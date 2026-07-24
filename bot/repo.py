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
    options: list[tuple[str, dt.date]],
) -> Poll:
    poll = Poll(chat_id=chat_id, title=title, status="active")
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
