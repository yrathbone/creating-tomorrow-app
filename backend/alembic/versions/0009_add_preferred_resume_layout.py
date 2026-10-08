"""Add the preferred resume layout to career_profiles

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-08

Additive only: one new nullable column. No existing row is modified; existing profiles simply
have NULL, which means "Classic".

"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("career_profiles", sa.Column("preferred_resume_layout", sa.String, nullable=True))


def downgrade() -> None:
    op.drop_column("career_profiles", "preferred_resume_layout")
