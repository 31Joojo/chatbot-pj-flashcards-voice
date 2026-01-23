# src/core/scheduler.py
### Modules importation
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional


### ------------------------------- Class ------------------------------- ###
### Class : SM2State
@dataclass
class SM2State:
    """
    Data container representing the SM-2 scheduling state of a flashcard.

    This class stores the minimal set of parameters required by the
    SM-2 spaced repetition algorithm to compute the next review interval.

    :param float ease_factor: Ease factor controlling interval growth
    :param int interval_days: Current interval before next review
    :param int repetitions: Number of consecutive successful reviews
    """
    ease_factor: float
    interval_days: int
    repetitions: int

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
