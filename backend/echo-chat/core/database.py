"""SQLite database creation and management."""

import sqlite3

from models import ExtractedFacts, Message

DB_NAME = 'knowledge_base.db'
FACTS_TABLE_NAME = 'facts'
MESSAGES_TABLE_NAME = 'messages'
connection = sqlite3.connect(DB_NAME)


def create_db(conn: sqlite3.Connection) -> None:
    """Create the necessary tables in the SQLite database if they don't already exist."""
    cursor = conn.cursor()
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {MESSAGES_TABLE_NAME} (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            text TEXT NOT NULL,
            is_from_me INTEGER NOT NULL, -- 0 for False, 1 for True
            date_iso TEXT NOT NULL,       -- ISO formatted datetime string
            timestamp_seconds REAL NOT NULL -- Converted timestamp in seconds (since CoreData epoch)
        )
    """)
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {FACTS_TABLE_NAME} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            subject TEXT NOT NULL,
            predicate TEXT NOT NULL,
            object TEXT NOT NULL,
            confidence REAL NOT NULL,
            source_text TEXT NOT NULL,
            date TEXT NOT NULL
        );
    """)
    conn.commit()


def insert_message(
    conn: sqlite3.Connection,
    *,
    message: Message,
) -> None:
    """Insert a single message into the messages table."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        (
            f'INSERT INTO {MESSAGES_TABLE_NAME}'
            '(conversation_id, text, is_from_me, date_iso, timestamp_seconds)'
            'VALUES (?, ?, ?, ?, ?)'
        ),
        (
            message.conversation_id,
            message.text,
            message.is_from_me,
            message.date_iso,
            message.timestamp_seconds,
        ),
    )
    conn.commit()


def insert_facts(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    facts: ExtractedFacts,
) -> None:
    """Insert extracted facts into the facts table."""
    cursor = conn.cursor()
    for fact in facts.facts:
        cursor.execute(
            (
                f'INSERT INTO {FACTS_TABLE_NAME}'
                '(conversation_id, subject, predicate, object, confidence, source_text, date)'
                'VALUES (?, ?, ?, ?, ?, ?, ?)'
            ),
            (
                conversation_id,
                fact.subject,
                fact.predicate,
                fact.object,
                fact.confidence,
                fact.source_text,
                fact.fact_date,
            ),
        )
    conn.commit()


def get_all_conversation_ids(conn: sqlite3.Connection) -> list[str]:
    """Retrieve all unique conversation IDs from the messages table."""
    cursor = conn.cursor()
    cursor.execute(f'SELECT DISTINCT conversation_id FROM {MESSAGES_TABLE_NAME};')  # noqa: S608 not user input
    rows = cursor.fetchall()
    return [row[0] for row in rows]
