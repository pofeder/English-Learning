import json
import re
from collections import OrderedDict
from copy import deepcopy
from threading import RLock
from time import monotonic

from db import _db_fetch, _db_fetch_one
from word_cache import prime as prime_word_cache


ARTICLE_CACHE_TTL_SECONDS = 300
ARTICLE_LIST_CACHE_TTL_SECONDS = 120
_article_cache = OrderedDict()
_article_cache_lock = RLock()


def _get_cached(key):
    now = monotonic()
    with _article_cache_lock:
        item = _article_cache.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at <= now:
            _article_cache.pop(key, None)
            return None
        _article_cache.move_to_end(key)
        return deepcopy(value)


def _set_cached(key, value, ttl):
    with _article_cache_lock:
        _article_cache[key] = (monotonic() + ttl, deepcopy(value))
        _article_cache.move_to_end(key)
        while len(_article_cache) > 20:
            _article_cache.popitem(last=False)


def clear_article_cache(article_id=None):
    """Clear cached article responses after article data or answers change."""
    with _article_cache_lock:
        if article_id is None:
            _article_cache.clear()
            return
        _article_cache.pop(f"article:{article_id}", None)
        _article_cache.pop("today", None)
        _article_cache.pop("list", None)


def _load_article_word_definitions(db, content):
    """Load all known word definitions used by an article in one query."""
    words = sorted({
        word.lower()
        for word in re.findall(r"\b[A-Za-z][A-Za-z'-]{0,48}\b", content or "")
    })
    if not words:
        return []

    # Keep the response bounded if an unusually long article is imported.
    words = words[:1200]
    placeholders = ", ".join(["%s"] * len(words))
    return _db_fetch(
        db,
        "SELECT word, part_of_speech, chinese_meaning, sentence_example, difficulty_level "
        f"FROM word_definitions WHERE word IN ({placeholders})",
        words,
    )


def _normalize_cloze_passage(passage_text, blanks):
    """Repair older generated cloze records that saved answers but no markers."""
    text = passage_text or ""
    markers = set(re.findall(r"__(\d+)__", text))
    if markers:
        return text

    for blank in sorted(blanks, key=lambda item: item.get("blank_index", 0)):
        index = blank.get("blank_index")
        answer = str(blank.get("correct_answer", "")).strip()
        if not index or not answer:
            continue
        pattern = r"(?<![A-Za-z])" + re.escape(answer) + r"(?![A-Za-z])"
        text, count = re.subn(
            pattern,
            lambda match, i=index: f"__{i}__",
            text,
            count=1,
            flags=re.IGNORECASE,
        )
        if count == 0:
            # Keep the question visible even when a legacy answer no longer
            # appears verbatim in the passage.
            text += f" __{index}__"
    return text


def _fetch_article(db, sql, params):
    row = _db_fetch_one(db, sql, params)
    if not row:
        return None

    article = dict(row)
    article["glossary"] = _db_fetch(
        db,
        "SELECT id, word, part_of_speech, chinese_meaning, sentence_example, difficulty_level "
        "FROM glossary WHERE article_id = %s",
        (article["id"],),
    )
    prime_word_cache(article["glossary"])
    article["word_definitions"] = _load_article_word_definitions(db, article.get("content", ""))
    prime_word_cache(article["word_definitions"])
    article["exercises"] = _db_fetch(
        db,
        "SELECT id, sentence_index, english_sentence, reference_translation, "
        "user_translation, feedback, score, submitted_at "
        "FROM translation_exercises WHERE article_id = %s ORDER BY sentence_index",
        (article["id"],),
    )
    article["reading_questions"] = _db_fetch(
        db,
        "SELECT id, question_type, question_text, option_a, option_b, option_c, option_d, "
        "explanation_cn FROM reading_questions WHERE article_id = %s",
        (article["id"],),
    )
    # Fetch all latest answer records in one query instead of one query per question.
    question_ids = [q["id"] for q in article["reading_questions"]]
    latest_answers = {}
    if question_ids:
        placeholders = ", ".join(["%s"] * len(question_ids))
        answer_rows = _db_fetch(
            db,
            "SELECT question_id, user_answer, is_correct, answered_at "
            f"FROM reading_answer_records WHERE question_id IN ({placeholders}) "
            "ORDER BY answered_at DESC",
            question_ids,
        )
        for rec in answer_rows:
            latest_answers.setdefault(rec["question_id"], rec)
    for q in article["reading_questions"]:
        rec = latest_answers.get(q["id"])
        q["user_answer"] = rec["user_answer"] if rec else None
        q["is_correct"] = rec["is_correct"] if rec else None

    cloze_rows = _db_fetch(
        db,
        "SELECT id, passage_text, blanks_json FROM cloze_exercises WHERE article_id = %s LIMIT 1",
        (article["id"],),
    )
    if cloze_rows:
        cloze = cloze_rows[0]
        blanks = json.loads(cloze["blanks_json"]) if isinstance(cloze["blanks_json"], str) else cloze["blanks_json"]
        article["cloze"] = {
            "id": cloze["id"],
            "passage_text": _normalize_cloze_passage(cloze["passage_text"], blanks),
            "blanks": blanks,
        }
        rec = _db_fetch_one(
            db,
            "SELECT user_answers_json, score, submitted_at FROM cloze_answer_records "
            "WHERE cloze_id = %s ORDER BY submitted_at DESC LIMIT 1",
            (cloze["id"],),
        )
        if rec:
            article["cloze"]["user_answers"] = json.loads(rec["user_answers_json"]) if isinstance(rec["user_answers_json"], str) else rec["user_answers_json"]
            article["cloze"]["score"] = rec["score"]
    else:
        article["cloze"] = None

    return article


