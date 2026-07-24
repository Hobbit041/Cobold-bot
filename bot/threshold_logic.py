DEFAULT_THRESHOLD = 4

SCHEDULE_TIMER = "schedule_or_reschedule_timer"
CANCEL_TIMER = "cancel_timer"
ANNOUNCE_DROP = "announce_drop"
NO_ACTION = "no_action"


def decide_action_after_vote_change(
    new_count: int, announced: bool, threshold: int = DEFAULT_THRESHOLD
) -> str:
    if not announced and new_count >= threshold:
        return SCHEDULE_TIMER
    if not announced and new_count < threshold:
        return CANCEL_TIMER
    if announced and new_count < threshold:
        return ANNOUNCE_DROP
    return NO_ACTION


def should_announce_on_timer_fire(current_count: int, threshold: int = DEFAULT_THRESHOLD) -> bool:
    return current_count >= threshold
