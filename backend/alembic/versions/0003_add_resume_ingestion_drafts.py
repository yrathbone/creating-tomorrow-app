"""Add resume_ingestion_drafts table

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-29

"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resume_ingestion_drafts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("career_profile_id", sa.Integer, sa.ForeignKey("career_profiles.id"), nullable=False, unique=True),
        sa.Column("analysis_summary", sa.String, nullable=True),
        sa.Column("roles", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("categories", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("history", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("pending_questions", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("discovered_facts", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("round_number", sa.Integer, nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("resume_ingestion_drafts")
