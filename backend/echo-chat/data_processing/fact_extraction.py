"""Extract facts from texts and add to db."""

import asyncio
import sqlite3
from typing import Any

from google.adk import Agent, Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import ValidationError

from config.settings import MODEL_NAME
from core.database import (
    DB_NAME,
    create_db,
    get_all_conversation_ids,
    insert_facts,
)
from core.models import ExtractedFacts

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
)


def _get_messages_for_conversation(
    conn: sqlite3.Connection, conversation_id: str
) -> list[dict[str, Any]]:
    """Fetch all messages for a specific conversation ID."""
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        (
            'SELECT text, is_from_me, date_iso FROM messages '
            'WHERE conversation_id = ? ORDER BY timestamp_seconds ASC'
        ),
        (conversation_id,),
    )
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


async def _extract_and_save_facts(
    conn: sqlite3.Connection, conversation_id: str, semaphore: asyncio.Semaphore
) -> None:
    """Use an AI agent to extract facts from a single conversation and save them.

    A semaphore is used to limit concurrent API calls.
    """
    async with semaphore:
        messages = _get_messages_for_conversation(conn, conversation_id)
        if not messages:
            return

        session_service = InMemorySessionService()
        runner = Runner(
            app_name='fact_extraction', agent=fact_extractor_agent, session_service=session_service
        )
        # Format the conversation for the agent
        formatted_msgs = ''.join(
            f'Sender: {"Me" if msg["is_from_me"] else "Other"}\nMessage: {msg["text"]}\n-----\n'
            for msg in messages
        )
        content = types.Content(parts=[types.Part(text=formatted_msgs)], role='user')

        session_id = f'session_{conversation_id}'
        await session_service.create_session(
            app_name='fact_extraction', session_id=session_id, user_id='admin'
        )

        try:
            events = runner.run_async(user_id='admin', session_id=session_id, new_message=content)
            event = await anext(events)

            if not (event and event.content and event.content.parts):
                print(f'Agent returned no content for conversation {conversation_id}.')
                return

            raw_output = event.content.parts[-1].text
            facts = ExtractedFacts.model_validate_json(raw_output)
            insert_facts(conn, conversation_id=conversation_id, facts=facts)
            print(
                f'Extracted and saved {len(facts.facts)} facts for conversation {conversation_id}.'
            )

        except ValidationError as e:
            print(
                f'Schema validation failed for conversation {conversation_id}: {e}'
                '\nRaw output: {raw_output}'
            )
        finally:
            await session_service.delete_session(
                app_name='fact_extraction', session_id=session_id, user_id='admin'
            )


async def run_fact_extraction_pipeline(
    max_concurrent: int = 5, batch_size: int = 50, delay_between_batches: int = 5
) -> None:
    """Orchestrate the entire fact extraction process from the knowledge base.

    Args:
        max_concurrent: The maximum number of concurrent API calls.
        batch_size: The number of conversations to process in each batch.
        delay_between_batches: Seconds to wait between processing batches.

    """
    # Ensure the database and tables are created before starting
    with sqlite3.connect(DB_NAME) as conn:
        create_db(conn)
        conversation_ids = get_all_conversation_ids(conn)

    if not conversation_ids:
        print('No conversations found in knowledge base. Skipping fact extraction.')
        return

    print(f'Found {len(conversation_ids)} unique conversations to process for facts.')
    semaphore = asyncio.Semaphore(max_concurrent)

    for i in range(0, len(conversation_ids), batch_size):
        batch_ids = conversation_ids[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = -(-len(conversation_ids) // batch_size)  # Ceiling division

        print(
            f'\nProcessing Batch {batch_num}/{total_batches} ({len(batch_ids)} conversations)'
        )

        with sqlite3.connect(DB_NAME) as conn:
            tasks = [_extract_and_save_facts(conn, convo_id, semaphore) for convo_id in batch_ids]
            await asyncio.gather(*tasks)

        if batch_num < total_batches:
            print(f'--- Batch {batch_num} complete. Waiting {delay_between_batches}s... ---')
            await asyncio.sleep(delay_between_batches)

    print('\n--- Finished processing all conversations for fact extraction. ---')
