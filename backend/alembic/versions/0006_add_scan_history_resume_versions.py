"""Add scan_histories and resume_versions tables

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-30

"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scan_histories",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("career_profile_id", sa.Integer, sa.ForeignKey("career_profiles.id"), nullable=False),
        sa.Column("scan_type", sa.String, nullable=False),
        sa.Column("job_title", sa.String, nullable=True),
        sa.Column("summary_text", sa.String, nullable=False),
        sa.Column("result_data", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "resume_versions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("career_profile_id", sa.Integer, sa.ForeignKey("career_profiles.id"), nullable=False),
        sa.Column("scan_history_id", sa.Integer, sa.ForeignKey("scan_histories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resume_data", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("resume_versions")
    op.drop_table("scan_histories")
