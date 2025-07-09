import sqlite3
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from google.adk import Agent, Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, Field

from config import MODEL_NAME

if TYPE_CHECKING:
    from google.adk.events import Event


class SubjectEnum(str, Enum):
    me = 'me'
    other = 'other'
    both = 'both'


class Fact(BaseModel):
    """A fact extracted extracted from a text conversation."""

    subject: Literal['me', 'other', 'relationship'] = Field(
        ...,
        description="Who the fact is about: 'me' (you), 'other' (the other person), or 'relationship'.",
    )
    predicate: str = Field(..., description='A short string describing the relation or attribute.')
    object: str = Field(..., description='The value or description of the fact.')
    confidence: float = Field(
        ..., ge=0, le=1, description='A float between 0 and 1 indicating confidence in the fact.'
    )
    source_text: str = Field(..., description='The exact message text where this fact appears.')
    fact_date: datetime = Field(..., description="The estimated date of the fact's origin.")


class ExtractedFacts(BaseModel):
    """List of extracted facts from a text conversation."""

    facts: list[Fact] = Field(
        ..., description='A list of factual statements extracted from text messages.'
    )


def get_knowledge_base_messages(
    db_path: str = 'knowledge_base.db', conversation_id: str | None = None
) -> list[dict[str, Any]]:
    """Connect to the knowledge_base.db, queries the 'messages' table.

    Return the results as a list of
    dictionaries.

    Args:
        db_path: Path to the knowledge_base.db file.
        conversation_id: Optional filter to retrieve messages for a specific conversation.

    Returns:
        A list of dictionaries, where each dictionary represents a message row.

    """
    if not Path.exists(Path(db_path)):
        print(f"Error: Knowledge base database file not found at '{db_path}'")
        return []

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = (
            'SELECT id, conversation_id, text, is_from_me, date_iso, timestamp_seconds '
            'FROM messages'
        )
        params = []

        if conversation_id:
            query += ' WHERE conversation_id = ?'
            params.append(conversation_id)

        query += ' ORDER BY timestamp_seconds ASC;'  # Ensure chronological order

        print(f'Executing query: {query} with params: {params}')
        cursor.execute(query, params)
        rows = cursor.fetchall()

        result_list = []
        for row in rows:
            # Convert sqlite3.Row object to a standard dictionary
            row_dict = dict(row)
            # Convert is_from_me back to a boolean for easier use
            row_dict['is_from_me'] = bool(row_dict['is_from_me'])
            result_list.append(row_dict)

    except sqlite3.Error as e:
        print(f'SQLite error when reading knowledge base: {e}')
        return []
    else:
        return result_list
    finally:
        if conn:
            conn.close()


fact_extractor_agent = Agent(
    name='fact_extractor',
    model=MODEL_NAME,
    description='Extracts facts from text conversations',
    instruction=(
        'You are an expert in analyzing text conversations to extract factual information.'
        " You pull information relevant to the sender and reciever's interests, hobbies, "
        'likes, dislikes, life events, etc. as well as specific details surrounding their '
        'relationship.'
        '\n\n'
        'These facts must be overarching truths and not specific to the given conversation. '
        'For example, if a fact is true, it should stay true and not change in a future '
        'conversation. If a fact may change at ALL during the lifetime and relationship '
        'of these individuals, the confidence level must drop.\n'
        '**NOTE**: Text conversations are complex. Sarcasm, inside jokes, and out of context '
        'information will be present.'
    ),
    output_schema=ExtractedFacts,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)

session_service = InMemorySessionService()


async def extract_facts_from_conversation(conversation_id: str) -> ExtractedFacts | None:
    messages = get_knowledge_base_messages(conversation_id=conversation_id)
    if not messages:
        return
    formatted_msgs = ''
    for message in messages:
        formatted_msgs += (
            f'Date: {message["date_iso"]}\n'
            f'Sender: {"Me" if message["is_from_me"] else "Other"}\n'
            f'Message:\n{message["text"]}\n-----\n'
        )
    runner = Runner(
        app_name='fact_extraction',
        agent=fact_extractor_agent,
        session_service=session_service,
    )
    content = types.Content(parts=[types.Part(text=formatted_msgs)], role='user')
    await session_service.create_session(
        app_name='fact_extraction', session_id=conversation_id, user_id=conversation_id
    )
    events = runner.run_async(
        user_id=conversation_id, session_id=conversation_id, new_message=content
    )
    event: Event = await anext(events)
    extracted_facts_json = (
        event.content.parts[-1].text if event.content and event.content.parts else None
    )
    await session_service.delete_session(
        app_name='fact_extraction', session_id=conversation_id, user_id=conversation_id
    )
    if extracted_facts_json:
        facts = ExtractedFacts.model_validate_json(extracted_facts_json)
        print(f'Extracted {len(facts.facts)} facts from conversation ID: {conversation_id}')
        await save_extracted_facts(conversation_id, facts)


async def create_facts_table(db_path: str = 'knowledge_base.db'):
    """Create the 'facts' table in the knowledge_base.db database.

    The 'facts' table stores extracted facts from conversations, with columns
    for conversation ID, subject, predicate, object, confidence, and source text.
    """
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create the 'facts' table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object TEXT NOT NULL,
                confidence REAL NOT NULL,
                source_text TEXT NOT NULL,
                date TEXT NOT NULL
            );
            """
        )
        conn.commit()
        print(f"Successfully created or ensured 'facts' table in '{db_path}'")
    except sqlite3.Error as e:
        print(f'SQLite error when creating facts table: {e}')
    finally:
        if conn:
            conn.close()


async def save_extracted_facts(
    conversation_id: str,
    extracted_facts: ExtractedFacts,
    db_path: str = 'knowledge_base.db',
):
    """Save extracted facts into the 'facts' table.

    Args:
        conversation_id: The ID of the conversation from which facts were extracted.
        extracted_facts: An ExtractedFacts object containing the facts to save.
        db_path: Path to the knowledge_base.db file.
    """
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        for fact in extracted_facts.facts:
            cursor.execute(
                """
                INSERT INTO facts (conversation_id, subject, predicate, object, confidence, source_text, date)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    conversation_id,
                    fact.subject,
                    fact.predicate,
                    fact.object,
                    fact.confidence,
                    fact.source_text,
                    fact.fact_date.isoformat(),
                ),
            )
        conn.commit()
        print(
            f"Successfully saved {len(extracted_facts.facts)} facts for conversation '{conversation_id}'"
        )
    except sqlite3.Error as e:
        print(f'SQLite error when saving extracted facts: {e}')
    finally:
        if conn:
            conn.close()


def get_all_conversation_ids(db_path: str = 'knowledge_base.db') -> list[str]:
    """Retrieve all unique conversation IDs from the 'messages' table."""
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT conversation_id FROM messages;')
        rows = cursor.fetchall()
        return [row[0] for row in rows]
    except sqlite3.Error as e:
        print(f'SQLite error when retrieving conversation IDs: {e}')
        return []
    finally:
        if conn:
            conn.close()


async def main():
    await create_facts_table()  # Ensure the facts table exists
    conversation_ids = get_all_conversation_ids()
    if not conversation_ids:
        print('No conversation IDs found in the database.')
        return

    for convo_id in conversation_ids:
        print(f'\nProcessing conversation: {convo_id}')
        await extract_facts_from_conversation(conversation_id=convo_id)
    print('\nFinished processing all conversations.')


if __name__ == '__main__':
    import asyncio

    asyncio.run(main())
