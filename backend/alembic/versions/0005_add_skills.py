"""Add skills table

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-30

"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("career_profile_id", sa.Integer, sa.ForeignKey("career_profiles.id"), nullable=False),
        sa.Column("experience_id", sa.Integer, sa.ForeignKey("experiences.id"), nullable=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("source_text", sa.String, nullable=True),
        sa.Column("source", sa.String, nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("skills")
