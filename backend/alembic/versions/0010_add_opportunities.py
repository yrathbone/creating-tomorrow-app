"""Add the opportunities table (My Opportunities, C-52 MVP-0)

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-09

Additive only: one new table. No existing table, column or row is changed. Applied by hand only, after Data's review and the
founder's approval. The feature switch CT_OPPORTUNITIES_ENABLED stays off by default, so applying this migration alone changes
nothing for members.

Downgrade drops the table; saved links are lost by design, so take the member's export first.
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "opportunities",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("career_profile_id", sa.Integer, sa.ForeignKey("career_profiles.id"), nullable=False),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("employer", sa.String, nullable=True),
        sa.Column("job_url", sa.String, nullable=False),
        sa.Column("dedupe_key", sa.String(64), nullable=False),
        sa.Column("location_text", sa.String, nullable=True),
        sa.Column("work_arrangement", sa.String, nullable=True),
        sa.Column("employment_type", sa.String, nullable=True),
        sa.Column("base_min", sa.Integer, nullable=True),
        sa.Column("base_max", sa.Integer, nullable=True),
        sa.Column("base_period", sa.String, nullable=True),
        sa.Column("pay_note", sa.String, nullable=True),
        sa.Column("state", sa.String, nullable=False, server_default="saved"),
        sa.Column("dismiss_reason", sa.String, nullable=True),
        sa.Column("last_verified_on", sa.String, nullable=True),
        sa.Column("notes", sa.String, nullable=True),
        sa.Column("application_id", sa.Integer, sa.ForeignKey("applications.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_resume_version_id", sa.Integer, sa.ForeignKey("resume_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_resume_hash", sa.String(64), nullable=True),
        sa.Column("follow_up_on", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("career_profile_id", "dedupe_key", name="uq_opportunities_profile_dedupe"),
    )
    op.create_index("ix_opportunities_career_profile_id", "opportunities", ["career_profile_id"])


def downgrade() -> None:
    op.drop_index("ix_opportunities_career_profile_id", table_name="opportunities")
    op.drop_table("opportunities")
