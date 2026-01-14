# tests/test_sm2.py
### Modules importation
from src.core.scheduler import SM2State, sm2_update

### Function : test_sm2_quality_below_3_resets_repetitions_and_interval()
def test_sm2_quality_below_3_resets_repetitions_and_interval():
    """
    Verify that a recall quality lower than 3
    resets the repetitions and interval.
    """
    ### Initial state with several successful repetitions
    s = SM2State(ease_factor=2.5, interval_days=10, repetitions=3)

    ### Insufficient recall
    new = sm2_update(s, quality=2)

    ### Progress must be reset
    assert new.repetitions == 0
    assert new.interval_days == 1

    ### EF should not go below 1.3
    assert new.ease_factor >= 1.3


### Function : test_sm2_first_two_success_intervals_are_1_and_6()
def test_sm2_first_two_success_intervals_are_1_and_6():
    """
    Verify that the first two successful repetitions
    use the standard SM-2 intervals (1 and 6 days).
    """
    ### Initial state of the new flashcard
    s0 = SM2State(ease_factor=2.5, interval_days=0, repetitions=0)

    ### First success
    s1 = sm2_update(s0, quality=4)
    assert s1.repetitions == 1
    assert s1.interval_days == 1

    ### Second success
    s2 = sm2_update(s1, quality=4)
    assert s2.repetitions == 2
    assert s2.interval_days == 6


### Function : test_sm2_third_success_interval_increases()
def test_sm2_third_success_interval_increases():
    """
    Check that from the third successful repetition onwards,
    the interval increases compared to the previous one.
    :return:
    """
    ### Status after two successful repetitions
    s2 = SM2State(ease_factor=2.5, interval_days=6, repetitions=2)

    ### Third success
    s3 = sm2_update(s2, quality=4)

    assert s3.repetitions == 3
    assert s3.interval_days >= 6
