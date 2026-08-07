import os
import json
import logging
from datetime import datetime

from flask import Flask, g, render_template, request, jsonify, make_response
from dotenv import load_dotenv

load_dotenv()

# ── Logging setup ──────────────────────────────────────
os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "app.log"),
            encoding="utf-8",
        ),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("english_daily")

from db import (
    init_db, get_connection, record_word_lookup,
    update_word_status, delete_word_record,
    _db_fetch_one, _db_execute, _db_fetch, DB_TYPE,
)
from article_store import (
    get_today_article, get_article_by_id, list_articles,
    get_glossary_entry, get_stats, get_vocabulary,
)
from word_cache import get as get_cached_word, set_value as cache_word
from generator import generate_article
from translate_service import review_translation

app = Flask(__name__)

logger.info("Application starting")

# Ensure DB tables exist on every startup
init_db()


def get_db():
    if "db" not in g:
        g.db = get_connection()
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db:
        db.close()


# ── Page routes ────────────────────────────────────────

@app.route("/")
def index():
    resp = make_response(render_template("index.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/vocabulary")
def vocab_page():
    resp = make_response(render_template("vocabulary.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/flashcard")
def flashcard_page():
    resp = make_response(render_template("flashcard.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/writing")
def writing_page():
    resp = make_response(render_template("writing.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/mistakes")
def mistakes_page():
    resp = make_response(render_template("mistakes.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


# ── Health ─────────────────────────────────────────────

@app.route("/api/health")
def api_health():
    try:
        db = get_db()
        row = _db_fetch_one(db, "SELECT COUNT(*) AS cnt FROM articles")
        article_count = row["cnt"] if row else 0
        return jsonify({
            "status": "ok",
            "article_count": article_count,
            "server_time": datetime.now().isoformat(),
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Article APIs ──────────────────────────────────────

@app.route("/api/article/today")
def api_article_today():
    db = get_db()
    article = get_today_article(db)
    if not article:
        return jsonify({"error": "今日文章尚未生成"}), 404
    return jsonify(article)


@app.route("/api/article/<int:article_id>")
def api_article_by_id(article_id):
    db = get_db()
    article = get_article_by_id(db, article_id)
    if not article:
        return jsonify({"error": "文章不存在"}), 404
    return jsonify(article)


@app.route("/api/articles")
def api_list_articles():
    db = get_db()
    return jsonify(list_articles(db))


# ── Word APIs ─────────────────────────────────────────

def _find_local_word(db, word):
    key = word.strip().lower()
    cached = get_cached_word(key)
    if cached:
        return cached

    entry = _db_fetch_one(
        db,
        "SELECT word, part_of_speech, chinese_meaning, sentence_example, difficulty_level "
        "FROM word_definitions WHERE word = %s",
        (key,),
    )
    if not entry:
        entry = get_glossary_entry(db, key)
    if entry:
        cache_word(entry)
    return entry

@app.route("/api/word/<word>")
def api_word_lookup(word):
    db = get_db()
    entry = _find_local_word(db, word)
    if not entry:
        return jsonify({"error": "词汇表中未找到该单词"}), 404
    return jsonify(entry)


@app.route("/api/word/<word>/lookup")
def api_word_local_lookup(word):
    """Look up a pre-generated local definition; never call AI during reading."""
    import re

    word = word.strip().lower()
    if not re.fullmatch(r"[a-z][a-z'-]{0,48}", word):
        return jsonify({"error": "无效单词"}), 400

    db = get_db()
    entry = _find_local_word(db, word)
    if not entry:
        return jsonify({"error": "该词暂无本地释义"}), 404
    return jsonify(entry)


@app.route("/api/word/mark-unfamiliar", methods=["POST"])
def api_mark_unfamiliar():
    """User explicitly marks a word as unfamiliar — tracked for repetition."""
    data = request.get_json()
    if not data or "word" not in data:
        return jsonify({"error": "缺少 word 字段"}), 400
    db = get_db()
    record_word_lookup(db, data["word"], data.get("article_id"))
    logger.info(f"Word marked unfamiliar: {data['word']}")
    return jsonify({"status": "ok"})


# ── Vocabulary notebook APIs ──────────────────────────

@app.route("/api/vocabulary", methods=["GET"])
def api_vocabulary():
    db = get_db()
    status_filter = request.args.get("status", "")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    result = get_vocabulary(db, status_filter, page, per_page)
    return jsonify(result)


@app.route("/api/vocabulary/<word>", methods=["PATCH"])
def api_update_word_status(word):
    data = request.get_json()
    if not data or "status" not in data:
        return jsonify({"error": "缺少 status 字段"}), 400
    db = get_db()
    try:
        update_word_status(db, word, data["status"])
        logger.info(f"Word status updated: {word} -> {data['status']}")
        return jsonify({"status": "ok"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/vocabulary/<word>", methods=["DELETE"])
def api_delete_word(word):
    db = get_db()
    delete_word_record(db, word)
    logger.info(f"Word removed from vocabulary: {word}")
    return jsonify({"status": "ok"})


# ── Translation APIs ──────────────────────────────────

@app.route("/api/translate/submit", methods=["POST"])
def api_translate_submit():
    data = request.get_json()
    if not data or "exercise_id" not in data or "user_translation" not in data:
        return jsonify({"error": "缺少必填字段"}), 400

    db = get_db()
    exercise = _db_fetch_one(db, "SELECT * FROM translation_exercises WHERE id = %s", (data["exercise_id"],))

    if not exercise:
        return jsonify({"error": "练习不存在"}), 404
    if exercise["user_translation"] is not None:
        return jsonify({"error": "该句已提交过翻译"}), 409

    try:
        result = review_translation(
            exercise["english_sentence"],
            exercise["reference_translation"],
            data["user_translation"],
        )
    except Exception as e:
        logger.error(f"Translation review failed: {e}")
        return jsonify({"error": f"AI 批改失败: {e}"}), 502

    _db_execute(
        db,
        "UPDATE translation_exercises SET user_translation = %s, feedback = %s, "
        "score = %s, submitted_at = %s WHERE id = %s",
        (data["user_translation"], result["feedback"], result["score"],
         "NOW()" if DB_TYPE == "mysql" else datetime.now().isoformat(),
         data["exercise_id"]),
    )
    db.commit()
    logger.info(f"Translation submitted for exercise {data['exercise_id']}, score: {result['score']}")

    return jsonify({
        "feedback": result["feedback"],
        "score": result["score"],
        "key_issues": result.get("key_issues", []),
        "reference_translation": exercise["reference_translation"],
    })


# ── Stats API ─────────────────────────────────────────

@app.route("/api/stats")
def api_stats():
    db = get_db()
    return jsonify(get_stats(db))


# ── Reading Questions APIs ─────────────────────────────

@app.route("/api/reading/submit", methods=["POST"])
def api_reading_submit():
    """Submit reading comprehension answers and get results."""
    data = request.get_json()
    if not data or "article_id" not in data or "answers" not in data:
        return jsonify({"error": "缺少必填字段"}), 400

    db = get_db()
    questions = _db_fetch(
        db,
        "SELECT id, question_type, question_text, option_a, option_b, option_c, option_d, "
        "correct_answer, explanation_cn FROM reading_questions WHERE article_id = %s",
        (data["article_id"],),
    )

    if not questions:
        return jsonify({"error": "该文章没有阅读题"}), 404

    answers = data["answers"]  # {question_id: "A"}
    results = []
    correct_count = 0

    for q in questions:
        qid = str(q["id"])
        user_ans = answers.get(qid, "").upper()
        is_correct = user_ans == q["correct_answer"]
        if is_correct:
            correct_count += 1

        now_str = "NOW()" if DB_TYPE == "mysql" else datetime.now().isoformat()
        _db_execute(
            db,
            "INSERT INTO reading_answer_records (question_id, user_answer, is_correct, answered_at) "
            "VALUES (%s, %s, %s, %s)",
            (q["id"], user_ans or None, 1 if is_correct else 0, now_str),
        )

        # Record mistakes
        if not is_correct and user_ans:
            now_str2 = "NOW()" if DB_TYPE == "mysql" else datetime.now().isoformat()
            _db_execute(
                db,
                "INSERT INTO mistake_notebook (mistake_type, ref_id, question_text, "
                "user_wrong_answer, correct_answer, explanation, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                ("reading", q["id"], q["question_text"][:500],
                 user_ans, q["correct_answer"], q["explanation_cn"][:1000], now_str2),
            )

        results.append({
            "question_id": q["id"],
            "question_type": q["question_type"],
            "question_text": q["question_text"],
            "options": {"A": q["option_a"], "B": q["option_b"], "C": q["option_c"], "D": q["option_d"]},
            "user_answer": user_ans,
            "correct_answer": q["correct_answer"],
            "is_correct": is_correct,
            "explanation_cn": q["explanation_cn"],
        })

    db.commit()

    score = round(correct_count / len(questions) * 100)
    return jsonify({
        "score": score,
        "correct_count": correct_count,
        "total": len(questions),
        "results": results,
    })


# ── Cloze APIs ─────────────────────────────────────────

@app.route("/api/cloze/submit", methods=["POST"])
def api_cloze_submit():
    """Submit cloze exercise answers."""
    data = request.get_json()
    if not data or "cloze_id" not in data or "answers" not in data:
        return jsonify({"error": "缺少必填字段"}), 400

    db = get_db()
    cloze = _db_fetch_one(
        db, "SELECT * FROM cloze_exercises WHERE id = %s", (data["cloze_id"],),
    )
    if not cloze:
        return jsonify({"error": "完形填空不存在"}), 404

    blanks = json.loads(cloze["blanks_json"]) if isinstance(cloze["blanks_json"], str) else cloze["blanks_json"]
    user_answers = data["answers"]  # {blank_index: "chosen_option"}
    correct_count = 0
    results = []

    for b in blanks:
        bi = str(b["blank_index"])
        user_ans = user_answers.get(bi, "")
        is_correct = user_ans == b["correct_answer"]
        if is_correct:
            correct_count += 1
        results.append({
            "blank_index": b["blank_index"],
            "user_answer": user_ans,
            "correct_answer": b["correct_answer"],
            "options": b["options"],
            "is_correct": is_correct,
            "explanation_cn": b.get("explanation_cn", ""),
        })

        # Record mistakes
        if not is_correct:
            now_str = "NOW()" if DB_TYPE == "mysql" else datetime.now().isoformat()
            _db_execute(
                db,
                "INSERT INTO mistake_notebook (mistake_type, ref_id, question_text, "
                "user_wrong_answer, correct_answer, explanation, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                ("cloze", cloze["id"], cloze["passage_text"][:300],
                 user_ans, b["correct_answer"], b.get("explanation_cn", "")[:500], now_str),
            )

    now_str = "NOW()" if DB_TYPE == "mysql" else datetime.now().isoformat()
    _db_execute(
        db,
        "INSERT INTO cloze_answer_records (cloze_id, user_answers_json, score, submitted_at) "
        "VALUES (%s, %s, %s, %s)",
        (data["cloze_id"], json.dumps(user_answers, ensure_ascii=False),
         correct_count, now_str),
    )
    db.commit()

    return jsonify({
        "correct_count": correct_count,
        "total": len(blanks),
        "score": round(correct_count / len(blanks) * 100),
        "results": results,
    })


# ── Writing APIs ───────────────────────────────────────

@app.route("/api/writing/generate", methods=["POST"])
def api_writing_generate():
    """Generate a new writing exercise (small or large essay)."""
    data = request.get_json()
    writing_type = data.get("type", "essay_large")  # essay_small, essay_large
    topic = data.get("topic", "")

    from generator import _get_client, _parse_json_response

    prompt = f"""You are a 考研 English writing instructor. Generate a writing exercise.

Type: {writing_type}
{"Topic suggestion: " + topic if topic else "Choose a topic suitable for 考研 English writing."}

Requirements:
- For "essay_small" (小作文/应用文): Generate a practical writing task (letter, notice, memo, report, email). Word limit: 100-150 words.
- For "essay_large" (大作文): Generate an essay prompt based on a described scenario/chart/picture. The prompt should describe a visual (chart trend, social phenomenon, cartoon scenario) in Chinese and ask for analysis and commentary. Word limit: 160-200 words.

Output JSON:
{{
  "prompt_cn": "写作题目/要求（中文）",
  "prompt_en": "English translation of the prompt",
  "requirements": "具体写作要求：内容要点、结构提示（中文，3-5条）",
  "reference_essay": "A model essay in English that would score well in 考研"
}}

Output raw JSON only, no markdown fences."""

    client = _get_client()
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            max_tokens=2048,
            temperature=0.8,
            messages=[{"role": "user", "content": prompt}],
            timeout=120,
        )
        result = _parse_json_response(resp.choices[0].message.content)

        now_str = "NOW()" if DB_TYPE == "mysql" else datetime.now().isoformat()
        db = get_db()
        ex_id = _db_execute(
            db,
            "INSERT INTO writing_exercises (writing_type, prompt_cn, prompt_en, requirements, "
            "reference_essay, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (writing_type, result["prompt_cn"], result.get("prompt_en", ""),
             result.get("requirements", ""), result.get("reference_essay", ""), now_str),
        )
        db.commit()
        logger.info(f"Writing exercise generated: id={ex_id}, type={writing_type}")
        return jsonify({"id": ex_id, **result})
    except Exception as e:
        logger.error(f"Writing generation failed: {e}")
        return jsonify({"error": f"生成失败: {e}"}), 500


@app.route("/api/writing/submit", methods=["POST"])
def api_writing_submit():
    """Submit user essay for AI review."""
    data = request.get_json()
    if not data or "exercise_id" not in data or "essay" not in data:
        return jsonify({"error": "缺少必填字段"}), 400

    db = get_db()
    exercise = _db_fetch_one(db, "SELECT * FROM writing_exercises WHERE id = %s", (data["exercise_id"],))
    if not exercise:
        return jsonify({"error": "练习不存在"}), 404

    from generator import _get_client, _parse_json_response

    review_prompt = f"""You are a 考研 English writing grader. Evaluate the student's essay.

Prompt: {exercise["prompt_cn"]}
Requirements: {exercise.get("requirements", "")}
Reference Essay: {exercise.get("reference_essay", "")}

Student's Essay: {data["essay"]}

Score on these dimensions (each 1-10):
1. Content (内容完整性): Does it address all points in the prompt?
2. Structure (结构逻辑): Is the organization clear and logical?
3. Language (语言表达): Vocabulary variety, sentence complexity, academic register
4. Grammar (语法准确): Grammatical accuracy

Output JSON:
{{
  "score": <overall score 1-10>,
  "content_score": <1-10>,
  "structure_score": <1-10>,
  "language_score": <1-10>,
  "grammar_score": <1-10>,
  "feedback": "<detailed feedback in Chinese, 150-300 chars, be encouraging>",
  "corrections": ["<specific correction 1 in Chinese>", "<correction 2>", "<correction 3>"]
}}

Output raw JSON only, no markdown fences."""

    client = _get_client()
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            max_tokens=1024,
            temperature=0.3,
            messages=[{"role": "user", "content": review_prompt}],
            timeout=120,
        )
        result = _parse_json_response(resp.choices[0].message.content)

        now_str = "NOW()" if DB_TYPE == "mysql" else datetime.now().isoformat()
        _db_execute(
            db,
            "INSERT INTO writing_submissions (exercise_id, user_essay, score, feedback, submitted_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (data["exercise_id"], data["essay"], result.get("score"),
             json.dumps(result, ensure_ascii=False), now_str),
        )
        db.commit()
        logger.info(f"Writing submitted for exercise {data['exercise_id']}, score: {result.get('score')}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"Writing review failed: {e}")
        return jsonify({"error": f"批改失败: {e}"}), 502


@app.route("/api/writing/history", methods=["GET"])
def api_writing_history():
    """Get writing exercise history."""
    db = get_db()
    rows = _db_fetch(
        db,
        "SELECT w.id, w.writing_type, w.prompt_cn, w.created_at, "
        "s.score, s.submitted_at "
        "FROM writing_exercises w LEFT JOIN writing_submissions s ON w.id = s.exercise_id "
        "ORDER BY w.created_at DESC LIMIT 30"
    )
    return jsonify([dict(r) for r in rows])


# ── Flashcard / Spaced Repetition APIs ────────────────

@app.route("/api/flashcard/due", methods=["GET"])
def api_flashcard_due():
    """Get words due for review today."""
    db = get_db()
    limit = int(request.args.get("limit", 20))

    now_str = "NOW()" if DB_TYPE == "mysql" else datetime.now().isoformat()

    # First, seed spaced_repetition from word_lookups for new words
    _db_execute(
        db,
        "INSERT OR IGNORE INTO spaced_repetition (word, ease_factor, interval_days, repetitions, next_review_at) "
        "SELECT LOWER(wl.word), 2.5, 0, 0, '2020-01-01' "
        "FROM word_lookups wl WHERE wl.status IN ('unfamiliar', 'learning') "
        "AND LOWER(wl.word) NOT IN (SELECT LOWER(sr.word) FROM spaced_repetition sr)"
    )

    if DB_TYPE == "mysql":
        rows = _db_fetch(
            db,
            "SELECT sr.word, sr.ease_factor, sr.interval_days, sr.repetitions, "
            "g.part_of_speech, g.chinese_meaning, g.sentence_example "
            "FROM spaced_repetition sr "
            "LEFT JOIN glossary g ON LOWER(sr.word) = LOWER(g.word) "
            "WHERE sr.next_review_at <= NOW() "
            "ORDER BY sr.next_review_at ASC LIMIT %s",
            (limit,),
        )
    else:
        rows = _db_fetch(
            db,
            "SELECT sr.word, sr.ease_factor, sr.interval_days, sr.repetitions, "
            "g.part_of_speech, g.chinese_meaning, g.sentence_example "
            "FROM spaced_repetition sr "
            "LEFT JOIN glossary g ON LOWER(sr.word) = LOWER(g.word) "
            "WHERE sr.next_review_at <= datetime('now') "
            "ORDER BY sr.next_review_at ASC LIMIT ?",
            (limit,),
        )

    words = [dict(r) for r in rows]
    return jsonify({
        "due_count": len(words),
        "words": words,
        "total_tracked": _db_fetch_one(db, "SELECT COUNT(*) AS cnt FROM spaced_repetition")["cnt"],
    })


@app.route("/api/flashcard/review", methods=["POST"])
def api_flashcard_review():
    """Submit a flashcard review result (SM-2 algorithm)."""
    data = request.get_json()
    if not data or "word" not in data or "quality" not in data:
        return jsonify({"error": "缺少必填字段"}), 400

    word = data["word"].lower().strip()
    quality = int(data["quality"])  # 0-5 scale

    db = get_db()
    row = _db_fetch_one(
        db, "SELECT * FROM spaced_repetition WHERE LOWER(word) = %s", (word,),
    )
    if not row:
        return jsonify({"error": "单词不在复习计划中"}), 404

    # SM-2 algorithm
    ef = float(row["ease_factor"])
    interval = int(row["interval_days"])
    reps = int(row["repetitions"])

    if quality >= 3:
        if reps == 0:
            interval = 1
        elif reps == 1:
            interval = 6
        else:
            interval = int(round(interval * ef))
        reps += 1
    else:
        reps = 0
        interval = 1

    ef = max(1.3, ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))

    now_str = "NOW()" if DB_TYPE == "mysql" else datetime.now().isoformat()
    if DB_TYPE == "mysql":
        _db_execute(
            db,
            "UPDATE spaced_repetition SET ease_factor = %s, interval_days = %s, "
            "repetitions = %s, next_review_at = DATE_ADD(NOW(), INTERVAL %s DAY), "
            "last_review_at = NOW() WHERE LOWER(word) = %s",
            (ef, interval, reps, interval, word),
        )
        # Also update word_lookups status based on quality
        if reps >= 3:
            _db_execute(db, "UPDATE word_lookups SET status = 'learning' WHERE LOWER(word) = %s", (word,))
        if reps >= 7:
            _db_execute(db, "UPDATE word_lookups SET status = 'mastered' WHERE LOWER(word) = %s", (word,))
    else:
        _db_execute(
            db,
            "UPDATE spaced_repetition SET ease_factor = ?, interval_days = ?, "
            "repetitions = ?, next_review_at = datetime('now', '+' || ? || ' days'), "
            "last_review_at = datetime('now') WHERE LOWER(word) = ?",
            (ef, interval, reps, str(interval), word),
        )
        if reps >= 3:
            _db_execute(db, "UPDATE word_lookups SET status = 'learning' WHERE LOWER(word) = ?", (word,))
        if reps >= 7:
            _db_execute(db, "UPDATE word_lookups SET status = 'mastered' WHERE LOWER(word) = ?", (word,))

    db.commit()

    return jsonify({
        "word": word,
        "interval_days": interval,
        "repetitions": reps,
        "ease_factor": round(ef, 1),
        "next_review": f"{interval}天后",
    })


# ── Check-in / Streak APIs ────────────────────────────

def _calculate_streak(db):
    """Calculate current consecutive check-in streak."""
    rows = _db_fetch(db, "SELECT checkin_date FROM daily_checkins ORDER BY checkin_date DESC LIMIT 365")
    if not rows:
        return 0

    from datetime import timedelta
    dates = sorted(set(r["checkin_date"] for r in rows), reverse=True)
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    if dates[0] != today and dates[0] != yesterday:
        return 0

    streak = 1
    current = datetime.strptime(dates[0], "%Y-%m-%d")
    for d in dates[1:]:
        prev = current - timedelta(days=1)
        if datetime.strptime(d, "%Y-%m-%d") == prev:
            streak += 1
            current = prev
        else:
            break
    return streak


@app.route("/api/checkin", methods=["POST"])
def api_checkin():
    """Record daily check-in."""
    today = datetime.now().strftime("%Y-%m-%d")
    db = get_db()
    now_str = "NOW()" if DB_TYPE == "mysql" else datetime.now().isoformat()

    try:
        data = request.get_json() or {}
        article_id = data.get("article_id")
        _db_execute(
            db,
            "INSERT INTO daily_checkins (checkin_date, article_id, created_at) VALUES (%s, %s, %s)",
            (today, article_id, now_str),
        )
        db.commit()
    except Exception:
        return jsonify({"status": "already_checked_in", "date": today})

    streak = _calculate_streak(db)
    return jsonify({"status": "ok", "date": today, "streak": streak})


@app.route("/api/checkin/status", methods=["GET"])
def api_checkin_status():
    """Get today's check-in status and streak info."""
    today = datetime.now().strftime("%Y-%m-%d")
    db = get_db()

    today_row = _db_fetch_one(db, "SELECT * FROM daily_checkins WHERE checkin_date = %s", (today,))
    streak = _calculate_streak(db)

    # Get check-in dates for heatmap (last 365 days)
    year_ago = datetime.now().replace(year=datetime.now().year - 1).strftime("%Y-%m-%d")
    if DB_TYPE == "mysql":
        rows = _db_fetch(db,
            "SELECT checkin_date FROM daily_checkins WHERE checkin_date >= %s ORDER BY checkin_date",
            (year_ago,))
    else:
        rows = _db_fetch(db,
            "SELECT checkin_date FROM daily_checkins WHERE checkin_date >= ? ORDER BY checkin_date",
            (year_ago,))
    dates = [r["checkin_date"] for r in rows]

    return jsonify({
        "checked_in_today": today_row is not None,
        "streak": streak,
        "checkin_dates": dates,
    })


# ── Mistake Notebook APIs ─────────────────────────────

@app.route("/api/mistakes", methods=["GET"])
def api_mistakes():
    """Get mistake notebook entries."""
    db = get_db()
    mtype = request.args.get("type", "")  # reading, cloze, all
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    reviewed = request.args.get("reviewed", "")  # 0, 1, or empty for all

    base = "FROM mistake_notebook WHERE 1=1"
    params = []

    if mtype:
        base += " AND mistake_type = %s"
        params.append(mtype)
    if reviewed != "":
        base += " AND reviewed = %s"
        params.append(int(reviewed))

    total = _db_fetch(db, f"SELECT COUNT(*) AS cnt {base}", params)[0]["cnt"]
    offset = (page - 1) * per_page

    rows = _db_fetch(
        db,
        f"SELECT * {base} ORDER BY created_at DESC LIMIT %s OFFSET %s",
        params + [per_page, offset],
    )

    return jsonify({
        "mistakes": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
    })


@app.route("/api/mistakes/<int:mid>/review", methods=["POST"])
def api_mistake_review(mid):
    """Mark a mistake as reviewed."""
    db = get_db()
    _db_execute(db, "UPDATE mistake_notebook SET reviewed = 1 WHERE id = %s", (mid,))
    db.commit()
    return jsonify({"status": "ok"})


@app.route("/api/mistakes/stats", methods=["GET"])
def api_mistake_stats():
    """Get mistake statistics."""
    db = get_db()
    total = _db_fetch_one(db, "SELECT COUNT(*) AS cnt FROM mistake_notebook")["cnt"]
    unreviewed = _db_fetch_one(db, "SELECT COUNT(*) AS cnt FROM mistake_notebook WHERE reviewed = 0")["cnt"]
    by_type = _db_fetch(db,
        "SELECT mistake_type, COUNT(*) AS cnt FROM mistake_notebook GROUP BY mistake_type")
    return jsonify({
        "total": total,
        "unreviewed": unreviewed,
        "by_type": {r["mistake_type"]: r["cnt"] for r in by_type},
    })


# ── Manual trigger ────────────────────────────────────

@app.route("/api/generate", methods=["POST"])
def api_generate():
    today = datetime.now().strftime("%Y-%m-%d")
    db = get_db()
    existing = _db_fetch_one(db, "SELECT id FROM articles WHERE DATE(created_at) = %s", (today,))
    if existing:
        return jsonify({
            "status": "ok",
            "article_id": existing["id"],
            "message": "今日文章已存在",
        })

    try:
        article_id = generate_article()
        logger.info(f"Article generated manually, id={article_id}")
        return jsonify({"status": "ok", "article_id": article_id})
    except Exception as e:
        logger.error(f"Manual generation failed: {e}")
        return jsonify({"error": f"生成失败: {e}"}), 500


# ── Entrypoint ────────────────────────────────────────

if __name__ == "__main__":
    init_db()

    from scheduler import start_scheduler, generate_daily_article
    start_scheduler(app)
    try:
        generate_daily_article(app)
    except Exception as e:
        logger.warning(f"Startup article generation skipped: {e}")

    port = int(os.environ.get("PORT", "5000"))
    try:
        from waitress import serve
        logger.info(f"Starting Waitress on http://0.0.0.0:{port}")
        serve(app, host="0.0.0.0", port=port, threads=4)
    except ImportError:
        logger.warning("Waitress not installed, falling back to Flask dev server")
        app.run(host="0.0.0.0", port=port, debug=False)
