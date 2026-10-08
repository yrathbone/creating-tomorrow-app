"""
Career Profile data model - still a small, deliberately incomplete subset
of docs/CAREER_PROFILE_ARCHITECTURE_AUDIT.md Section 13's full proposed
schema, grown one vertical slice at a time per that document's locked
sequence (Decision 4: Account -> Career Profile -> Manual CRUD -> Resume
ingestion -> Evidence verification). Account and Career Profile/consent
are live; Experience is the first Manual CRUD entity.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, text
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
    # Do not ask the database to RETURN server-generated values on INSERT: that would name the
    # migration-0008 columns and break creating a profile on a not-yet-upgraded database.
    __mapper_args__ = {"eager_defaults": False}

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # Resume-header basics (migration 0008). Deferred (never selected unless asked
    # for) and given a server-side NULL default (never inserted unless set), so every
    # existing query and every new CareerProfile row keeps working on a database that
    # has not been upgraded yet; only the /profile routes read or write them.
    display_name: Mapped[str | None] = mapped_column(String, nullable=True, deferred=True, server_default=text("NULL"))
    contact_line: Mapped[str | None] = mapped_column(String, nullable=True, deferred=True, server_default=text("NULL"))

    user: Mapped["User"] = relationship(back_populates="career_profile")
    experiences: Mapped[list["Experience"]] = relationship(back_populates="career_profile")
    education_entries: Mapped[list["Education"]] = relationship(back_populates="career_profile")
    certifications: Mapped[list["Certification"]] = relationship(back_populates="career_profile")
    languages: Mapped[list["Language"]] = relationship(back_populates="career_profile")
    skills: Mapped[list["Skill"]] = relationship(back_populates="career_profile")
    scan_histories: Mapped[list["ScanHistory"]] = relationship(back_populates="career_profile")
    resume_versions: Mapped[list["ResumeVersion"]] = relationship(back_populates="career_profile")


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


class Language(Base):
    """A spoken/written language on the Career Profile (migration 0008). Free-text
    proficiency, e.g. "Native", "Professional working proficiency"."""
    __tablename__ = "languages"

    id: Mapped[int] = mapped_column(primary_key=True)
    career_profile_id: Mapped[int] = mapped_column(ForeignKey("career_profiles.id"))
    name: Mapped[str] = mapped_column(String)
    proficiency: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    career_profile: Mapped["CareerProfile"] = relationship(back_populates="languages")


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


class ScanHistory(Base):
    """A persisted record that a job-comparison or skill scan actually ran,
    and what it found - deliberately one table with a scan_type
    discriminator ("job_comparison" | "skill_scan"), not a
    JobComparisonHistory/SkillScanHistory split, same reasoning Skill
    already applies to its own would-be Skill/ExperienceSkill split
    (Section 13 of the architecture doc is future/Phase 5+ scope this
    project isn't building yet). result_data is a JSON blob rather than
    many nullable specific columns because each scan_type's result is a
    different, variable shape, read back whole for display and never
    queried by field - the same tradeoff the architecture doc calls out
    for its own (unbuilt) JobAnalysis.match_detail. job_title is its own
    column (not buried in result_data) since list views need it without
    unpacking JSON - nullable since it's only ever populated for
    scan_type == "job_comparison".
    """
    __tablename__ = "scan_histories"

    id: Mapped[int] = mapped_column(primary_key=True)
    career_profile_id: Mapped[int] = mapped_column(ForeignKey("career_profiles.id"))
    scan_type: Mapped[str] = mapped_column(String)  # "job_comparison" | "skill_scan"
    job_title: Mapped[str | None] = mapped_column(String, nullable=True)
    summary_text: Mapped[str] = mapped_column(String)
    result_data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    career_profile: Mapped["CareerProfile"] = relationship(back_populates="scan_histories")
    resume_versions: Mapped[list["ResumeVersion"]] = relationship(back_populates="scan_history")


class ResumeVersion(Base):
    """A resume actually built through the Career Profile - created the
    moment build_tailored_resume() (career/job_match.py) returns, not
    gated on the candidate ever clicking Download, so "what did I build
    last month" survives a refresh/navigate-away the way the transient
    job-build-resume flow never could on its own. resume_data is plain
    JSON (not Postgres-specific JSONB) in exactly the shape
    resume_builder.py's build_resume_bytes() already consumes, matching
    ResumeIngestionDraft's own "standard Postgres features only, portable
    migrations" choice - so a later download re-runs no AI call, it just
    reformats the stored data. scan_history_id is nullable because a
    resume built through this flow is still worth keeping even without a
    job-comparison run behind it; when present, it links back to the
    job_comparison ScanHistory row this resume was tailored for.
    """
    __tablename__ = "resume_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    career_profile_id: Mapped[int] = mapped_column(ForeignKey("career_profiles.id"))
    scan_history_id: Mapped[int | None] = mapped_column(ForeignKey("scan_histories.id"), nullable=True)
    resume_data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    career_profile: Mapped["CareerProfile"] = relationship(back_populates="resume_versions")
    scan_history: Mapped["ScanHistory | None"] = relationship(back_populates="resume_versions")


class Application(Base):
    """A job the candidate says they actually applied for - a simple tracker
    they come back to and update (no response, interview, rejection, offer).
    Entered by the candidate (the app can't know they applied), usually from
    the finished-resume screen; scan_history_id / resume_version_id link back
    to the comparison and resume it came from when there is one (nullable:
    an application can also be added by hand). applied_on is an ISO
    "YYYY-MM-DD" string from a date input, matching how this codebase
    already stores dates as text.
    """
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    career_profile_id: Mapped[int] = mapped_column(ForeignKey("career_profiles.id"))
    scan_history_id: Mapped[int | None] = mapped_column(ForeignKey("scan_histories.id", ondelete="SET NULL"), nullable=True)
    resume_version_id: Mapped[int | None] = mapped_column(ForeignKey("resume_versions.id", ondelete="SET NULL"), nullable=True)
    job_title: Mapped[str] = mapped_column(String)
    company: Mapped[str | None] = mapped_column(String, nullable=True)
    applied_on: Mapped[str] = mapped_column(String)  # YYYY-MM-DD
    status: Mapped[str] = mapped_column(String, default="applied")  # applied | no_response | interview | rejected | offer
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    status_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
