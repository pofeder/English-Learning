import os
import json
import sqlite3
import logging
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("english_daily")

DB_TYPE = os.getenv("DB_TYPE", "sqlite").lower()
_pool = None
_sqlite_path = None


# ═══ SQLite backend ═══════════════════════════════════════

def _get_sqlite_path():
    global _sqlite_path
    if _sqlite_path is None:
        env_path = os.getenv("DB_SQLITE_PATH", "")
        if env_path:
            os.makedirs(os.path.dirname(env_path), exist_ok=True)
            _sqlite_path = env_path
        else:
            base = os.path.dirname(os.path.abspath(__file__))
            _sqlite_path = os.path.join(base, "data", "english.db")
    return _sqlite_path


def _init_sqlite():
    db_path = _get_sqlite_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            chinese_title TEXT,
            chinese_content TEXT NOT NULL,
            source TEXT,
            word_count INTEGER,
            created_at TEXT NOT NULL,
            is_active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS glossary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL,
            word TEXT NOT NULL,
            part_of_speech TEXT,
            chinese_meaning TEXT NOT NULL,
            sentence_example TEXT,
            difficulty_level TEXT,
            FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS word_definitions (
            word TEXT PRIMARY KEY,
            part_of_speech TEXT,
            chinese_meaning TEXT NOT NULL,
            sentence_example TEXT,
            difficulty_level TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS word_lookups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT UNIQUE NOT NULL,
            looked_up_at TEXT NOT NULL,
            article_id INTEGER,
            lookup_count INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS translation_exercises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL,
            sentence_index INTEGER NOT NULL,
            english_sentence TEXT NOT NULL,
            reference_translation TEXT NOT NULL,
            user_translation TEXT,
            feedback TEXT,
            score INTEGER,
            submitted_at TEXT,
            FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS reading_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL,
            question_type TEXT NOT NULL,
            question_text TEXT NOT NULL,
            option_a TEXT NOT NULL,
            option_b TEXT NOT NULL,
            option_c TEXT NOT NULL,
            option_d TEXT NOT NULL,
            correct_answer TEXT NOT NULL,
            explanation_cn TEXT NOT NULL,
            FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS reading_answer_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            user_answer TEXT,
            is_correct INTEGER,
            answered_at TEXT NOT NULL,
            FOREIGN KEY (question_id) REFERENCES reading_questions(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS cloze_exercises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL,
            passage_text TEXT NOT NULL,
            blanks_json TEXT NOT NULL,
            FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS cloze_answer_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cloze_id INTEGER NOT NULL,
            user_answers_json TEXT NOT NULL,
            score INTEGER,
            submitted_at TEXT NOT NULL,
            FOREIGN KEY (cloze_id) REFERENCES cloze_exercises(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS writing_exercises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER,
            writing_type TEXT NOT NULL,
            prompt_cn TEXT NOT NULL,
            prompt_en TEXT,
            requirements TEXT,
            reference_essay TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS writing_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exercise_id INTEGER NOT NULL,
            user_essay TEXT NOT NULL,
            score INTEGER,
            feedback TEXT,
            submitted_at TEXT NOT NULL,
            FOREIGN KEY (exercise_id) REFERENCES writing_exercises(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS spaced_repetition (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL UNIQUE,
            ease_factor REAL DEFAULT 2.5,
            interval_days INTEGER DEFAULT 0,
            repetitions INTEGER DEFAULT 0,
            next_review_at TEXT NOT NULL,
            last_review_at TEXT
        );
        CREATE TABLE IF NOT EXISTS daily_checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            checkin_date TEXT NOT NULL UNIQUE,
            article_id INTEGER,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mistake_notebook (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mistake_type TEXT NOT NULL,
            ref_id INTEGER,
            question_text TEXT,
            user_wrong_answer TEXT,
            correct_answer TEXT,
            explanation TEXT,
            reviewed INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );
    """)
    conn.commit()

    # Migrations: add columns that may be missing from older schema
    migrations = [
        "ALTER TABLE articles ADD COLUMN difficulty_level TEXT",
        "ALTER TABLE articles ADD COLUMN difficulty_score REAL",
        "ALTER TABLE articles ADD COLUMN cefr_level TEXT",
        "ALTER TABLE word_lookups ADD COLUMN status TEXT DEFAULT 'unfamiliar'",
    ]
    for m in migrations:
        try:
            conn.execute(m)
        except sqlite3.OperationalError:
            pass
    conn.execute(
        "INSERT OR IGNORE INTO word_definitions "
        "(word, part_of_speech, chinese_meaning, sentence_example, difficulty_level, updated_at) "
        "SELECT LOWER(word), part_of_speech, chinese_meaning, sentence_example, "
        "difficulty_level, datetime('now') FROM glossary"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_glossary_word ON glossary(word)")
    conn.commit()

    # Create indexes (safe after migrations)
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_sqlite_active ON articles(is_active, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_sqlite_gloss ON glossary(article_id)",
        "CREATE INDEX IF NOT EXISTS idx_sqlite_status ON word_lookups(status)",
        "CREATE INDEX IF NOT EXISTS idx_sqlite_count ON word_lookups(lookup_count)",
        "CREATE INDEX IF NOT EXISTS idx_sqlite_ex ON translation_exercises(article_id)",
        "CREATE INDEX IF NOT EXISTS idx_sqlite_rq ON reading_questions(article_id)",
        "CREATE INDEX IF NOT EXISTS idx_sqlite_rq_type ON reading_questions(question_type)",
        "CREATE INDEX IF NOT EXISTS idx_sqlite_rar ON reading_answer_records(question_id)",
        "CREATE INDEX IF NOT EXISTS idx_sqlite_cloze ON cloze_exercises(article_id)",
        "CREATE INDEX IF NOT EXISTS idx_sqlite_sr ON spaced_repetition(next_review_at)",
        "CREATE INDEX IF NOT EXISTS idx_sqlite_chk ON daily_checkins(checkin_date)",
        "CREATE INDEX IF NOT EXISTS idx_sqlite_mn ON mistake_notebook(mistake_type)",
        "CREATE INDEX IF NOT EXISTS idx_sqlite_mn_rev ON mistake_notebook(reviewed)",
    ]
    for i in indexes:
        try:
            conn.execute(i)
        except sqlite3.OperationalError:
            pass
    conn.commit()

    conn.close()
    logger.info(f"SQLite database initialized at {db_path}")


def _get_sqlite_connection():
    conn = sqlite3.connect(_get_sqlite_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ═══ MySQL backend ════════════════════════════════════════

def _get_mysql_config():
    return {
        "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER", "root"),
        "password": os.getenv("MYSQL_PASSWORD", ""),
        "database": os.getenv("MYSQL_DATABASE", "english_daily"),
        "charset": "utf8mb4",
        "cursorclass": None,  # filled later after import
        "autocommit": False,
    }


def _init_mysql():
    global _pool
    import pymysql
    from dbutils.pooled_db import PooledDB

    cfg = _get_mysql_config()
    cfg["cursorclass"] = pymysql.cursors.DictCursor
    db_name = cfg.pop("database")

    # Create database if not exists
    conn = pymysql.connect(**cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()
    finally:
        conn.close()

    cfg["database"] = db_name
    conn = pymysql.connect(**cfg)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS articles (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    title VARCHAR(500) NOT NULL,
                    content TEXT NOT NULL,
                    chinese_title VARCHAR(500),
                    chinese_content TEXT NOT NULL,
                    source VARCHAR(300),
                    word_count INT,
                    difficulty_level VARCHAR(50),
                    difficulty_score DECIMAL(3,1),
                    cefr_level VARCHAR(10),
                    created_at DATETIME NOT NULL,
                    is_active TINYINT DEFAULT 1,
                    INDEX idx_active_date (is_active, created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS glossary (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    article_id INT NOT NULL,
                    word VARCHAR(100) NOT NULL,
                    part_of_speech VARCHAR(30),
                    chinese_meaning VARCHAR(500) NOT NULL,
                    sentence_example TEXT,
                    difficulty_level VARCHAR(50),
                    INDEX idx_glossary_article (article_id),
                    INDEX idx_glossary_word (word),
                    FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS word_definitions (
                    word VARCHAR(100) PRIMARY KEY,
                    part_of_speech VARCHAR(30),
                    chinese_meaning VARCHAR(500) NOT NULL,
                    sentence_example TEXT,
                    difficulty_level VARCHAR(50),
                    updated_at DATETIME NOT NULL,
                    INDEX idx_word_definition_updated (updated_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS word_lookups (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    word VARCHAR(100) NOT NULL,
                    looked_up_at DATETIME NOT NULL,
                    article_id INT,
                    lookup_count INT DEFAULT 1,
                    status VARCHAR(20) DEFAULT 'unfamiliar',
                    UNIQUE KEY uk_word (word),
                    INDEX idx_status (status),
                    INDEX idx_count (lookup_count)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS translation_exercises (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    article_id INT NOT NULL,
                    sentence_index INT NOT NULL,
                    english_sentence TEXT NOT NULL,
                    reference_translation TEXT NOT NULL,
                    user_translation TEXT,
                    feedback TEXT,
                    score INT,
                    submitted_at DATETIME,
                    INDEX idx_exercises_article (article_id),
                    FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS reading_questions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    article_id INT NOT NULL,
                    question_type VARCHAR(30) NOT NULL,
                    question_text TEXT NOT NULL,
                    option_a TEXT NOT NULL,
                    option_b TEXT NOT NULL,
                    option_c TEXT NOT NULL,
                    option_d TEXT NOT NULL,
                    correct_answer CHAR(1) NOT NULL,
                    explanation_cn TEXT NOT NULL,
                    INDEX idx_rq_article (article_id),
                    FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS reading_answer_records (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    question_id INT NOT NULL,
                    user_answer CHAR(1),
                    is_correct TINYINT,
                    answered_at DATETIME NOT NULL,
                    FOREIGN KEY (question_id) REFERENCES reading_questions(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cloze_exercises (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    article_id INT NOT NULL,
                    passage_text TEXT NOT NULL,
                    blanks_json TEXT NOT NULL,
                    INDEX idx_cloze_article (article_id),
                    FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cloze_answer_records (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    cloze_id INT NOT NULL,
                    user_answers_json TEXT NOT NULL,
                    score INT,
                    submitted_at DATETIME NOT NULL,
                    FOREIGN KEY (cloze_id) REFERENCES cloze_exercises(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS writing_exercises (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    article_id INT,
                    writing_type VARCHAR(30) NOT NULL,
                    prompt_cn TEXT NOT NULL,
                    prompt_en TEXT,
                    requirements TEXT,
                    reference_essay TEXT,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE SET NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS writing_submissions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    exercise_id INT NOT NULL,
                    user_essay TEXT NOT NULL,
                    score INT,
                    feedback TEXT,
                    submitted_at DATETIME NOT NULL,
                    FOREIGN KEY (exercise_id) REFERENCES writing_exercises(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS spaced_repetition (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    word VARCHAR(100) NOT NULL UNIQUE,
                    ease_factor DECIMAL(3,1) DEFAULT 2.5,
                    interval_days INT DEFAULT 0,
                    repetitions INT DEFAULT 0,
                    next_review_at DATETIME NOT NULL,
                    last_review_at DATETIME
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS daily_checkins (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    checkin_date DATE NOT NULL UNIQUE,
                    article_id INT,
                    created_at DATETIME NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mistake_notebook (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    mistake_type VARCHAR(30) NOT NULL,
                    ref_id INT,
                    question_text TEXT,
                    user_wrong_answer TEXT,
                    correct_answer TEXT,
                    explanation TEXT,
                    reviewed TINYINT DEFAULT 0,
                    created_at DATETIME NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("""
                INSERT IGNORE INTO word_definitions
                    (word, part_of_speech, chinese_meaning, sentence_example, difficulty_level, updated_at)
                SELECT LOWER(word), part_of_speech, chinese_meaning, sentence_example,
                       difficulty_level, NOW()
                FROM glossary
            """)
            try:
                cur.execute("CREATE INDEX idx_glossary_word ON glossary(word)")
            except Exception:
                pass
            mysql_indexes = [
                "CREATE INDEX idx_articles_created_at ON articles(created_at)",
                "CREATE INDEX idx_reading_answer_q_time ON reading_answer_records(question_id, answered_at)",
                "CREATE INDEX idx_cloze_answer_id_time ON cloze_answer_records(cloze_id, submitted_at)",
                "CREATE INDEX idx_writing_submission_ex_time ON writing_submissions(exercise_id, submitted_at)",
                "CREATE INDEX idx_word_lookup_status_count ON word_lookups(status, lookup_count)",
                "CREATE INDEX idx_spaced_review_due ON spaced_repetition(next_review_at)",
            ]
            for statement in mysql_indexes:
                try:
                    cur.execute(statement)
                except Exception:
                    # Existing indexes are harmless; keep startup safe.
                    pass
        conn.commit()
        logger.info("MySQL database initialized successfully")
    finally:
        conn.close()

    _pool = PooledDB(
        creator=pymysql,
        maxconnections=5,
        mincached=1,
        maxcached=3,
        blocking=True,
        **cfg,
    )
    logger.info("MySQL connection pool created (max 5 connections)")
    return _pool


# ═══ Public API ═══════════════════════════════════════════

def init_db():
    if DB_TYPE == "mysql":
        result = _init_mysql()
    else:
        _init_sqlite()
        result = None
    seed_local_dictionary()
    return result


def get_connection():
    if DB_TYPE == "mysql":
        global _pool
        if _pool is None:
            _pool = _init_mysql()
        return _pool.connection()
    else:
        return _get_sqlite_connection()


def _load_local_dictionary():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "local_dictionary.json")
    try:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
        return entries if isinstance(entries, list) else []
    except (FileNotFoundError, ValueError, TypeError) as exc:
        logger.warning("Local dictionary could not be loaded: %s", exc)
        return []


def seed_local_dictionary():
    """Import the checked-in offline dictionary into the reusable definition table."""
    entries = _load_local_dictionary()
    if not entries:
        return
    db = get_connection()
    try:
        for entry in entries:
            if not entry.get("word") or not entry.get("chinese_meaning"):
                continue
            upsert_word_definition(
                db,
                entry["word"],
                entry.get("part_of_speech", ""),
                entry["chinese_meaning"],
                entry.get("sentence_example", ""),
                entry.get("difficulty_level", "考研高频"),
            )
        db.commit()
    finally:
        db.close()


# ═══ Query helpers (both backends) ════════════════════════

def _db_execute(db, sql, params=()):
    """Execute a write statement. Works for both SQLite and MySQL."""
    if DB_TYPE == "mysql":
        with db.cursor() as cur:
            cur.execute(sql, params)
            return cur.lastrowid
    else:
        sql = sql.replace("%s", "?")
        cur = db.execute(sql, params)
        return cur.lastrowid


def _db_fetch(db, sql, params=()):
    """Execute a read query. Returns list of dicts."""
    if DB_TYPE == "mysql":
        with db.cursor() as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    else:
        sql = sql.replace("%s", "?")
        cur = db.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _db_fetch_one(db, sql, params=()):
    rows = _db_fetch(db, sql, params)
    return rows[0] if rows else None


def record_word_lookup(db, word, article_id=None):
    word = word.lower().strip()
    if DB_TYPE == "mysql":
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO word_lookups (word, looked_up_at, article_id, lookup_count, status) "
                "VALUES (%s, NOW(), %s, 1, 'unfamiliar') "
                "ON DUPLICATE KEY UPDATE "
                "lookup_count = lookup_count + 1, looked_up_at = NOW(), status = 'unfamiliar'",
                (word, article_id),
            )
        db.commit()
    else:
        db.execute(
            "INSERT INTO word_lookups (word, looked_up_at, article_id, lookup_count, status) "
            "VALUES (?, datetime('now'), ?, 1, 'unfamiliar') "
            "ON CONFLICT(word) DO UPDATE SET "
            "lookup_count = lookup_count + 1, looked_up_at = datetime('now'), status = 'unfamiliar'",
            (word, article_id),
        )
        db.commit()


def update_word_status(db, word, status):
    word = word.lower().strip()
    valid = ("unfamiliar", "learning", "mastered")
    if status not in valid:
        raise ValueError(f"Invalid status: {status}, must be one of {valid}")
    if DB_TYPE == "mysql":
        with db.cursor() as cur:
            cur.execute(
                "UPDATE word_lookups SET status = %s WHERE word = %s",
                (status, word),
            )
        db.commit()
    else:
        db.execute(
            "UPDATE word_lookups SET status = ? WHERE word = ?",
            (status, word),
        )
        db.commit()


def delete_word_record(db, word):
    word = word.lower().strip()
    if DB_TYPE == "mysql":
        with db.cursor() as cur:
            cur.execute("DELETE FROM word_lookups WHERE word = %s", (word,))
        db.commit()
    else:
        db.execute("DELETE FROM word_lookups WHERE word = ?", (word,))
        db.commit()


def upsert_word_definition(db, word, part_of_speech, chinese_meaning, sentence_example, difficulty_level):
    """Store one reusable local definition for click-to-lookup."""
    word = word.lower().strip()
    now_str = datetime.now() if DB_TYPE == "mysql" else datetime.now().isoformat()
    if DB_TYPE == "mysql":
        _db_execute(
            db,
            "INSERT INTO word_definitions "
            "(word, part_of_speech, chinese_meaning, sentence_example, difficulty_level, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE part_of_speech = VALUES(part_of_speech), "
            "chinese_meaning = VALUES(chinese_meaning), sentence_example = VALUES(sentence_example), "
            "difficulty_level = VALUES(difficulty_level), updated_at = VALUES(updated_at)",
            (word, part_of_speech or "", chinese_meaning, sentence_example or "", difficulty_level or "", now_str),
        )
    else:
        _db_execute(
            db,
            "INSERT INTO word_definitions "
            "(word, part_of_speech, chinese_meaning, sentence_example, difficulty_level, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT(word) DO UPDATE SET part_of_speech = excluded.part_of_speech, "
            "chinese_meaning = excluded.chinese_meaning, sentence_example = excluded.sentence_example, "
            "difficulty_level = excluded.difficulty_level, updated_at = excluded.updated_at",
            (word, part_of_speech or "", chinese_meaning, sentence_example or "", difficulty_level or "", now_str),
        )


def get_priority_words(db, limit=15):
    if DB_TYPE == "mysql":
        with db.cursor() as cur:
            cur.execute(
                "SELECT word, lookup_count, looked_up_at FROM word_lookups "
                "WHERE status IN ('unfamiliar', 'learning') "
                "ORDER BY lookup_count DESC LIMIT 50"
            )
            rows = cur.fetchall()
    else:
        rows = db.execute(
            "SELECT word, lookup_count, looked_up_at FROM word_lookups "
            "WHERE status IN ('unfamiliar', 'learning') "
            "ORDER BY lookup_count DESC LIMIT 50"
        ).fetchall()
        rows = [dict(r) for r in rows]

    now = datetime.now()
    scored = []
    for r in rows:
        try:
            last_seen = r["looked_up_at"]
            if isinstance(last_seen, str):
                last_seen = datetime.fromisoformat(last_seen)
            days_ago = max(0, (now - last_seen).days)
        except (ValueError, TypeError):
            days_ago = 30
        score = r["lookup_count"] * (0.9 ** days_ago)
        scored.append((r["word"], score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [w for w, _ in scored[:limit]]
