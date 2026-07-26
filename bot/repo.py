"""Data-access layer for the poll bot.

Plain CRUD-style operations against the SQLAlchemy models. No Telegram/aiogram
imports here, no business logic beyond straightforward persistence.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import Option, Poll, Reminder, ThresholdState, Vote

# --- Poll creation / retrieval -------------------------------------------------


async def create_poll(
    session: AsyncSession,
    chat_id: int,
    title: str,
    options: list[tuple[str, dt.date | None]],
    message_thread_id: int | None = None,
) -> Poll:
    poll = Poll(chat_id=chat_id, title=title, status="active", message_thread_id=message_thread_id)
    session.add(poll)
    await session.flush()

    for position, (text, option_date) in enumerate(options):
        option = Option(poll_id=poll.id, text=text, date=option_date, position=position)
        session.add(option)
        await session.flush()
        session.add(ThresholdState(option_id=option.id, announced=False))
        session.add(Reminder(option_id=option.id, sent=False))

    await session.commit()
    await session.refresh(poll)
    return poll


async def set_poll_message(session: AsyncSession, poll_id: int, message_id: int) -> None:
    poll = await session.get(Poll, poll_id)
    poll.message_id = message_id
    await session.commit()


async def get_poll_options(session: AsyncSession, poll_id: int) -> list[Option]:
    result = await session.execute(
        select(Option)
        .where(Option.poll_id == poll_id, Option.is_deleted.is_(False))
        .order_by(Option.position)
    )
    return list(result.scalars().all())


async def get_poll(session: AsyncSession, poll_id: int) -> Poll | None:
    return await session.get(Poll, poll_id)


async def mark_poll_orphaned(session: AsyncSession, poll_id: int) -> None:
    poll = await session.get(Poll, poll_id)
    if poll is not None:
        poll.status = "orphaned"
        await session.commit()


async def delete_poll(session: AsyncSession, poll_id: int) -> None:
    result = await session.execute(select(Option).where(Option.poll_id == poll_id))
    options = list(result.scalars().all())

    for option in options:
        votes = await get_voters(session, option.id)
        for vote in votes:
            await session.delete(vote)

        threshold_state = await session.get(ThresholdState, option.id)
        if threshold_state:
            await session.delete(threshold_state)

        reminder = await session.get(Reminder, option.id)
        if reminder:
            await session.delete(reminder)

        await session.delete(option)

    poll = await session.get(Poll, poll_id)
    await session.delete(poll)
    await session.commit()


# --- Voting ----------------------------------------------------------------


async def toggle_vote(
    session: AsyncSession,
    option_id: int,
    user_id: int,
    username: str | None,
    first_name: str,
) -> tuple[bool, int]:
    result = await session.execute(
        select(Vote).where(Vote.option_id == option_id, Vote.user_id == user_id)
    )
    existing = result.scalar_one_or_none()

    if existing:
        await session.delete(existing)
        voted_now = False
    else:
        session.add(Vote(option_id=option_id, user_id=user_id, username=username, first_name=first_name))
        voted_now = True

    await session.commit()
    count = await get_vote_count(session, option_id)
    return voted_now, count


async def get_vote_count(session: AsyncSession, option_id: int) -> int:
    result = await session.execute(select(Vote).where(Vote.option_id == option_id))
    return len(result.scalars().all())


async def get_voters(session: AsyncSession, option_id: int) -> list[Vote]:
    result = await session.execute(
        select(Vote).where(Vote.option_id == option_id).order_by(Vote.voted_at)
    )
    return list(result.scalars().all())


# --- Edit / delete option ---------------------------------------------------


async def edit_option_text(session: AsyncSession, option_id: int, new_text: str) -> Option:
    option = await session.get(Option, option_id)
    option.text = new_text
    await session.commit()
    await session.refresh(option)
    return option


async def edit_option_date(session: AsyncSession, option_id: int, new_date: dt.date) -> Option:
    option = await session.get(Option, option_id)
    option.date = new_date
    await session.commit()
    await session.refresh(option)
    return option


async def add_option(session: AsyncSession, poll_id: int, text: str, option_date: dt.date | None) -> Option:
    existing = await get_poll_options(session, poll_id)
    next_position = (max(o.position for o in existing) + 1) if existing else 0

    option = Option(poll_id=poll_id, text=text, date=option_date, position=next_position)
    session.add(option)
    await session.flush()
    session.add(ThresholdState(option_id=option.id, announced=False))
    session.add(Reminder(option_id=option.id, sent=False))
    await session.commit()
    await session.refresh(option)
    return option


async def delete_option(session: AsyncSession, option_id: int) -> None:
    votes = await get_voters(session, option_id)
    for vote in votes:
        await session.delete(vote)

    option = await session.get(Option, option_id)
    option.is_deleted = True

    threshold_state = await session.get(ThresholdState, option_id)
    if threshold_state:
        await session.delete(threshold_state)

    reminder = await session.get(Reminder, option_id)
    if reminder:
        await session.delete(reminder)

    await session.commit()


# --- Threshold / reminder state ---------------------------------------------


async def is_announced(session: AsyncSession, option_id: int) -> bool:
    state = await session.get(ThresholdState, option_id)
    return bool(state and state.announced)


async def set_announced(session: AsyncSession, option_id: int, value: bool) -> None:
    state = await session.get(ThresholdState, option_id)
    state.announced = value
    await session.commit()


async def is_reminder_sent(session: AsyncSession, option_id: int) -> bool:
    reminder = await session.get(Reminder, option_id)
    return bool(reminder and reminder.sent)


async def set_reminder_sent(session: AsyncSession, option_id: int, value: bool) -> None:
    reminder = await session.get(Reminder, option_id)
    reminder.sent = value
    await session.commit()


async def get_options_due_for_reminder(session: AsyncSession, target_date: dt.date) -> list[Option]:
    result = await session.execute(
        select(Option)
        .join(ThresholdState, ThresholdState.option_id == Option.id)
        .join(Reminder, Reminder.option_id == Option.id)
        .where(
            Option.date == target_date,
            Option.is_deleted.is_(False),
            ThresholdState.announced.is_(True),
            Reminder.sent.is_(False),
        )
    )
    return list(result.scalars().all())
