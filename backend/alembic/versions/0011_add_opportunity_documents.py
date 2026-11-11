"""Add the opportunity_documents table: the exact approved résumé document for a saved job (C-52 F07)

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-11

Additive only: one new table with a foreign key to opportunities and career_profiles. No existing table, column or row is
changed. Applied by hand only, after the founder's approval. The feature switch CT_OPPORTUNITIES_ENABLED stays off by default.

Downgrade drops the table. Approved documents are lost by design, so take the member's export first.
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "opportunity_documents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("opportunity_id", sa.Integer, sa.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("career_profile_id", sa.Integer, sa.ForeignKey("career_profiles.id"), nullable=False),
        sa.Column("resume_version_id", sa.Integer, sa.ForeignKey("resume_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resume_snapshot", sa.JSON, nullable=False),
        sa.Column("layout", sa.String, nullable=False),
        sa.Column("template", sa.String, nullable=False),
        sa.Column("ats_mode", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("renderer", sa.String, nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("docx", sa.LargeBinary, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("opportunity_id", name="uq_opportunity_documents_opportunity"),
    )
    op.create_index("ix_opportunity_documents_opportunity_id", "opportunity_documents", ["opportunity_id"])
    op.create_index("ix_opportunity_documents_career_profile_id", "opportunity_documents", ["career_profile_id"])


def downgrade() -> None:
    op.drop_index("ix_opportunity_documents_career_profile_id", table_name="opportunity_documents")
    op.drop_index("ix_opportunity_documents_opportunity_id", table_name="opportunity_documents")
    op.drop_table("opportunity_documents")
