# tests/test_repo_sqlite.py
### Modules importation
from pathlib import Path
from datetime import datetime, timedelta

from src.core.models import FlashcardCreate
from src.storage.repo import FlashcardRepo


### Function : test_repo_add_and_get_due()
def test_repo_add_and_get_due(tmp_path: Path):
    """
    Checks the addition of flashcards and their retrieval
    via the `get_due` method.
    """
    db_path = tmp_path / "test.db"
    repo = FlashcardRepo(db_path)

    ### Add two flashcards
    ids = repo.add_cards(
        [
            FlashcardCreate(question="Q1", answer="A1"),
            FlashcardCreate(question="Q2", answer="A2"),
        ]
    )
    assert len(ids) == 2

    ### Newly created cards must be paid immediately
    due = repo.get_due(limit=10)
    assert len(due) >= 2
    assert due[0].question in {"Q1", "Q2"}


### Function : test_repo_get_by_id()
def test_repo_get_by_id(tmp_path: Path):
    """
    Checks the retrieval of a flashcard by its ID
    """
    repo = FlashcardRepo(tmp_path / "test.db")
    ids = repo.add_cards([FlashcardCreate(question="Q", answer="A")])

    card = repo.get_by_id(ids[0])
    assert card is not None
    assert card.id == ids[0]
    assert card.question == "Q"
    assert card.answer == "A"


### Function : test_repo_update_review_changes_due_date()
def test_repo_update_review_changes_due_date(tmp_path: Path):
    """
    Verify that updating the revision status
    correctly changes the SM-2 fields and the due date.
    """
    repo = FlashcardRepo(tmp_path / "test.db")
    ids = repo.add_cards([FlashcardCreate(question="Q", answer="A")])
    card_id = ids[0]

    ### New future revision date
    future_due = datetime.now() + timedelta(days=3)
    repo.update_review(
        card_id=card_id,
        ease_factor=2.2,
        interval_days=3,
        repetitions=1,
        due_at=future_due,
    )

    card = repo.get_by_id(card_id)
    assert card is not None
    assert card.ease_factor == 2.2
    assert card.interval_days == 3
    assert card.repetitions == 1

    ### Tolerant comparison: SQLite stores dates to the second
    assert card.due_at >= future_due - timedelta(seconds=1)

    ### The card should no longer be considered immediately due.
    due_now = repo.get_due(limit=10)
    assert all(c.id != card_id for c in due_now)
