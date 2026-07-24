from bot.threshold_logic import (
    ANNOUNCE_DROP,
    CANCEL_TIMER,
    NO_ACTION,
    SCHEDULE_TIMER,
    decide_action_after_vote_change,
    should_announce_on_timer_fire,
)


def test_not_announced_reaching_threshold_schedules_timer():
    assert decide_action_after_vote_change(new_count=4, announced=False) == SCHEDULE_TIMER


def test_not_announced_below_threshold_cancels_timer():
    assert decide_action_after_vote_change(new_count=3, announced=False) == CANCEL_TIMER


def test_announced_dropping_below_threshold_announces_drop():
    assert decide_action_after_vote_change(new_count=3, announced=True) == ANNOUNCE_DROP


def test_announced_staying_above_threshold_no_action():
    assert decide_action_after_vote_change(new_count=5, announced=True) == NO_ACTION
    assert decide_action_after_vote_change(new_count=4, announced=True) == NO_ACTION


def test_should_announce_on_timer_fire_true_when_still_at_threshold():
    assert should_announce_on_timer_fire(4) is True


def test_should_announce_on_timer_fire_false_when_dropped():
    assert should_announce_on_timer_fire(3) is False
