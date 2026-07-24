from bot.threshold_logic import (
    ANNOUNCE_DROP,
    CANCEL_TIMER,
    NO_ACTION,
    SCHEDULE_TIMER,
    decide_action_after_vote_change,
    should_announce_on_timer_fire,
)


def test_not_announced_reaching_threshold_with_no_pending_timer_schedules_timer():
    assert (
        decide_action_after_vote_change(new_count=4, announced=False, timer_pending=False)
        == SCHEDULE_TIMER
    )


def test_not_announced_reaching_threshold_with_pending_timer_does_not_reschedule():
    # A vote on top of an already-qualifying count (a 5th voter, or a 4th
    # after the timer already started) must not touch a timer that's
    # already counting down -- only the FIRST crossing of the threshold
    # starts it.
    assert (
        decide_action_after_vote_change(new_count=5, announced=False, timer_pending=True)
        == NO_ACTION
    )
    assert (
        decide_action_after_vote_change(new_count=4, announced=False, timer_pending=True)
        == NO_ACTION
    )


def test_not_announced_below_threshold_with_pending_timer_cancels_it():
    assert (
        decide_action_after_vote_change(new_count=3, announced=False, timer_pending=True)
        == CANCEL_TIMER
    )


def test_not_announced_below_threshold_with_no_pending_timer_does_nothing():
    assert (
        decide_action_after_vote_change(new_count=3, announced=False, timer_pending=False)
        == NO_ACTION
    )


def test_announced_dropping_below_threshold_announces_drop():
    assert (
        decide_action_after_vote_change(new_count=3, announced=True, timer_pending=False)
        == ANNOUNCE_DROP
    )


def test_announced_staying_above_threshold_no_action():
    assert (
        decide_action_after_vote_change(new_count=5, announced=True, timer_pending=False)
        == NO_ACTION
    )
    assert (
        decide_action_after_vote_change(new_count=4, announced=True, timer_pending=False)
        == NO_ACTION
    )


def test_should_announce_on_timer_fire_true_when_still_at_threshold():
    assert should_announce_on_timer_fire(4) is True


def test_should_announce_on_timer_fire_false_when_dropped():
    assert should_announce_on_timer_fire(3) is False
