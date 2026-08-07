import json
import re
import os
import logging
from datetime import datetime

from openai import OpenAI

from db import get_connection, get_priority_words, upsert_word_definition, _db_execute, DB_TYPE
from word_cache import prime as prime_word_cache
from article_store import clear_article_cache

logger = logging.getLogger("english_daily")

TOPICS = [
    "Artificial Intelligence and the Future of Work",
    "Climate Change and Global Policy",
    "The Evolution of Social Media and Mental Health",
    "Economic Inequality in Developed Nations",
    "Space Exploration: Public vs. Private",
    "The Philosophy of Free Will and Neuroscience",
    "Globalization and Cultural Identity",
    "Advances in Gene Editing and Bioethics",
    "Urbanization and Smart Cities",
    "The History and Future of Democracy",
    "Quantum Computing and Cybersecurity",
    "The Psychology of Decision-Making",
    "Renewable Energy and Geopolitics",
    "The Ethics of Autonomous Weapons",
    "Longevity Science and Population Aging",
    "Digital Privacy in the Age of Surveillance",
    "The Economics of Space Tourism",
    "Language Evolution in the Internet Age",
    "Food Security and Agricultural Technology",
    "The Cognitive Science of Learning",
]

_topic_index_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "topic_index.txt")
_prompt_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")


def _get_next_topic():
    os.makedirs(os.path.dirname(_topic_index_path), exist_ok=True)
    try:
        with open(_topic_index_path) as f:
            idx = int(f.read().strip())
    except (FileNotFoundError, ValueError):
        idx = 0
    topic = TOPICS[idx % len(TOPICS)]
    with open(_topic_index_path, "w") as f:
        f.write(str((idx + 1) % len(TOPICS)))
    return topic


def _load_prompt_template(name):
    with open(os.path.join(_prompt_dir, name), encoding="utf-8") as f:
        return f.read()


def _parse_json_response(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1).strip()
    return json.loads(text)


def _get_client():
    return OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )


