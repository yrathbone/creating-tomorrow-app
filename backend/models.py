"""
Career Profile data model - first slice only (User, CareerProfile).

See docs/CAREER_PROFILE_ARCHITECTURE_AUDIT.md Section 13 for the full
proposed schema this is deliberately a small, verified-working subset of.
Not yet backing any route - real signup (populating cognito_sub) waits on
the Account phase of that document's locked sequence (Decision 4: Account
-> Career Profile -> Manual CRUD -> Resume ingestion -> Evidence
verification).
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Nullable for now - no Cognito integration yet (Decision 1). Stays
    # unique so the real signup flow can populate it later without a
    # schema change.
    cognito_sub: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
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
