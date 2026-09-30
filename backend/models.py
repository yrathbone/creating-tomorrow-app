"""
Career Profile data model - still a small, deliberately incomplete subset
of docs/CAREER_PROFILE_ARCHITECTURE_AUDIT.md Section 13's full proposed
schema, grown one vertical slice at a time per that document's locked
sequence (Decision 4: Account -> Career Profile -> Manual CRUD -> Resume
ingestion -> Evidence verification). Account and Career Profile/consent
are live; Experience is the first Manual CRUD entity.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    cognito_sub: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    # Nullable/unset for now - email isn't captured at signup yet
    # (get_current_user() only auto-provisions cognito_sub on a
    # first-seen token; capturing email is separate, not-yet-built work).
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    consent_given_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    career_profile: Mapped["CareerProfile"] = relationship(back_populates="user", uselist=False)


class CareerProfile(Base):
    __tablename__ = "career_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="career_profile")
    experiences: Mapped[list["Experience"]] = relationship(back_populates="career_profile")


class Experience(Base):
    __tablename__ = "experiences"

    id: Mapped[int] = mapped_column(primary_key=True)
    career_profile_id: Mapped[int] = mapped_column(ForeignKey("career_profiles.id"))
    title: Mapped[str] = mapped_column(String)
    organization: Mapped[str] = mapped_column(String)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    # Free-text dates for now (matches resume_builder.py's existing
    # "MM/YY - MM/YY" convention) rather than a Date type - avoids forcing
    # every hand-entered role into a strict calendar date this early.
    start_date: Mapped[str | None] = mapped_column(String, nullable=True)
    end_date: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, default="manual")
    verified: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    career_profile: Mapped["CareerProfile"] = relationship(back_populates="experiences")
