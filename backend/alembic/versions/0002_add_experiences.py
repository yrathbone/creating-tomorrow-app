"""Add experiences table

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29

"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experiences",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("career_profile_id", sa.Integer, sa.ForeignKey("career_profiles.id"), nullable=False),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("organization", sa.String, nullable=False),
        sa.Column("location", sa.String, nullable=True),
        sa.Column("start_date", sa.String, nullable=True),
        sa.Column("end_date", sa.String, nullable=True),
        sa.Column("description", sa.String, nullable=True),
        sa.Column("source", sa.String, nullable=False, server_default="manual"),
        sa.Column("verified", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("experiences")
