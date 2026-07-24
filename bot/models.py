from __future__ import annotations

import datetime as dt

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Poll(Base):
    __tablename__ = "polls"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int]
    message_id: Mapped[int | None] = mapped_column(default=None)
    title: Mapped[str]
    status: Mapped[str] = mapped_column(default="active")
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)

    options: Mapped[list["Option"]] = relationship(
        back_populates="poll", cascade="all, delete-orphan"
    )


class Option(Base):
    __tablename__ = "options"

    id: Mapped[int] = mapped_column(primary_key=True)
    poll_id: Mapped[int] = mapped_column(ForeignKey("polls.id"))
    text: Mapped[str]
    date: Mapped[dt.date]
    position: Mapped[int]
    is_deleted: Mapped[bool] = mapped_column(default=False)

    poll: Mapped["Poll"] = relationship(back_populates="options")
    votes: Mapped[list["Vote"]] = relationship(
        back_populates="option", cascade="all, delete-orphan"
    )
    threshold_state: Mapped["ThresholdState | None"] = relationship(
        back_populates="option", cascade="all, delete-orphan", uselist=False
    )
    reminder: Mapped["Reminder | None"] = relationship(
        back_populates="option", cascade="all, delete-orphan", uselist=False
    )


class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (UniqueConstraint("option_id", "user_id", name="uq_vote_option_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    option_id: Mapped[int] = mapped_column(ForeignKey("options.id"))
    user_id: Mapped[int]
    username: Mapped[str | None]
    first_name: Mapped[str]
    voted_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)

    option: Mapped["Option"] = relationship(back_populates="votes")


class ThresholdState(Base):
    __tablename__ = "threshold_states"

    option_id: Mapped[int] = mapped_column(ForeignKey("options.id"), primary_key=True)
    announced: Mapped[bool] = mapped_column(default=False)

    option: Mapped["Option"] = relationship(back_populates="threshold_state")


class Reminder(Base):
    __tablename__ = "reminders"

    option_id: Mapped[int] = mapped_column(ForeignKey("options.id"), primary_key=True)
    sent: Mapped[bool] = mapped_column(default=False)

    option: Mapped["Option"] = relationship(back_populates="reminder")
