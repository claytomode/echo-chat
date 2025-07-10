import asyncio
import sqlite3
import json
from datetime import datetime
from pathlib import Path

from google.adk import Agent, Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

# Assume a config file exists for the model name, similar to your original script.
# You can replace this with a hardcoded string if you prefer.
# e.g., MODEL_NAME = 'gemini-1.5-pro-latest'
try:
    from config import MODEL_NAME
except ImportError:
    print('Warning: config.py not found. Using a default model name.')
    MODEL_NAME = 'gemini-1.5-pro-latest'


# --- Pydantic Schemas for AI Input and Output ---


class FactFromDB(BaseModel):
    """A single fact retrieved from the database, including its ID and date."""

    id: int
    date: str  # Keep as ISO string for the model
    subject: str
    predicate: str
    object: str
    confidence: float


class MonthlyFactList(BaseModel):
    """A list of facts from a single month to be sent to the AI for timeline generation."""

    facts: list[FactFromDB]


class TimelineEvent(BaseModel):
    """Represents a specific event that occurred on a particular day."""

    event_date: str = Field(
        ..., description='The estimated date of the event, in YYYY-MM-DD format.'
    )
    description: str = Field(..., description='A concise, past-tense description of the event.')
    supporting_fact_ids: list[int] = Field(
        ..., description='List of fact IDs from the input that support this event.'
    )


class KeyLearning(BaseModel):
    """Represents a significant piece of information or insight learned during the month."""

    description: str = Field(..., description='A summary of the new fact or insight learned.')
    supporting_fact_ids: list[int] = Field(
        ..., description='List of fact IDs from the input that reveal this learning.'
    )


class MonthlyTimeline(BaseModel):
    """The structured output from the AI, containing a full summary of the month."""

    month_summary: str = Field(
        ...,
        description="A high-level narrative paragraph summarizing the month's key activities, themes, and emotional tone.",
    )
    key_events: list[TimelineEvent] = Field(
        ...,
        description='A chronologically sorted list of specific, dateable events that happened during the month.',
    )
    key_learnings: list[KeyLearning] = Field(
        ...,
        description="A list of important, non-event-based facts or insights learned about the subjects ('me', 'other', 'relationship').",
    )


# --- Database Interaction ---


def get_facts_for_month(
    year: int, month: int, db_path: str = 'knowledge_base.db'
) -> list[FactFromDB]:
    """
    Connects to the database and retrieves all facts for a specific month.

    Args:
        year: The target year.
        month: The target month (1-12).
        db_path: Path to the knowledge_base.db file.

    Returns:
        A list of FactFromDB objects for the specified month.
    """
    if not Path(db_path).exists():
        print(f"Error: Database file not found at '{db_path}'")
        return []

    conn = None
    results = []
    # Format the month with a leading zero if needed (e.g., 7 -> '07')
    month_str = f'{month:02d}'
    year_month_str = f'{year}-{month_str}'

    print(f'Querying for facts from month: {year_month_str}')

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Use strftime to filter by year and month. Crucially, select the date column.
        query = "SELECT id, date, subject, predicate, object, confidence FROM facts WHERE strftime('%Y-%m', date) = ? ORDER BY date"
        cursor.execute(query, (year_month_str,))
        rows = cursor.fetchall()

        for row in rows:
            try:
                # Validate data from DB against our Pydantic model
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
    """
    Connects to the database and retrieves all unique year-month combinations present in the 'facts' table.

    Args:
        db_path: Path to the knowledge_base.db file.

    Returns:
        A list of tuples, where each tuple is (year, month).
    """
    if not Path(db_path).exists():
        print(f"Error: Database file not found at '{db_path}'")
        return []

    conn = None
    unique_months = set()
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # Extract year and month from the date column
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
    return sorted(list(unique_months))


# --- AI Agent Definition ---

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


# --- Main Execution Logic ---


async def create_monthly_timeline(year: int, month: int, save_json: bool = False):
    """
    The main function to orchestrate fetching, synthesizing, and reporting a monthly timeline.
    Optionally saves the generated timeline as a JSON file.
    """
    # 1. Fetch facts from the database
    facts = get_facts_for_month(year, month)
    if not facts:
        print(f'No facts found for {year}-{month:02d}. Cannot generate a timeline.')
        return

    print(f'Found {len(facts)} facts. Sending to AI for timeline generation...')

    # 2. Prepare data and run the AI Agent
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
    try:
        await session_service.create_session(
            app_name='timeline_app', session_id=session_id, user_id='admin'
        )

        # 3. Run the agent and get the synthesized timeline
        events = runner.run_async(user_id='admin', session_id=session_id, new_message=content)
        event = await anext(events)

        if not (event and event.content and event.content.parts):
            print('Error: AI agent did not return any content.')
            return

        raw_output = event.content.parts[-1].text
        timeline = MonthlyTimeline.model_validate_json(raw_output)

        # 4. Print the final report
        month_name = datetime(year, month, 1).strftime('%B')
        print('\n' + '=' * 60)
        print(f'    TIMELINE AND SUMMARY FOR {month_name.upper()} {year}')
        print('=' * 60 + '\n')

        print('## 📝 Monthly Summary')
        print(timeline.month_summary)
        print('\n' + '---')

        print('\n## 🗓️ Key Events')
        if not timeline.key_events:
            print('No specific events were identified for this month.')
        else:
            for event in timeline.key_events:
                # Parse date for prettier formatting
                event_date_obj = datetime.fromisoformat(event.event_date)
                print(f'  - **{event_date_obj.strftime("%B %d, %Y")}:** {event.description}')
        print('\n' + '---')

        print('\n## 💡 Key Learnings & Insights')
        if not timeline.key_learnings:
            print('No new key learnings or insights were identified this month.')
        else:
            for learning in timeline.key_learnings:
                print(f'  - {learning.description}')

        print('\n' + '=' * 60)

        # 5. Save the JSON output if requested
        if save_json:
            output_dir = Path('monthly_timelines')
            output_dir.mkdir(exist_ok=True)  # Create directory if it doesn't exist
            file_name = f'timeline_{year}-{month:02d}.json'
            output_path = output_dir / file_name
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(timeline.model_dump_json(indent=2))
            print(f'\nTimeline saved to: {output_path}')

    except ValidationError as e:
        print('\n--- ERROR ---')
        print("Failed to validate the AI's output. It may not match the required Timeline format.")
        print(f'Validation Error: {e}')
        print('\nRaw AI Output:')
        print(raw_output)
    except Exception as e:
        print(f'\nAn unexpected error occurred: {e}')
    finally:
        # Clean up the session
        try:
            await session_service.delete_session(
                app_name='timeline_app', session_id=session_id, user_id='admin'
            )
        except Exception:
            pass  # Ignore errors on cleanup


if __name__ == '__main__':
    # --- Configuration ---
    # Set to True to generate and save JSON files for all months
    SAVE_JSON_OUTPUT = True  # Determines if the JSON output should be saved

    db_path = 'knowledge_base.db'  # Make sure this path is correct
    unique_months = get_all_unique_months(db_path)
    if not unique_months:
        print('No unique months found in the database. Exiting.')
    else:
        print(f'Found {len(unique_months)} unique month(s) in the database. Processing...')
        for year, month in unique_months:
            print(f'\nProcessing timeline for {year}-{month:02d}...')
            asyncio.run(
                create_monthly_timeline(year=year, month=month, save_json=SAVE_JSON_OUTPUT)
            )
            print('-' * 70)  # Separator for clarity