def get_today_article(db):
    cached = _get_cached("today")
    if cached is not None:
        return cached
    article = _fetch_article(
        db,
        "SELECT * FROM articles WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1",
        (),
    )
    if article:
        _set_cached("today", article, ARTICLE_CACHE_TTL_SECONDS)
    return article


def get_article_by_id(db, article_id):
    key = f"article:{article_id}"
    cached = _get_cached(key)
    if cached is not None:
        return cached
    article = _fetch_article(db, "SELECT * FROM articles WHERE id = %s", (article_id,))
    if article:
        _set_cached(key, article, ARTICLE_CACHE_TTL_SECONDS)
    return article


def list_articles(db):
    cached = _get_cached("list")
    if cached is not None:
        return cached
    rows = _db_fetch(db, "SELECT id, title, created_at FROM articles ORDER BY created_at DESC")
    articles = [{"id": r["id"], "title": r["title"], "created_at": str(r["created_at"])} for r in rows]
    _set_cached("list", articles, ARTICLE_LIST_CACHE_TTL_SECONDS)
    return articles


def get_glossary_entry(db, word):
    key = word.lower().strip()
    entry = _db_fetch_one(
        db,
        "SELECT id, word, part_of_speech, chinese_meaning, sentence_example, difficulty_level "
        "FROM glossary WHERE word = %s ORDER BY id DESC LIMIT 1",
        (key,),
    )
    if entry:
        return entry
    # Compatibility fallback for legacy rows that were stored with mixed case.
    return _db_fetch_one(
        db,
        "SELECT id, word, part_of_speech, chinese_meaning, sentence_example, difficulty_level "
        "FROM glossary WHERE LOWER(word) = %s ORDER BY id DESC LIMIT 1",
        (key,),
    )


def get_stats(db):
    rows = _db_fetch(db, "SELECT COUNT(DISTINCT word) AS cnt FROM word_lookups")
    word_count = rows[0]["cnt"] if rows else 0
    rows = _db_fetch(db, "SELECT COALESCE(SUM(lookup_count), 0) AS total FROM word_lookups")
    total_lookups = rows[0]["total"] if rows else 0
    rows = _db_fetch(db, "SELECT COUNT(*) AS cnt FROM translation_exercises WHERE user_translation IS NOT NULL")
    total_exercises = rows[0]["cnt"] if rows else 0
    rows = _db_fetch(db, "SELECT AVG(score) AS avg_score FROM translation_exercises WHERE score IS NOT NULL")
    avg_score_val = rows[0]["avg_score"] if rows else None
    avg_score = round(float(avg_score_val), 1) if avg_score_val is not None else None

    top_words = _db_fetch(db, "SELECT word, lookup_count, status FROM word_lookups ORDER BY lookup_count DESC LIMIT 10")

    return {
        "unique_words": word_count,
        "total_lookups": total_lookups,
        "total_exercises": total_exercises,
        "avg_score": avg_score,
        "top_words": [{"word": r["word"], "count": r["lookup_count"], "status": r["status"]} for r in top_words],
    }


def get_vocabulary(db, status_filter="", page=1, per_page=50):
    status_counts = {}
    for r in _db_fetch(db, "SELECT status, COUNT(*) AS cnt FROM word_lookups GROUP BY status"):
        status_counts[r["status"]] = r["cnt"]
    counts = {
        "unfamiliar": status_counts.get("unfamiliar", 0),
        "learning": status_counts.get("learning", 0),
        "mastered": status_counts.get("mastered", 0),
        "total": sum(status_counts.values()),
    }

    base = "FROM word_lookups w LEFT JOIN glossary g ON LOWER(w.word) = LOWER(g.word)"
    params = []
    where = ""
    if status_filter in ("unfamiliar", "learning", "mastered"):
        where = " WHERE w.status = %s"
        params.append(status_filter)

    total = _db_fetch(db, f"SELECT COUNT(*) AS total {base}{where}", params)[0]["total"]
    offset = (page - 1) * per_page

    rows = _db_fetch(
        db,
        f"SELECT w.word, w.lookup_count, w.status, w.looked_up_at, "
        f"g.part_of_speech, g.chinese_meaning "
        f"{base}{where} ORDER BY w.lookup_count DESC, w.looked_up_at DESC "
        f"LIMIT %s OFFSET %s",
        params + [per_page, offset],
    )

    words = []
    for r in rows:
        words.append({
            "word": r["word"],
            "lookup_count": r["lookup_count"],
            "status": r["status"],
            "last_looked_up": str(r["looked_up_at"]) if r["looked_up_at"] else None,
            "part_of_speech": r.get("part_of_speech", ""),
            "chinese_meaning": r.get("chinese_meaning", ""),
        })

    return {"words": words, "total": total, "page": page, "per_page": per_page, "counts": counts}
