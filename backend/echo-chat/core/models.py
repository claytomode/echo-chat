"""Models."""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Message(BaseModel):
    """A single message in a conversation."""

    id: str | None = None
    conversation_id: str
    text: str
    is_from_me: bool
    date_iso: str
    timestamp_seconds: float


class SubjectEnum(str, Enum):
    """The subject of a fact."""

    me = 'me'
    other = 'other'
    both = 'both'


class Fact(BaseModel):
    """A fact extracted extracted from a text conversation."""

    subject: Literal['me', 'other', 'relationship'] = Field(
        ...,
        description=(
            "Who the fact is about: 'me' (you), 'other' (the other person), or 'relationship'."
        ),
    )
    predicate: str = Field(..., description='A short string describing the relation or attribute.')
    object: str = Field(..., description='The value or description of the fact.')
    confidence: float = Field(
        ...,
        ge=0,
        le=1,
        description='A float between 0 and 1 indicating confidence in the fact.',
    )
    source_text: str = Field(..., description='The exact message text where this fact appears.')
    fact_date: datetime = Field(..., description="The estimated date of the fact's origin.")


class ExtractedFacts(BaseModel):
    """List of extracted facts from a text conversation."""

    facts: list[Fact] = Field(
        ..., description='A list of factual statements extracted from text messages.'
    )


class FactFromDB(Fact):
    """A single fact retrieved from the database, including its ID."""

    id: int


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
        description=(
            "A high-level narrative paragraph summarizing the month's key activities,"
            ' themes, and emotional tone.'
        ),
    )
    key_events: list[TimelineEvent] = Field(
        ...,
        description=(
            'A chronologically sorted list of specific, dateable events'
            ' that happened during the month.'
        ),
    )
    key_learnings: list[KeyLearning] = Field(
        ...,
        description=(
            "A list of important, non-event-based facts or insights learned'' about the subjects"
            " ('me', 'other', 'relationship')."
        ),
    )
