import asyncio
import sqlite3
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from google.adk import Agent, Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

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


async def extract_facts_from_conversation(
    conversation_id: str,
    semaphore: asyncio.Semaphore,  # Accept semaphore as an argument
) -> ExtractedFacts | None:
    """
    Fetches messages for a given conversation ID, formats them for the agent,
    sends them to the fact extractor agent, and saves the extracted facts to the database.
    Uses a semaphore to limit concurrent API calls.
    """
    # Acquire a semaphore slot before proceeding with the API call
    async with semaphore:
        messages = get_knowledge_base_messages(conversation_id=conversation_id)
        if not messages:
            print(f'Skipping fact extraction for convo ID: {conversation_id} (no messages found).')
            return None

        runner = Runner(
            app_name='fact_extraction',
            agent=fact_extractor_agent,
            session_service=session_service,
        )

        formatted_msgs = ''
        for message in messages:
            formatted_msgs += (
                f'Date: {message["date_iso"]}\n'
                f'Sender: {"Me" if message["is_from_me"] else "Other"}\n'
                f'Message:\n{message["text"]}\n-----\n'
            )

        content = types.Content(parts=[types.Part(text=formatted_msgs)], role='user')

        current_session_id = f'session_{conversation_id}'
        try:
            await session_service.create_session(
                app_name='fact_extraction', session_id=current_session_id, user_id=conversation_id
            )
        except Exception:
            pass  # Suppress "session already exists" errors for InMemorySessionService

        # print(f"Attempting to extract facts for conversation ID: {conversation_id}") # Moved logging for less clutter
        try:
            events = runner.run_async(
                user_id=conversation_id, session_id=current_session_id, new_message=content
            )
            event: Event = await anext(events)

            extracted_facts_json = None
            if event and event.content and event.content.parts:
                extracted_facts_json = event.content.parts[-1].text

            if extracted_facts_json:
                try:
                    facts = ExtractedFacts.model_validate_json(extracted_facts_json)
                    # print(f"Extracted {len(facts.facts)} facts from conversation ID: {conversation_id}") # Moved logging for less clutter
                    await save_extracted_facts(conversation_id, facts)
                    return facts
                except ValidationError as e:
                    print(
                        f"Error validating agent's output schema for conversation ID {conversation_id}: {e}"
                    )
                    print(f'Raw agent output: {extracted_facts_json}')
                    return None
                except Exception as e:
                    print(
                        f'An unexpected error occurred after agent output for conversation ID {conversation_id}: {e}'
                    )
                    return None
            else:
                print(
                    f'No valid JSON output for facts from agent for conversation ID: {conversation_id}'
                )
                return None
        except Exception as e:
            print(
                f'An error occurred during agent execution for conversation ID {conversation_id}: {e}'
            )
            return None
        finally:
            try:
                await session_service.delete_session(
                    app_name='fact_extraction',
                    session_id=current_session_id,
                    user_id=conversation_id,
                )
            except Exception:
                pass


async def main():
    await create_facts_table()  # Ensure the facts table exists

    conversation_ids = get_all_conversation_ids()
    if not conversation_ids:
        print(
            "No conversation IDs found in the database. Please ensure your 'messages' table is populated."
        )
        return

    total_conversations = len(conversation_ids)
    print(f'Found {total_conversations} unique conversations to process.')

    MAX_CONCURRENT_API_CALLS_PER_BATCH = 5
    BATCH_SIZE = 50

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_API_CALLS_PER_BATCH)

    processed_count = 0
    for i in range(0, total_conversations, BATCH_SIZE):
        batch_ids = conversation_ids[i : i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = (total_conversations + BATCH_SIZE - 1) // BATCH_SIZE  # Ceiling division

        print(
            f'\n--- Processing Batch {batch_num}/{total_batches} ({len(batch_ids)} conversations) ---'
        )

        batch_tasks = [
            extract_facts_from_conversation(convo_id, semaphore) for convo_id in batch_ids
        ]

        await asyncio.gather(*batch_tasks)

        processed_count += len(batch_ids)
        print(
            f'--- Completed Batch {batch_num}. Total processed: {processed_count}/{total_conversations} ---'
        )
        await asyncio.sleep(5)

    print('\n--- Finished processing all conversations. ---')


if __name__ == '__main__':
    asyncio.run(main())
