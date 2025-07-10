import json
from pathlib import Path
from datetime import datetime
from pydantic import BaseModel, Field, ValidationError

# Re-using the Pydantic schemas for TimelineEvent
class TimelineEvent(BaseModel):
    """Represents a specific event that occurred on a particular day."""
    event_date: str = Field(
        ..., description='The estimated date of the event, in YYYY-MM-DD format.'
    )
    description: str = Field(..., description='A concise, past-tense description of the event.')
    supporting_fact_ids: list[int] = Field(
        ..., description='List of fact IDs from the input that support this event.'
    )

class MonthlyTimeline(BaseModel):
    """
    Simplified schema to load only the relevant parts (events) from saved JSONs.
    """
    key_events: list[TimelineEvent] = []


def create_master_timeline_md(output_dir: str = 'monthly_timelines', output_filename: str = 'master_timeline.md'):
    """
    Reads all monthly timeline JSONs, combines key events,
    and generates a single Markdown file focused only on events.
    """
    json_files = Path(output_dir).glob('timeline_*.json')
    all_events = []

    print(f"Searching for JSON files in: {Path(output_dir).resolve()}")

    for json_file in sorted(json_files): # Sort to process chronologically
        print(f"Processing: {json_file.name}")
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Use Pydantic to validate and load relevant parts
                monthly_data = MonthlyTimeline(**data)
                all_events.extend(monthly_data.key_events)
        except ValidationError as e:
            print(f"Error validating {json_file.name}: {e}")
            continue
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from {json_file.name}: {e}")
            continue
        except Exception as e:
            print(f"An unexpected error occurred with {json_file.name}: {e}")
            continue

    # Sort all events chronologically
    all_events.sort(key=lambda x: datetime.fromisoformat(x.event_date))

    # Prepare the Markdown content
    master_md_content = []
    master_md_content.append("## 🗓️ Key Events\n\n")
    if not all_events:
        master_md_content.append("No key events found across all timelines.\n")
    else:
        current_year = None
        current_month = None
        for event in all_events:
            event_date_obj = datetime.fromisoformat(event.event_date)
            year = event_date_obj.year
            month = event_date_obj.month

            if year != current_year:
                master_md_content.append(f"\n### {year}\n")
                current_year = year
                current_month = None # Reset month when year changes

            if month != current_month:
                # Add a newline before the month heading if it's not the very first one
                if current_month is not None:
                    master_md_content.append("\n")
                master_md_content.append(f"#### {event_date_obj.strftime('%B')}\n")
                current_month = month

            master_md_content.append(f"- **{event_date_obj.strftime('%Y-%m-%d')}:** {event.description}\n")

    # Write to file
    output_path = Path(output_filename)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.writelines(master_md_content)

    print(f"\nMaster timeline saved to: {output_path.resolve()}")

if __name__ == '__main__':
    create_master_timeline_md()