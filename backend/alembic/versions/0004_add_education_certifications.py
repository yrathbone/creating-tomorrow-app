"""Add education and certifications tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-29

"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("resume_ingestion_drafts", sa.Column("education", sa.JSON, nullable=False, server_default="[]"))
    op.add_column("resume_ingestion_drafts", sa.Column("certifications", sa.JSON, nullable=False, server_default="[]"))

    op.create_table(
        "education",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("career_profile_id", sa.Integer, sa.ForeignKey("career_profiles.id"), nullable=False),
        sa.Column("institution", sa.String, nullable=False),
        sa.Column("degree", sa.String, nullable=True),
        sa.Column("field_of_study", sa.String, nullable=True),
        sa.Column("graduation_date", sa.String, nullable=True),
        sa.Column("source", sa.String, nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "certifications",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("career_profile_id", sa.Integer, sa.ForeignKey("career_profiles.id"), nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("issuer", sa.String, nullable=True),
        sa.Column("date", sa.String, nullable=True),
        sa.Column("source", sa.String, nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("certifications")
    op.drop_table("education")
    op.drop_column("resume_ingestion_drafts", "certifications")
    op.drop_column("resume_ingestion_drafts", "education")
