"""
Career Profile data model - still a small, deliberately incomplete subset
of docs/CAREER_PROFILE_ARCHITECTURE_AUDIT.md Section 13's full proposed
schema, grown one vertical slice at a time per that document's locked
sequence (Decision 4: Account -> Career Profile -> Manual CRUD -> Resume
ingestion -> Evidence verification). Account and Career Profile/consent
are live; Experience is the first Manual CRUD entity.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String
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
    education_entries: Mapped[list["Education"]] = relationship(back_populates="career_profile")
    certifications: Mapped[list["Certification"]] = relationship(back_populates="career_profile")
    skills: Mapped[list["Skill"]] = relationship(back_populates="career_profile")


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
    skills: Mapped[list["Skill"]] = relationship(back_populates="experience")


class Skill(Base):
    """A confirmed skill on the Career Profile - deliberately one table,
    not the full Skill/ExperienceSkill split the architecture doc
    describes for a shared canonical taxonomy (Section 13), since that's
    future/Phase 5+ scope this project isn't building yet. Supports both
    ways a skill gets added, per Yovana's own request:
      - tied to a specific role, with source_text capturing HOW it was
        used (experience_id set, source_text set) - including
        non-standard/custom skills that wouldn't be on any pre-built
        list, not just a fixed taxonomy checkbox;
      - a flat addition straight to the general skill list, no story
        required (experience_id and source_text both null).
    """
    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(primary_key=True)
    career_profile_id: Mapped[int] = mapped_column(ForeignKey("career_profiles.id"))
    experience_id: Mapped[int | None] = mapped_column(ForeignKey("experiences.id"), nullable=True)
    name: Mapped[str] = mapped_column(String)
    source_text: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    career_profile: Mapped["CareerProfile"] = relationship(back_populates="skills")
    experience: Mapped["Experience | None"] = relationship(back_populates="skills")


class Education(Base):
    __tablename__ = "education"

    id: Mapped[int] = mapped_column(primary_key=True)
    career_profile_id: Mapped[int] = mapped_column(ForeignKey("career_profiles.id"))
    institution: Mapped[str] = mapped_column(String)
    degree: Mapped[str | None] = mapped_column(String, nullable=True)
    field_of_study: Mapped[str | None] = mapped_column(String, nullable=True)
    graduation_date: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    career_profile: Mapped["CareerProfile"] = relationship(back_populates="education_entries")


class Certification(Base):
    __tablename__ = "certifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    career_profile_id: Mapped[int] = mapped_column(ForeignKey("career_profiles.id"))
    name: Mapped[str] = mapped_column(String)
    issuer: Mapped[str | None] = mapped_column(String, nullable=True)
    date: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    career_profile: Mapped["CareerProfile"] = relationship(back_populates="certifications")


class ResumeIngestionDraft(Base):
    """In-progress resume-upload interview state (roles extracted so far,
    Q&A history, the question batch currently awaiting answers, and any
    discovered facts pending review) - persisted so onboarding is
    resumable across logins/devices, not just within one browser tab's
    memory. One active draft per Career Profile; cleared once the
    candidate saves (career/routes.py's /resume-save) or explicitly
    discards it. Plain JSON (not Postgres-specific JSONB) per Deliverable
    D's "standard Postgres features only, portable migrations" principle.
    """
    __tablename__ = "resume_ingestion_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    career_profile_id: Mapped[int] = mapped_column(ForeignKey("career_profiles.id"), unique=True)
    analysis_summary: Mapped[str | None] = mapped_column(String, nullable=True)
    roles: Mapped[list] = mapped_column(JSON, default=list)
    education: Mapped[list] = mapped_column(JSON, default=list)
    certifications: Mapped[list] = mapped_column(JSON, default=list)
    categories: Mapped[list] = mapped_column(JSON, default=list)
    history: Mapped[list] = mapped_column(JSON, default=list)
    pending_questions: Mapped[list] = mapped_column(JSON, default=list)
    discovered_facts: Mapped[list] = mapped_column(JSON, default=list)
    round_number: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    career_profile: Mapped["CareerProfile"] = relationship()
