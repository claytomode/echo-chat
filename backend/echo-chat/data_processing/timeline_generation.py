import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from google.adk import Agent, Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import ValidationError

from config.settings import MODEL_NAME
from core.models import FactFromDB, MonthlyFactList, MonthlyTimeline


def get_facts_for_month(
    year: int, month: int, db_path: str = 'knowledge_base.db'
) -> list[FactFromDB]:
    """Connect to the database and retrieves all facts for a specific month."""
    if not Path(db_path).exists():
        print(f"Error: Database file not found at '{db_path}'")
        return []

    conn = None
    results = []
    month_str = f'{month:02d}'
    year_month_str = f'{year}-{month_str}'

    print(f'Querying for facts from month: {year_month_str}')

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT id, date, subject, predicate, object, confidence FROM facts WHERE strftime('%Y-%m', date) = ? ORDER BY date"
        cursor.execute(query, (year_month_str,))
        rows = cursor.fetchall()

        for row in rows:
            try:
                results.append(FactFromDB(**dict(row)))
            except ValidationError as e:
                print(f'Skipping row with ID {row["id"]} due to data validation error: {e}')

    except sqlite3.Error as e:
        print(f'SQLite error when querying facts: {e}')
        return []
    finally:
        if conn:
            conn.close()

    return results


def get_all_unique_months(db_path: str = 'knowledge_base.db') -> list[tuple[int, int]]:
    """Retrieve all unique year-month combinations from the 'facts' table."""
    if not Path(db_path).exists():
        print(f"Error: Database file not found at '{db_path}'")
        return []

    conn = None
    unique_months = set()
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        query = "SELECT DISTINCT strftime('%Y', date), strftime('%m', date) FROM facts ORDER BY strftime('%Y', date), strftime('%m', date)"
        cursor.execute(query)
        rows = cursor.fetchall()
        for row in rows:
            unique_months.add((int(row[0]), int(row[1])))
    except sqlite3.Error as e:
        print(f'SQLite error when querying unique months: {e}')
    finally:
        if conn:
            conn.close()
    return sorted(unique_months)


timeline_agent = Agent(
    name='monthly_timeline_generator',
    model=MODEL_NAME,
    description='Synthesizes a list of facts into a narrative monthly timeline.',
    instruction=(
        'You are an expert biographer and data synthesizer. Your task is to analyze a list of dated facts '
        "extracted from a person's life and generate a coherent, narrative timeline for that month. "
        "The facts concern 'me' (the user), 'other' (another person), and their 'relationship'."
        '\n\n'
        'From the list of facts, you must:'
        '\n1. Write a high-level **narrative summary** of the month.'
        '\n2. Identify and list specific, dateable **Key Events** that occurred, sorting them chronologically.'
        '\n3. Distill and list the most important **Key Learnings**—these are new insights or static facts revealed during the month, not tied to a single event.'
        '\n\nYour output must be a single JSON object that strictly adheres to the `MonthlyTimeline` schema.'
    ),
    output_schema=MonthlyTimeline,
)



async def create_monthly_timeline(year: int, month: int, save_json: bool = False):
    """Orchestrate fetching facts, running the AI agent, and reporting a monthly timeline."""
    facts = get_facts_for_month(year, month)
    if not facts:
        print(f'No facts found for {year}-{month:02d}. Cannot generate a timeline.')
        return

    print(f'Found {len(facts)} facts. Sending to AI for timeline generation...')

    session_service = InMemorySessionService()
    runner = Runner(
        app_name='timeline_app',
        agent=timeline_agent,
        session_service=session_service,
    )

    input_data = MonthlyFactList(facts=facts)
    content = types.Content(
        parts=[types.Part(text=input_data.model_dump_json(indent=2))], role='user'
    )
    session_id = f'timeline_session_{year}_{month}'
    raw_output = ''

    try:
        await session_service.create_session(
            app_name='timeline_app', session_id=session_id, user_id='admin'
        )
        events = runner.run_async(user_id='admin', session_id=session_id, new_message=content)
        event = await anext(events)

        if not (event and event.content and event.content.parts):
            print('Error: AI agent did not return any content.')
            return

        raw_output = event.content.parts[-1].text
        timeline = MonthlyTimeline.model_validate_json(raw_output)

        if save_json:
            output_dir = Path('monthly_timelines')
            output_dir.mkdir(exist_ok=True)
            file_name = f'timeline_{year}-{month:02d}.json'
            output_path = output_dir / file_name
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(timeline.model_dump_json(indent=2))
            print(f'Timeline for {year}-{month:02d} saved to: {output_path}')

    except ValidationError:
        print(f'\n--- ERROR validating AI output for {year}-{month:02d} ---')
        print(raw_output)
    except Exception as e:
        print(
            f'\nAn unexpected error occurred during timeline generation for {year}-{month:02d}: {e}'
        )
    finally:
        await session_service.delete_session(
            app_name='timeline_app', session_id=session_id, user_id='admin'
        )



def create_master_timeline_md(
    output_dir: str = 'monthly_timelines', output_filename: str = 'master_timeline.md'
):
    """Read all monthly timeline JSONs, combines key events, and generates a single Markdown file."""
    json_dir = Path(output_dir)
    if not json_dir.exists():
        print(f"Directory '{output_dir}' not found. Cannot create master timeline.")
        return

    all_events = []
    print(f'\nSearching for monthly timeline JSON files in: {json_dir.resolve()}')

    for json_file in sorted(json_dir.glob('timeline_*.json')):
        try:
            with Path.open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                monthly_data = MonthlyTimeline.model_validate(data)
                all_events.extend(monthly_data.key_events)
        except (ValidationError, json.JSONDecodeError) as e:
            print(f'Skipping {json_file.name} due to processing error: {e}')
            continue

    all_events.sort(key=lambda x: datetime.fromisoformat(x.event_date))
    md_content = ['# Master Timeline of Events\n']
    if not all_events:
        md_content.append('No key events found across all timelines.\n')
    else:
        current_year = None
        current_month = None
        for event in all_events:
            event_date = datetime.fromisoformat(event.event_date)
            if event_date.year != current_year:
                md_content.append(f'\n## {event_date.year}\n')
                current_year = event_date.year
                current_month = None

            if event_date.month != current_month:
                md_content.append(f'\n### {event_date.strftime("%B")}\n')
                current_month = event_date.month

            md_content.append(f'- **{event_date.strftime("%Y-%m-%d")}:** {event.description}\n')

    output_path = Path(output_filename)
    with Path.open(output_path, 'w', encoding='utf-8') as f:
        f.writelines(md_content)

    print(f'\nMaster timeline successfully saved to: {output_path.resolve()}')