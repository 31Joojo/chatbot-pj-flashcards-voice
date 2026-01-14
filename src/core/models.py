# src/core/models.py
### Modules importation
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List


### Class : FlashcardCreate
@dataclass
class FlashcardCreate:
    """
    Data model representing a flashcard to be created.

    This class is used during the generation or initial insertion
    of flashcards, before they are persisted in the database.
    """
    ### Educational content
    question: str
    answer: str

    ### Optional information
    hint: str = ""
    tags: Optional[List[str]] = None
    source_text: str = ""


### Class : Flashcard
@dataclass
class Flashcard(FlashcardCreate):
    """
    Data model representing a persistent flashcard.

    This class extends `FlashcardCreate` by adding :
    - a unique identifier,
    - temporal metadata,
    - the fields required for the SM-2 spaced repetition algorithm.
    """
    ### Unique ID
    id: int = -1

    ### Creation metadata
    created_at: datetime = datetime.now()

    ### SM-2 fields
    ease_factor: float = 2.5
    interval_days: int = 0
    repetitions: int = 0
    due_at: datetime = datetime.now()
    last_reviewed_at: Optional[datetime] = None
