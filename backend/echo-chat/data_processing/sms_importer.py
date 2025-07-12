"""sms.db to knowledge base."""

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

# The CoreData epoch starts on January 1, 2001, UTC.
CORE_DATA_EPOCH = datetime(2001, 1, 1, tzinfo=UTC)


def _assign_conversation_ids(messages: list[dict], time_gap_threshold_minutes: int) -> list[dict]:
    """Assign pseudo-conversation IDs based on time gaps between messages.

    This is a helper function and assumes messages are sorted by timestamp.

    Args:
        messages: A list of message dictionaries, sorted by timestamp.
        time_gap_threshold_minutes: The number of minutes of inactivity that
                                    defines a new conversation.

    Returns:
        The list of messages with a 'conversation_id' key added to each.

    """
    if not messages:
        return []

    conversation_id_counter = 0
    # The first message always starts a new conversation.
    messages[0]['conversation_id'] = f'conv_{conversation_id_counter}'

    for i in range(1, len(messages)):
        prev_msg_ts = messages[i - 1]['timestamp_seconds']
        current_msg_ts = messages[i]['timestamp_seconds']

        time_diff_minutes = (current_msg_ts - prev_msg_ts) / 60

        if time_diff_minutes > time_gap_threshold_minutes:
            conversation_id_counter += 1

        messages[i]['conversation_id'] = f'conv_{conversation_id_counter}'

    return messages


def import_sms_to_knowledge_base(
    sms_db_path: str,
    target_phone_number: str,
    knowledge_base_db_path: str = 'knowledge_base.db',
    conversation_gap_minutes: int = 30,
    *,
    recreate_db: bool = True,
) -> None:
    """Extract messages from sms.db and add to knowledge base.

    Args:
        sms_db_path: The file path to the sms.db from an iOS backup.
        target_phone_number: The phone number of the person to import messages for.
        knowledge_base_db_path: The path to the target SQLite database.
        conversation_gap_minutes: The time gap to define a new conversation.
        recreate_db: If True, the existing knowledge base will be deleted.

    """
    kb_path = Path(knowledge_base_db_path)
    if recreate_db and kb_path.exists():
        Path.unlink(kb_path)
        print(f"Removed existing '{kb_path}' to recreate.")

    if not Path(sms_db_path).exists():
        msg = f"Source sms.db not found at '{sms_db_path}'"
        raise FileNotFoundError(msg)

    # 1. Connect to databases and ensure table exists
    knowledge_conn = sqlite3.connect(kb_path)
    knowledge_cursor = knowledge_conn.cursor()
    knowledge_cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            text TEXT NOT NULL,
            is_from_me INTEGER NOT NULL,
            date_iso TEXT NOT NULL,
            timestamp_seconds REAL NOT NULL
        )
    """
    )

    sms_conn = sqlite3.connect(sms_db_path)
    sms_cursor = sms_conn.cursor()

    # 2. Fetch raw messages from sms.db
    query = """
        SELECT message.text, message.is_from_me, message.date
        FROM message
        INNER JOIN handle ON message.handle_id = handle.ROWID
        WHERE REPLACE(REPLACE(REPLACE(handle.id, '+', ''), '-', ''), ' ', '') LIKE ?
        ORDER BY message.date ASC;
    """
    normalized_phone = ''.join(filter(str.isdigit, target_phone_number))
    sms_cursor.execute(query, (f'%{normalized_phone}%',))
    raw_messages = sms_cursor.fetchall()
    sms_conn.close()

    if not raw_messages:
        msg = f'No messages found for {target_phone_number} in {sms_db_path}'
        raise ValueError(msg)
    print(f'Fetched {len(raw_messages)} raw messages from sms.db.')

    # 3. Process messages: convert timestamps and structure data
    prepped_messages = []
    for text, is_from_me, date_coredata in raw_messages:
        # CoreData timestamps are nanoseconds from the epoch. Convert to seconds.
        timestamp_seconds_since_epoch = date_coredata / 1_000_000_000.0
        message_datetime = CORE_DATA_EPOCH + timedelta(seconds=timestamp_seconds_since_epoch)

        prepped_messages.append(
            {
                'text': str(text) if text is not None else '',
                'is_from_me': bool(is_from_me),
                'date_iso': message_datetime.isoformat(),
                'timestamp_seconds': message_datetime.timestamp(),
            }
        )

    # 4. Assign conversation IDs
    processed_messages = _assign_conversation_ids(prepped_messages, conversation_gap_minutes)
    print(f'Assigned conversation IDs to {len(processed_messages)} messages.')

    # 5. Prepare for batch insert
    batch_insert_data = [
        (
            str(uuid.uuid4()),  # Generate a new unique ID
            msg['conversation_id'],
            msg['text'],
            int(msg['is_from_me']),
            msg['date_iso'],
            msg['timestamp_seconds'],
        )
        for msg in processed_messages
    ]

    # 6. Insert into knowledge base and close connection
    knowledge_cursor.executemany(
        """
        INSERT INTO messages (id, conversation_id, text, is_from_me, date_iso, timestamp_seconds)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        batch_insert_data,
    )
    knowledge_conn.commit()
    knowledge_conn.close()
    print(f"Successfully inserted {len(batch_insert_data)} messages into '{kb_path}'.")
