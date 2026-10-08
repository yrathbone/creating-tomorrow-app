"""Add languages table and resume-header basics on career_profiles

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-08

Additive only: one new table and two new nullable columns. No existing row is
modified; existing career_profiles rows simply have NULL display_name/contact_line.

"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "languages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("career_profile_id", sa.Integer, sa.ForeignKey("career_profiles.id"), nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("proficiency", sa.String, nullable=True),
        sa.Column("source", sa.String, nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column("career_profiles", sa.Column("display_name", sa.String, nullable=True))
    op.add_column("career_profiles", sa.Column("contact_line", sa.String, nullable=True))


def downgrade() -> None:
    op.drop_column("career_profiles", "contact_line")
    op.drop_column("career_profiles", "display_name")
    op.drop_table("languages")
