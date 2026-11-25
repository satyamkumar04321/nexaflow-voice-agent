import sqlite3
from contextlib import contextmanager
from .config import settings


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


@contextmanager
def db_session():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with db_session() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT,
                phone TEXT,
                company TEXT,
                role TEXT,
                team_size TEXT,
                language TEXT DEFAULT 'en',
                budget TEXT,
                authority TEXT,
                need TEXT,
                timeline TEXT,
                qualification_score INTEGER DEFAULT 0,
                stage TEXT DEFAULT 'New',
                sentiment_avg REAL DEFAULT 0.0,
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS calls (
                id TEXT PRIMARY KEY,
                lead_id INTEGER,
                language TEXT DEFAULT 'en',
                status TEXT DEFAULT 'active',
                bant_json TEXT DEFAULT '{}',
                qualification_score INTEGER DEFAULT 0,
                qualification_tier TEXT DEFAULT 'Cold',
                sentiment_score REAL DEFAULT 0.0,
                sentiment_label TEXT DEFAULT 'Neutral',
                objections_json TEXT DEFAULT '[]',
                summary TEXT,
                next_action TEXT,
                followup_email TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                call_id TEXT NOT NULL,
                speaker TEXT NOT NULL,
                text TEXT NOT NULL,
                language TEXT DEFAULT 'en',
                intent TEXT,
                sentiment_score REAL DEFAULT 0.0,
                sentiment_label TEXT DEFAULT 'Neutral',
                rag_sources_json TEXT DEFAULT '[]',
                latency_ms INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (call_id) REFERENCES calls(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                call_id TEXT,
                lead_id INTEGER,
                prospect_name TEXT NOT NULL,
                prospect_email TEXT NOT NULL,
                company TEXT DEFAULT '',
                slot_date TEXT NOT NULL,
                slot_time TEXT NOT NULL,
                topic TEXT DEFAULT 'Product Demo & Architecture Walkthrough',
                meeting_link TEXT NOT NULL,
                status TEXT DEFAULT 'confirmed',
                created_at TEXT NOT NULL,
                UNIQUE(slot_date, slot_time),
                FOREIGN KEY (call_id) REFERENCES calls(id) ON DELETE SET NULL,
                FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS crm_activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER NOT NULL,
                call_id TEXT,
                activity_type TEXT NOT NULL,
                detail TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
            );
            """
        )