def validate_article(data):
    """Validate generated article quality before storing."""
    errors = []
    content = data.get("content", "")
    content_lower = content.lower()

    def contains_word(text, word):
        return bool(re.search(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])", text, re.IGNORECASE))

    # 1. Words in glossary must appear in the article
    glossary_words = set()
    missing_words = []
    for g in data.get("glossary", []):
        w = g["word"].lower().strip()
        glossary_words.add(w)
        # Check for exact word presence instead of substring matching.
        if len(w) >= 3 and not contains_word(content, w):
            missing_words.append(g["word"])
    if missing_words:
        errors.append(f"Glossary words not found in article: {', '.join(missing_words[:10])}")

    # 2. Keep the glossary focused so generation does not turn into a rare-word list.
    glossary_count = len(data.get("glossary", []))
    if glossary_count < 18:
        errors.append(f"Glossary too short: {glossary_count} entries (minimum 18)")
    if glossary_count > 32:
        errors.append(f"Glossary too long: {glossary_count} entries (maximum 32)")

    rare_markers = ("超纲", "生僻", "低频", "rare", "c2", "c1+")
    rare_entries = [
        g.get("word", "") for g in data.get("glossary", [])
        if any(marker in str(g.get("difficulty_level", "")).lower() for marker in rare_markers)
    ]
    if len(rare_entries) > 5:
        errors.append(f"Too many rare/domain-specific glossary entries: {len(rare_entries)}")

    # 3. Word count must be in range
    word_count = len(content.split())
    if word_count < 300:
        errors.append(f"Article too short: {word_count} words (minimum 300)")
    if word_count > 600:
        errors.append(f"Article too long: {word_count} words (maximum 600)")

    # 4. Must have exercises
    exercise_count = len(data.get("exercises", []))
    if exercise_count < 3:
        errors.append(f"Too few exercises: {exercise_count} (minimum 3)")

    # 4b. Must have reading questions
    rq = data.get("reading_questions", [])
    if len(rq) < 5:
        errors.append(f"Too few reading questions: {len(rq)} (minimum 5)")
    required_types = {"main_idea", "detail", "inference", "vocabulary", "attitude"}
    rq_types = {q.get("question_type", "") for q in rq}
    missing_types = required_types - rq_types
    if missing_types:
        errors.append(f"Missing question types: {missing_types}")

    # 4c. Must have a complete cloze exercise with visible blank markers.
    cloze = data.get("cloze", {})
    if not cloze or not cloze.get("passage_text"):
        errors.append("Missing cloze exercise")
    cloze_blanks = cloze.get("blanks", [])
    if len(cloze_blanks) != 10:
        errors.append(f"Invalid cloze blank count: {len(cloze_blanks)} (must be exactly 10)")
    markers = re.findall(r"__(\d+)__", cloze.get("passage_text", ""))
    expected_markers = [str(i) for i in range(1, 11)]
    if markers != expected_markers:
        errors.append("Cloze passage must contain __1__ through __10__ exactly once and in order")
    blank_indexes = [str(b.get("blank_index")) for b in cloze_blanks]
    if blank_indexes != expected_markers:
        errors.append("Cloze blank_index values must be exactly 1 through 10")
    for b in cloze_blanks:
        options = b.get("options", [])
        if len(options) != 4 or b.get("correct_answer") not in options:
            errors.append(f"Invalid cloze options for blank {b.get('blank_index')}")

    # 5. Difficulty fields must be present
    if not data.get("difficulty_score"):
        errors.append("Missing difficulty_score")
    if not data.get("cefr_level"):
        errors.append("Missing cefr_level")
    else:
        try:
            if float(data.get("difficulty_score")) > 8.2:
                errors.append("Difficulty score above daily target: maximum 8.2")
        except (TypeError, ValueError):
            errors.append("Invalid difficulty_score")

    # 6. Chinese content must have matching paragraph count
    en_paras = len([p for p in data["content"].split("\n\n") if p.strip()])
    zh_paras = len([p for p in data.get("chinese_content", "").split("\n\n") if p.strip()])
    if abs(en_paras - zh_paras) > 2:
        errors.append(f"Paragraph count mismatch: EN={en_paras}, ZH={zh_paras}")

    # 7. Title must be present
    if not data.get("title") or len(data["title"]) < 3:
        errors.append("Title too short or missing")

    # 8. Chinese title must be present
    if not data.get("chinese_title"):
        errors.append("Missing chinese_title")

    if errors:
        logger.warning(f"Article validation issues: {'; '.join(errors)}")

    # Return True if no blocking errors (we allow warnings for some issues)
    blocking = [e for e in errors if any(kw in e for kw in (
        "Missing", "Too few exercises", "Too few reading questions",
        "Missing question types", "Missing cloze", "Invalid cloze",
        "Cloze passage", "Cloze blank_index", "Invalid cloze options",
        "Glossary too short", "Glossary too long", "Too many rare",
        "Difficulty score above", "Invalid difficulty_score",
        "Article too short", "Article too long"
    ))]
    if blocking:
        raise ValueError(f"Article validation failed: {'; '.join(blocking)}")

    logger.info(
        f"Article validated: {word_count} words, {glossary_count} glossary entries, "
        f"{exercise_count} exercises, {len(rq)} reading questions, "
        f"{len(cloze_blanks)} cloze blanks, "
        f"difficulty {data.get('difficulty_score', 'N/A')}, "
        f"CEFR {data.get('cefr_level', 'N/A')}"
    )
    return True


