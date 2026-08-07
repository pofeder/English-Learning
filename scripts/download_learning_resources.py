"""Download and import local learning resources.

Examples:
  python scripts/download_learning_resources.py download \
      --url https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv \
      --output data/downloads/ecdict.csv

  python scripts/download_learning_resources.py import-dictionary \
      --path data/downloads/ecdict.csv

  python scripts/download_learning_resources.py download-question-bank \
      --url https://example.com/licensed-question-bank.json \
      --output data/downloads/question_bank.json

Dictionary input accepts JSON or CSV. JSON fields: word, chinese_meaning/translation,
part_of_speech, sentence_example/example, difficulty_level.
Question-bank files are downloaded and format-checked for later import; only sources
the user is allowed to store should be used.
"""

import argparse
import csv
import json
import os
import re
import sys
import urllib.request
from datetime import datetime


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def download_file(url, output):
    output_path = os.path.abspath(output)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "EnglishDaily/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response, open(output_path, "wb") as target:
        total = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > 100 * 1024 * 1024:
                raise ValueError("resource is larger than the 100 MB safety limit")
            target.write(chunk)
    print(f"Downloaded {total:,} bytes -> {output_path}")
    return output_path


def _first(item, *keys):
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


EXAM_TAGS = {"ky"}
COMMON_TAGS = {"cet4", "cet6", "gk", "zk"}
COMMON_FREQUENCY_MAX = 10000


def _row_tags(row):
    raw = _first(row, "tag", "tags").lower()
    return set(part for part in re.split(r"[\s,;|]+", raw) if part)


def _row_frequency(row):
    raw = _first(row, "frq", "frequency", "freq")
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 0


def _matches_profile(row, profile):
    if profile == "all":
        return True

    # Small JSON dictionaries often do not carry ECDICT tags or frequency
    # metadata. Keep those entries instead of filtering the whole file out.
    has_metadata = any(
        str(row.get(key, "")).strip()
        for key in ("tag", "tags", "frq", "frequency", "freq")
    )
    if not has_metadata:
        return True

    tags = _row_tags(row)
    is_exam = bool(tags & EXAM_TAGS)
    is_common = bool(tags & COMMON_TAGS) or (
        0 < _row_frequency(row) <= COMMON_FREQUENCY_MAX
    )

    if profile == "exam":
        return is_exam
    if profile == "common":
        return is_common
    # Default: postgraduate-exam words plus common high-frequency words.
    return is_exam or is_common


def read_dictionary(path, profile="exam-common"):
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as source:
            payload = json.load(source)
        rows = payload if isinstance(payload, list) else payload.get("words", [])
    else:
        with open(path, encoding="utf-8-sig", newline="") as source:
            rows = list(csv.DictReader(source))

    entries = []
    for row in rows:
        if not _matches_profile(row, profile):
            continue
        word = _first(row, "word", "headword", "lemma").lower()
        meaning = _first(row, "chinese_meaning", "translation", "meaning", "definition", "trans")
        if (
            not word
            or not meaning
            or len(word) > 100
            or not re.fullmatch(r"[a-z][a-z'-]{0,48}", word)
        ):
            continue
        entries.append({
            "word": word,
            "part_of_speech": _first(row, "part_of_speech", "pos", "type"),
            "chinese_meaning": meaning[:500],
            "sentence_example": _first(row, "sentence_example", "example", "example_sentence")[:1000],
            "difficulty_level": _first(row, "difficulty_level", "level") or "本地词典",
        })
    return entries


def _bulk_upsert_word_definitions(db, entries):
    """Write one batch with executemany instead of one network request per word."""
    from db import DB_TYPE

    now = datetime.now() if DB_TYPE == "mysql" else datetime.now().isoformat()
    rows = [
        (
            entry["word"],
            entry.get("part_of_speech", ""),
            entry["chinese_meaning"],
            entry.get("sentence_example", ""),
            entry.get("difficulty_level", ""),
            now,
        )
        for entry in entries
    ]

    if DB_TYPE == "mysql":
        sql = (
            "INSERT INTO word_definitions "
            "(word, part_of_speech, chinese_meaning, sentence_example, difficulty_level, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE part_of_speech = VALUES(part_of_speech), "
            "chinese_meaning = VALUES(chinese_meaning), sentence_example = VALUES(sentence_example), "
            "difficulty_level = VALUES(difficulty_level), updated_at = VALUES(updated_at)"
        )
        with db.cursor() as cur:
            cur.executemany(sql, rows)
    else:
        db.executemany(
            "INSERT INTO word_definitions "
            "(word, part_of_speech, chinese_meaning, sentence_example, difficulty_level, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(word) DO UPDATE SET part_of_speech = excluded.part_of_speech, "
            "chinese_meaning = excluded.chinese_meaning, sentence_example = excluded.sentence_example, "
            "difficulty_level = excluded.difficulty_level, updated_at = excluded.updated_at",
            rows,
        )


def import_dictionary(path, profile="exam-common"):
    from app import app
    from db import get_connection

    entries = read_dictionary(path, profile=profile)
    if not entries:
        raise ValueError("no usable dictionary entries found")

    with app.app_context():
        db = get_connection()
        try:
            batch_size = 500
            total = len(entries)
            print(f"Dictionary parsed: {total:,} entries; importing in batches...", flush=True)
            for start in range(0, total, batch_size):
                batch = entries[start:start + batch_size]
                _bulk_upsert_word_definitions(db, batch)
                db.commit()
                imported = min(start + batch_size, total)
                print(f"Imported {imported:,}/{total:,} entries...", flush=True)
        finally:
            db.close()
    print(f"Imported {len(entries):,} dictionary entries (profile: {profile})")


def validate_question_bank(path):
    """Validate a licensed JSON/CSV question bank without publishing its contents."""
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as source:
            payload = json.load(source)
        rows = payload if isinstance(payload, list) else payload.get("questions", [])
    else:
        with open(path, encoding="utf-8-sig", newline="") as source:
            rows = list(csv.DictReader(source))

    if not rows:
        raise ValueError("question bank is empty")
    required = {"question_text", "option_a", "option_b", "option_c", "option_d"}
    valid = sum(1 for row in rows if required.issubset(row.keys()))
    print(f"Question bank checked: {valid:,}/{len(rows):,} records contain the required fields")
    if valid == 0:
        raise ValueError("question bank must contain question_text and option_a..option_d")


def main():
    parser = argparse.ArgumentParser(description="Manage offline dictionary and licensed question-bank files")
    sub = parser.add_subparsers(dest="command", required=True)

    download = sub.add_parser("download", help="download a resource")
    download.add_argument("--url", required=True)
    download.add_argument("--output", required=True)

    import_cmd = sub.add_parser("import-dictionary", help="import JSON/CSV dictionary into SQLite/MySQL")
    import_cmd.add_argument("--path", required=True)
    import_cmd.add_argument(
        "--profile",
        choices=("exam-common", "exam", "common", "all"),
        default="exam-common",
        help="exam-common=考研+高频常见词（默认），exam=仅考研，common=仅常见词，all=全部",
    )

    question = sub.add_parser("download-question-bank", help="download and validate an authorized question bank")
    question.add_argument("--url", required=True)
    question.add_argument("--output", required=True)

    args = parser.parse_args()
    if args.command == "download":
        download_file(args.url, args.output)
    elif args.command == "import-dictionary":
        import_dictionary(args.path, profile=args.profile)
    elif args.command == "download-question-bank":
        output = download_file(args.url, args.output)
        validate_question_bank(output)
        print("Use only question-bank content you are licensed to store and use.")


if __name__ == "__main__":
    main()
