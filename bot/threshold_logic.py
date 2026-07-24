DEFAULT_THRESHOLD = 4

SCHEDULE_TIMER = "schedule_or_reschedule_timer"
CANCEL_TIMER = "cancel_timer"
ANNOUNCE_DROP = "announce_drop"
NO_ACTION = "no_action"


def decide_action_after_vote_change(
    new_count: int, announced: bool, timer_pending: bool, threshold: int = DEFAULT_THRESHOLD
) -> str:
    threshold_met = new_count >= threshold

    if announced:
        return ANNOUNCE_DROP if not threshold_met else NO_ACTION

    if threshold_met:
        # Only the FIRST crossing of the threshold starts the debounce timer;
        # further votes while it's already counting down (more voters piling
        # on past 4) must not touch it.
        return NO_ACTION if timer_pending else SCHEDULE_TIMER

    return CANCEL_TIMER if timer_pending else NO_ACTION


def should_announce_on_timer_fire(current_count: int, threshold: int = DEFAULT_THRESHOLD) -> bool:
    return current_count >= threshold