def generate_article():
    db = get_connection()
    review_words_list = get_priority_words(db)
    review_words = ", ".join(review_words_list) if review_words_list else "none yet (this is the first article)"

    topic = _get_next_topic()
    template = _load_prompt_template("article_gen.txt")
    prompt = template.format(topic=topic, review_words=review_words)

    client = _get_client()
    raw = None

    base_prompt = prompt
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="deepseek-chat",
                max_tokens=8192,
                temperature=0.8,
                messages=[{"role": "user", "content": prompt}],
                timeout=180,
            )
            raw = resp.choices[0].message.content
            data = _parse_json_response(raw)
            validate_article(data)
            break
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Generation attempt {attempt + 1} failed: {e}")
            if attempt == 2:
                raw_text = raw[:500] if raw else "N/A"
                raise RuntimeError(
                    f"Failed to generate valid article after 3 attempts: {e}\n\nRaw (truncated):\n{raw_text}"
                ) from e
            prompt = base_prompt + "\n\n"
            prompt += (
                f"Your previous response failed validation: {e}\n"
                "Regenerate the entire response. Output ONLY valid JSON matching the requested schema exactly. "
                "No markdown fences, no extra text. Double-check vocabulary limits and cloze markers."
            )

    now = datetime.now()
    if DB_TYPE == "mysql":
        now_str = now
    else:
        now_str = now.isoformat()

    content = data["content"]
    word_count = len(content.split())

    article_id = _db_execute(
        db,
        "INSERT INTO articles (title, content, chinese_title, chinese_content, "
        "source, word_count, difficulty_level, difficulty_score, cefr_level, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            data["title"], content, data["chinese_title"], data["chinese_content"],
            data.get("source", ""), word_count,
            data.get("difficulty_level", ""),
            data.get("difficulty_score"),
            data.get("cefr_level", ""),
            now_str,
        ),
    )

    glossary_count = 0
    generated_definitions = []
    for g in data.get("glossary", []):
        glossary_word = g["word"].strip().lower()
        definition = {
            "word": glossary_word,
            "part_of_speech": g.get("part_of_speech", ""),
            "chinese_meaning": g["chinese_meaning"],
            "sentence_example": g.get("sentence_example", ""),
            "difficulty_level": g.get("difficulty_level", "考研高频"),
        }
        _db_execute(
            db,
            "INSERT INTO glossary (article_id, word, part_of_speech, chinese_meaning, "
            "sentence_example, difficulty_level) VALUES (%s, %s, %s, %s, %s, %s)",
            (article_id, glossary_word, definition["part_of_speech"], definition["chinese_meaning"],
             g.get("sentence_example", ""), g.get("difficulty_level", "考研高频")),
        )
        upsert_word_definition(
            db,
            definition["word"],
            definition["part_of_speech"],
            definition["chinese_meaning"],
            definition["sentence_example"],
            definition["difficulty_level"],
        )
        generated_definitions.append(definition)
        glossary_count += 1

    for i, ex in enumerate(data.get("exercises", [])):
        _db_execute(
            db,
            "INSERT INTO translation_exercises (article_id, sentence_index, "
            "english_sentence, reference_translation) VALUES (%s, %s, %s, %s)",
            (article_id, i, ex["english_sentence"], ex["reference_translation"]),
        )

    # Store reading questions
    for q in data.get("reading_questions", []):
        _db_execute(
            db,
            "INSERT INTO reading_questions (article_id, question_type, question_text, "
            "option_a, option_b, option_c, option_d, correct_answer, explanation_cn) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (article_id, q["question_type"], q["question_text"],
             q["option_a"], q["option_b"], q["option_c"], q["option_d"],
             q["correct_answer"].upper(), q["explanation_cn"]),
        )

    # Store cloze exercise
    cloze_data = data.get("cloze", {})
    if cloze_data and cloze_data.get("passage_text"):
        _db_execute(
            db,
            "INSERT INTO cloze_exercises (article_id, passage_text, blanks_json) "
            "VALUES (%s, %s, %s)",
            (article_id, cloze_data["passage_text"],
             json.dumps(cloze_data.get("blanks", []), ensure_ascii=False)),
        )

    _db_execute(db, "UPDATE articles SET is_active = 0 WHERE id != %s", (article_id,))

    db.commit()
    db.close()
    clear_article_cache()
    prime_word_cache(generated_definitions)

    logger.info(
        f"Article generated: id={article_id}, title='{data['title'][:50]}', "
        f"words={word_count}, glossary={glossary_count}, "
        f"difficulty={data.get('difficulty_score', 'N/A')}, "
        f"CEFR={data.get('cefr_level', 'N/A')}"
    )
    return article_id
