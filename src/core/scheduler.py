# src/core/scheduler.py
### Modules importation
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional


### ------------------------------ Classes ------------------------------ ###
### Class : SM2State
@dataclass
class SM2State:
    """
    Data container representing the SM-2 scheduling state of a flashcard.

    This class stores the minimal set of parameters required by the
    SM-2 spaced repetition algorithm to compute the next review interval.

    :arg float ease_factor: Ease factor controlling interval growth
    :arg int interval_days: Current interval before next review
    :arg int repetitions: Number of consecutive successful reviews
    """
    ease_factor: float
    interval_days: int
    repetitions: int

### Class : ReviewSuggestion
@dataclass
class ReviewSuggestion:
    """
    Container describing a recommended next review date.

    :arg float score: Session performance score
    :arg int days: Recommended delay before next review in days
    :arg datetime recommended_at: Recommended review datetime
    :arg str reason: Human-readable explanation of the recommendation
    """
    score: float
    days: int
    recommended_at: datetime
    reason: str

### ------------------------------ Helpers ------------------------------ ###
### Helper : _now()
def _now() -> datetime:
    """
    Return the current UTC datetime timezone-aware.

    :return datetime: Current UTC datetime
    """
    return datetime.now(timezone.utc)

### Helper : _to_naive_utc()
def _to_naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Convert a datetime to naive UTC if needed.

    :param Optional[datetime] dt: Datetime to normalize
    :return Optional[datetime]: Naive UTC datetime or None
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt

    ### Convert to UTC and strip timezone info
    return dt.astimezone(timezone.utc).replace(tzinfo=None)

### ----------------------------- Functions ----------------------------- ###
### Function : sm2_update()
def sm2_update(state: SM2State, quality: int) -> SM2State:
    """
    Updates the revision status of a flashcard according to the SuperMemo 2 (SM-2) algorithm, used in spaced repetition systems.

    The algorithm adjusts :
    - the ease factor,
    - the interval before the next revision,
    - the number of consecutive successful repetitions,

    based on the recall quality assessed by the user.

    :param SM2State state:
        Current state of the flashcard, containing:
        - ease_factor : float
        - interval_days : int
        - repetitions : int
    :param int quality:
        Quality of recall assessed by the user, between 0 and 5:
        - 0–2 : failure or very difficult recall
        - 3 : correct recall with effort
        - 4–5 : easy or perfect recall
    :return SM2State:
        New updated status of the flashcard after applying
        the rules of the SM-2 algorithm
    """
    ### Quality normalization within the allowed range [0, 5]
    q = max(0, min(5, int(quality)))

    ### Update of the ease factor
    ef = state.ease_factor + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    ef = max(1.3, ef)

    ### If the recall fails the progress is reset
    if q < 3:
        ### reset
        return SM2State(ease_factor=ef, interval_days=1, repetitions=0)

    ### Increment in the number of successful repetitions
    reps = state.repetitions + 1

    ### Calculation of the revision interval based on the number of repetitions
    if reps == 1:
        interval = 1
    elif reps == 2:
        interval = 6
    else:
        interval = max(1, int(round(state.interval_days * ef)))

    return SM2State(ease_factor=ef, interval_days=interval, repetitions=reps)

### Function : next_due()
def next_due(interval_days: int) -> datetime:
    """
    Calculates the date of the next review of a flashcard.

    This function adds an interval (in days) to the current date
    to determine when a flashcard should
    be presented to the user again.

    :param int interval_days: Number of days to wait until the next review
    :return datetime: Date and time (UTC) corresponding to the next revision deadline
    """
    ### Calculation of the next revision date in UTC
    return datetime.now() + timedelta(days=int(interval_days))

### Function : compute_session_score()
def compute_session_score(grade_counts: Dict[str, int], avg_conf: float) -> float:
    """
    Compute a normalized session performance score.

    The score is based on a weighted average of grades
    (Again / Hard / Good / Easy) combined with the
    average confidence score.

    :param Dict[str, int] grade_counts: Count of grades assigned during the session
    :param float avg_conf: Average confidence score (0.0 to 1.0)
    :return float: Session score between 0.0 and 1.0
    """
    again = grade_counts.get("Again", 0)
    hard = grade_counts.get("Hard", 0)
    good = grade_counts.get("Good", 0)
    easy = grade_counts.get("Easy", 0)

    total = max(1, again + hard + good + easy)

    ### Pedagogical weighting of grades
    weighted = (
        0.0 * again +
        0.4 * hard +
        0.8 * good +
        1.0 * easy
    ) / total

    ### Combine grade-based score with confidence score
    score = 0.6 * weighted + 0.4 * max(0.0, min(1.0, avg_conf))

    ### Clamp final score to [0, 1]
    return max(0.0, min(1.0, score))

### Function : suggest_next_review()
def suggest_next_review(score: float, min_days: int = 1) -> ReviewSuggestion:
    """
    Suggest a next review delay based on session performance.

    :param float score: Session score between 0 and 1
    :param int min_days: Minimum number of days before next review
    :return ReviewSuggestion: Recommended review information
    """
    if score >= 0.90:
        days, reason = 7, "Très bon score : espacement plus long."
    elif score >= 0.80:
        days, reason = 4, "Bon score : espacement modéré."
    elif score >= 0.75:
        days, reason = 2, "Score correct : revoir sous 48h pour consolider."
    elif score >= 0.60:
        days, reason = 1, "Score moyen : revoir rapidement."
    else:
        days, reason = 1, "Score faible : revoir dès demain."

    ### Enforce minimum delay
    days = max(min_days, days)

    ### Compute recommended review datetime
    dt = _now() + timedelta(days=days)

    return ReviewSuggestion(
        score=score,
        days=days,
        recommended_at=dt,
        reason=reason,
    )

### Function : pick_recommended_date()
def pick_recommended_date(suggestion: ReviewSuggestion, next_due_at: Optional[datetime], ) -> datetime:
    """
    Choose the final review date between SM-2 scheduling and session recommendation.

    :param ReviewSuggestion suggestion: Session-based review recommendation
    :param Optional[datetime] next_due_at: Next due date from SM-2 scheduling
    :return datetime: Selected review datetime
    """
    nd = _to_naive_utc(next_due_at)
    sd = _to_naive_utc(suggestion.recommended_at)

    if nd is None:
        return sd
    if sd is None:
        return nd

    ### Pick the earliest review date
    return min(nd, sd)
