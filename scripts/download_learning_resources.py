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


def read_dictionary(path):
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as source:
            payload = json.load(source)
        rows = payload if isinstance(payload, list) else payload.get("words", [])
    else:
        with open(path, encoding="utf-8-sig", newline="") as source:
            rows = list(csv.DictReader(source))

    entries = []
    for row in rows:
        word = _first(row, "word", "headword", "lemma").lower()
        meaning = _first(row, "chinese_meaning", "translation", "meaning", "definition", "trans")
        if not word or not meaning or len(word) > 100:
            continue
        entries.append({
            "word": word,
            "part_of_speech": _first(row, "part_of_speech", "pos", "type"),
            "chinese_meaning": meaning[:500],
            "sentence_example": _first(row, "sentence_example", "example", "example_sentence")[:1000],
            "difficulty_level": _first(row, "difficulty_level", "level") or "本地词典",
        })
    return entries


def import_dictionary(path):
    from app import app
    from db import get_connection, upsert_word_definition

    entries = read_dictionary(path)
    if not entries:
        raise ValueError("no usable dictionary entries found")

    with app.app_context():
        db = get_connection()
        try:
            for entry in entries:
                upsert_word_definition(db, **entry)
            db.commit()
        finally:
            db.close()
    print(f"Imported {len(entries):,} dictionary entries")


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

    question = sub.add_parser("download-question-bank", help="download and validate an authorized question bank")
    question.add_argument("--url", required=True)
    question.add_argument("--output", required=True)

    args = parser.parse_args()
    if args.command == "download":
        download_file(args.url, args.output)
    elif args.command == "import-dictionary":
        import_dictionary(args.path)
    elif args.command == "download-question-bank":
        output = download_file(args.url, args.output)
        validate_question_bank(output)
        print("Use only question-bank content you are licensed to store and use.")


if __name__ == "__main__":
    main()
