# src/ui/review_flow.py
### Modules importation
from pathlib import Path
import emoji
from typing import Optional

from src.core.scheduler import SM2State, sm2_update, next_due
from src.storage.repo import FlashcardRepo

### Setting repo for storing flashcards
DB_PATH = Path("data/flashcards.db")
repo = FlashcardRepo(DB_PATH)

### ------------------------------ Helpers ------------------------------ ###
### Helper : _label_to_quality()
def _label_to_quality(label: str) -> int:
    """
    Map a UI grade label to an SM-2 quality score.

    :param label: One of: 'Again', 'Hard', 'Good', 'Easy'
    :return int: Corresponding SM-2 quality value (0–5)
    """
    return {"Again": 1, "Hard": 3, "Good": 4, "Easy": 5}.get(label, 4)

### ------------------------------ Wrappers ----------------------------- ###
### Wrapper : grade_again()
def grade_again(cid):
    """Shortcut for grading a card as 'Again'."""
    return grade_card(cid, "Again")

### Wrapper : grade_hard()
def grade_hard(cid):
    """Shortcut for grading a card as 'Hard'."""
    return grade_card(cid, "Hard")

### Wrapper : grade_good()
def grade_good(cid):
    """Shortcut for grading a card as 'Good'."""
    return grade_card(cid, "Good")

### Wrapper : grade_easy()
def grade_easy(cid):
    """Shortcut for grading a card as 'Easy'."""
    return grade_card(cid, "Easy")

### ----------------------------- Functions ----------------------------- ###
### Function : load_due_card()
def load_due_card(source_id: Optional[int] = None):
    """
    Load the next flashcard that is due for review.

    :param Optional[int] source_id: ID of the source text
    :return Tuple[Any, str, str, str]: Card ID, metadata info string, question text, placeholder answer
    """
    due = repo.get_due(limit=1, source_id=source_id)

    if not due:
        return None, emoji.emojize(":party_popper:") + " No cards due at the moment.", "—", "—"

    card = due[0]
    info = (
        f"Due: {card.due_at.isoformat(timespec='seconds')} | "
        f"EF={card.ease_factor:.2f} | "
        f"Int={card.interval_days}d | "
        f"Rep={card.repetitions}"
    )

    return card.id, info, card.question, "—"

### Function : reveal_answer()
def reveal_answer(card_id):
    """
    Reveal the answer (and optional hint) for a flashcard.

    :param card_id: Identifier of the current flashcard
    :return: Answer text formatted for display
    """
    if not card_id:
        return "—"

    card = repo.get_by_id(int(card_id))
    if not card:
        return "—"

    hint = f"\n\n{emoji.emojize(':light_bulb:')} Hint: {card.hint}" if card.hint else ""
    return f"**Answer:** {card.answer}{hint}"

### Function : grade_card()
def grade_card(card_id, grade_label, source_id: Optional[int] = None):
    """
    Apply a recall grade to a flashcard and update its review schedule.

    This function:
    - retrieves the flashcard,
    - applies the SM-2 algorithm,
    - updates the database,
    - loads the next due card.

    :param card_id: Identifier of the flashcard being reviewed
    :param grade_label: Recall quality label selected by the user
    :param source_id: ID of the source text
    :return Tuple[Any, str, str, str]: Updated card ID, status message, next question, metadata info
    """
    if not card_id:
        return None, emoji.emojize(":cross_mark:") + " Please load a card first.", "—", "—"

    card = repo.get_by_id(int(card_id))
    if not card:
        return None, emoji.emojize(":cross_mark:") + " Card not found.", "—", "—"

    ### Convert UI label to SM-2 quality score
    q = _label_to_quality(grade_label)

    ### Apply SM-2 update
    new_state = sm2_update(
        SM2State(card.ease_factor, card.interval_days, card.repetitions),
        q
    )
    due_at = next_due(new_state.interval_days)

    ### Persist updated review state
    repo.update_review(
        card_id=card.id,
        ease_factor=new_state.ease_factor,
        interval_days=new_state.interval_days,
        repetitions=new_state.repetitions,
        due_at=due_at,
    )

    ### Load next due card
    next_id, info, question, answer = load_due_card(source_id=source_id)
    return next_id, f"{emoji.emojize(':check_mark_button:')} Graded: {grade_label}", question, info
