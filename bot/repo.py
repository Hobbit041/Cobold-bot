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
