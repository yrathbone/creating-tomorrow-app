"""Add job discovery pilot tables: job_postings (shared, system-owned) and job_preferences (one per career profile)

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-12

LOCAL AND TEST ONLY until the founder approves a production migration separately. Additive only: two new tables, no change to
any existing table, column or row. job_postings holds NO member data and NO third-party description text: only the metadata
listed in the model. job_preferences holds one member's own confirmed preferences, with a foreign key to career_profiles.

Downgrade drops both tables. Postings and preferences are lost by design; the pilot stores nothing a member did not confirm.
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

SOURCES = ("greenhouse", "ashby")
ARRANGEMENTS = ("remote", "hybrid", "on_site")


def upgrade() -> None:
    op.create_table(
        "job_postings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("board_token", sa.String(100), nullable=False),
        sa.Column("source_job_id", sa.String(200), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("company", sa.String(200), nullable=False),
        sa.Column("location_text", sa.String(300), nullable=True),
        sa.Column("work_arrangement", sa.String(20), nullable=True),
        sa.Column("employment_type", sa.String(30), nullable=True),
        sa.Column("job_url", sa.String(2000), nullable=False),
        sa.Column("url_hash", sa.String(64), nullable=False),
        sa.Column("first_seen_on", sa.Date, nullable=False),
        sa.Column("last_seen_on", sa.Date, nullable=False),
        sa.Column("closed_on", sa.Date, nullable=True),
        sa.Column("missing_on", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source", "board_token", "source_job_id", name="uq_job_postings_board_job"),
        sa.UniqueConstraint("url_hash", name="uq_job_postings_url_hash"),
        sa.CheckConstraint("source IN ('greenhouse', 'ashby')", name="ck_job_postings_source"),
        sa.CheckConstraint(
            "work_arrangement IS NULL OR work_arrangement IN ('remote', 'hybrid', 'on_site')",
            name="ck_job_postings_work_arrangement",
        ),
        sa.CheckConstraint("last_seen_on >= first_seen_on", name="ck_job_postings_seen_order"),
    )
    op.create_index("ix_job_postings_open", "job_postings", ["closed_on"])

    op.create_table(
        "job_preferences",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("career_profile_id", sa.Integer, sa.ForeignKey("career_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_titles", sa.JSON, nullable=False),
        sa.Column("locations", sa.JSON, nullable=False),
        sa.Column("remote_ok", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("onsite_ok", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("employment_types", sa.JSON, nullable=False),
        sa.Column("min_base", sa.Integer, nullable=True),
        sa.Column("exclude_words", sa.JSON, nullable=False),
        sa.Column("followed_boards", sa.JSON, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("career_profile_id", name="uq_job_preferences_profile"),
        sa.CheckConstraint("min_base IS NULL OR min_base >= 0", name="ck_job_preferences_min_base"),
    )


def downgrade() -> None:
    op.drop_table("job_preferences")
    op.drop_index("ix_job_postings_open", table_name="job_postings")
    op.drop_table("job_postings")
