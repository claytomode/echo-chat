"""Convert sms.db messages to a knowledge_base.db SQLite table."""

import os
import sqlite3
import uuid
from datetime import datetime, timedelta


def assign_conversation_ids(messages: list, time_gap_threshold_minutes: int = 30) -> list:
    """Assign pseudo conversation IDs based on time gaps between messages.

    Messages MUST be sorted by 'timestamp_raw' ascending before calling this.
    """
    if not messages:
        return []

    processed_messages = []
    current_conversation_id = 0

    for i, msg in enumerate(messages):
        if i == 0:
            msg['conversation_id'] = f'conv_{current_conversation_id}'
            processed_messages.append(msg)
            continue

        prev_msg = processed_messages[i - 1]

        # Use 'timestamp_seconds' for the time difference calculation.
        # This 'timestamp_seconds' should now be the converted (seconds-since-epoch) value.
        time_diff_seconds = msg['timestamp_seconds'] - prev_msg['timestamp_seconds']
        time_diff_minutes = time_diff_seconds / 60

        if time_diff_minutes > time_gap_threshold_minutes:
            current_conversation_id += 1

        msg['conversation_id'] = f'conv_{current_conversation_id}'
        processed_messages.append(msg)

    return processed_messages


def sms_db_to_knowledge_base(
    sms_db_path: str,
    target_phone_number: str,
    knowledge_base_db_path: str = 'knowledge_base.db',
    conversation_gap_minutes: int = 30,
    *,
    recreate_db: bool = True,
) -> None:
    """
    Extracts messages from sms.db, assigns conversation IDs, and stores them
    in a 'messages' table within knowledge_base.db.
    """
    if recreate_db and os.path.exists(knowledge_base_db_path):
        os.remove(knowledge_base_db_path)
        print(f"Removed existing '{knowledge_base_db_path}' to recreate.")

    # Connect to the new knowledge_base.db
    knowledge_conn = sqlite3.connect(knowledge_base_db_path)
    knowledge_cursor = knowledge_conn.cursor()
    print(f'Connected to knowledge base database: {knowledge_base_db_path}')

    # Create the messages table if it doesn't exist
    knowledge_cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            text TEXT NOT NULL,
            is_from_me INTEGER NOT NULL, -- 0 for False, 1 for True
            date_iso TEXT NOT NULL,       -- ISO formatted datetime string
            timestamp_seconds REAL NOT NULL -- Converted timestamp in seconds (since CoreData epoch)
        )
    """)
    knowledge_conn.commit()
    print("Ensured 'messages' table exists in knowledge base.")

    # Connect to sms.db to read messages
    sms_conn = sqlite3.connect(sms_db_path)
    sms_cursor = sms_conn.cursor()
    print('Connected to sms database.')

    query = """
            SELECT
                message.ROWID,
                message.text,
                message.is_from_me,
                message.date
            FROM
                message
            INNER JOIN
                handle ON message.handle_id = handle.ROWID
            WHERE
                REPLACE(REPLACE(REPLACE(handle.id, '+', ''), '-', ''), ' ', '') LIKE ?
            ORDER BY
                message.date ASC;
            """
    normalized_phone_number = target_phone_number.replace('+', '').replace('-', '').replace(' ', '')
    sms_cursor.execute(query, (f'%{normalized_phone_number}%',))
    raw_messages = sms_cursor.fetchall()
    print(f'Fetched {len(raw_messages)} raw messages from sms.db.')

    if not raw_messages:
        sms_conn.close()
        knowledge_conn.close()
        msg = f'No messages found for {target_phone_number} in {sms_db_path}'
        raise ValueError(msg)

    coredata_epoch = datetime(2001, 1, 1, tzinfo=None)

    # First pass: Prepare messages with normalized timestamps for conversation ID assignment
    prepped_messages = []
    for row_id, text, is_from_me, date_coredata in raw_messages:
        # Correctly convert CoreData timestamp from nanoseconds to seconds
        # The `date_coredata` is in nanoseconds since 2001-01-01 00:00:00 UTC
        timestamp_in_seconds = date_coredata / 1_000_000_000.0
        message_datetime = coredata_epoch + timedelta(seconds=timestamp_in_seconds)

        prepped_messages.append(
            {
                'original_id': row_id,  # Keep original ROWID if needed later
                'text': str(text) if text is not None else '',
                'is_from_me': bool(is_from_me),
                'date': message_datetime.isoformat(),  # ISO format for readability
                'timestamp_seconds': timestamp_in_seconds,  # Store converted seconds
            }
        )

    # Assign conversation IDs using the helper function
    # It requires messages to be sorted by timestamp, which they are from the SQL query
    processed_messages_with_conv_ids = assign_conversation_ids(
        prepped_messages, conversation_gap_minutes
    )
    print(
        f'Processed {len(processed_messages_with_conv_ids)} messages and assigned conversation IDs.'
    )

    # Insert into knowledge_base.db
    batch_insert_data = []
    for msg in processed_messages_with_conv_ids:
        batch_insert_data.append(
            (
                str(uuid.uuid4()),
                msg['conversation_id'],
                msg['text'],
                int(msg['is_from_me']),
                msg['date'],
                msg['timestamp_seconds'],
            )
        )

    # Perform a batch insert for efficiency
    knowledge_cursor.executemany(
        """
        INSERT INTO messages (id, conversation_id, text, is_from_me, date_iso, timestamp_seconds)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        batch_insert_data,
    )
    knowledge_conn.commit()
    print(f"Inserted {len(batch_insert_data)} messages into '{knowledge_base_db_path}'.")

    sms_conn.close()
    knowledge_conn.close()
    print('SMS and knowledge base database connections closed.')


if __name__ == '__main__':
    SMS_DB_PATH = ''
    TARGET_PHONE = ''

    try:
        sms_db_to_knowledge_base(
            sms_db_path=SMS_DB_PATH,
            target_phone_number=TARGET_PHONE,
            knowledge_base_db_path='knowledge_base.db',
            conversation_gap_minutes=30,
            recreate_db=True,
        )
        print('\nMessage extraction and knowledge base creation complete.')

        print('\n--- Verifying knowledge_base.db contents ---')
        conn = sqlite3.connect('knowledge_base.db')
        cursor = conn.cursor()
        cursor.execute(
            'SELECT conversation_id, text, is_from_me, date_iso, timestamp_seconds FROM messages ORDER BY timestamp_seconds'
        )
        kb_messages = cursor.fetchall()
        for msg in kb_messages:
            print(
                f"Conv ID: {msg[0]}, Text: '{msg[1]}', From Me: {bool(msg[2])}, Date: {msg[3]}, Time (sec): {msg[4]:.2f}"
            )
        conn.close()

    except ValueError as e:
        print(f'Configuration Error: {e}')
    except Exception as e:
        print(f'An unexpected error occurred: {e}')
