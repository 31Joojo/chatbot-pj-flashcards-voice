# src/ui/state.py
### Modules importation
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, Optional

DEFAULT_MODEL = "qwen2.5:7b-instruct"

### ----------------------------- Functions ----------------------------- ###
### Function : default_stats()
def default_stats() -> Dict[str, Any]:
    """
    Create a default statistics dictionary for a chat session.

    This function initializes all counters and aggregates used
    to track user performance during a review session.

    :return Dict[str, Any]: Initialized statistics structure
    """
    return {
        "asked": 0,
        "graded": 0,
        "conf_sum": 0.0,
        "grade_counts": {
            "Again": 0,
            "Hard": 0,
            "Good": 0,
            "Easy": 0,
        },
        "last_details": "",
    }

### Function : default_chat_state()
def default_chat_state(model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """
    Initialize the default chat state structure.

    It prevents inconsistencies caused by duplicated literals.

    :param str model: Ollama model name to use for the session
    :return Dict[str, Any]: Initialized chat state dictionary
    """
    return {
        ### Conversation phase
        "phase": "idle",

        ### Current source text and identifier
        "source_text": "",
        "source_id": None,

        ### Active model
        "model": (model or DEFAULT_MODEL),

        ### Flashcard currently being reviewed
        "pending_card_id": None,
        "details_visible": False,

        ### Embedded session statistics
        **default_stats(),
    }

### Function : reset_chat_state()
def reset_chat_state(chat_state: Optional[Dict[str, Any]] = None, *, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """
    Perform a full reset of the chat state.

    This function is used when starting a new
    learning session from scratch.

    :param Optional[Dict[str, Any]] chat_state: Existing chat state
    :param str model: Ollama model name for the new session
    :return Dict[str, Any]: Freshly initialized chat state
    """
    return default_chat_state(model=model)

### Function : reset_stats()
def reset_stats(chat_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Reset only the session statistics within the chat state.

    The source text, model, and conversation phase are preserved.

    :param Dict[str, Any] chat_state: Current chat state
    :return Dict[str, Any]: Updated chat state with reset statistics
    """
    stats = default_stats()

    ### Update only statistical fields
    chat_state.update(stats)
    return chat_state

### Function : update_stats()
def update_stats(chat_state: Dict[str, Any], grade: str, conf: float) -> Dict[str, Any]:
    """
    Update session statistics after grading a flashcard answer.

    This function increments counters and aggregates confidence
    scores for later analysis.

    :param Dict[str, Any] chat_state: Current chat state
    :param str grade: Assigned grade "Again" "Hard" "Good" "Easy"
    :param float conf: Confidence score associated with the grading
    :return Dict[str, Any]: Updated chat state
    """
    ### Update total number of graded answers
    chat_state["graded"] = int(chat_state.get("graded", 0)) + 1

    ### Accumulate confidence scores
    chat_state["conf_sum"] = float(chat_state.get("conf_sum", 0.0)) + float(conf or 0.0)

    ### Update grade distribution
    counts = chat_state.get("grade_counts") or {
        "Again": 0,
        "Hard": 0,
        "Good": 0,
        "Easy": 0,
    }
    if grade in counts:
        counts[grade] = int(counts.get(grade, 0)) + 1
    chat_state["grade_counts"] = counts
    return chat_state

### Function : avg_conf()
def avg_conf(chat_state: Dict[str, Any]) -> float:
    """
    Compute the average confidence score for the current session.

    :param Dict[str, Any] chat_state: Current chat state
    :return float: Average confidence score, or 0 if no grading occurred
    """
    graded = int(chat_state.get("graded", 0))
    if graded <= 0:
        return 0.0

    return float(chat_state.get("conf_sum", 0.0)) / graded
