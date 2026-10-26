"""phase 2: annotations and inbox

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "annotations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("rects", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.Column("color", sa.String(length=10), server_default="yellow", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("color IN ('yellow','green','blue','pink','orange')", name=op.f("ck_annotations_color")),
        sa.CheckConstraint("page >= 1", name=op.f("ck_annotations_page")),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_annotations_document_id_documents"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_annotations_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_annotations")),
    )
    op.create_index("ix_annotations_document_user", "annotations", ["document_id", "user_id"], unique=False)

    op.create_table(
        "inbox_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("collection_id", sa.UUID(), nullable=True),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("source_key", sa.String(length=1000), nullable=False),
        sa.Column("folder", sa.String(length=600), nullable=False),
        sa.Column("filename", sa.String(length=300), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mtime_ns", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('imported','duplicate','quarantined','failed')", name=op.f("ck_inbox_items_status")),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_inbox_items_workspace_id_workspaces"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["collections.id"], name=op.f("fk_inbox_items_collection_id_collections"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_inbox_items_document_id_documents"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inbox_items")),
    )
    op.create_index("ix_inbox_items_workspace_created", "inbox_items", ["workspace_id", "created_at"], unique=False)
    op.create_index("ix_inbox_items_source", "inbox_items", ["source_key", "size_bytes", "mtime_ns"], unique=False)

    op.create_table(
        "inbox_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("last_scan_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scan_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_counts", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.CheckConstraint("id = 1", name=op.f("ck_inbox_state_single_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inbox_state")),
    )


def downgrade() -> None:
    op.drop_table("inbox_state")
    op.drop_index("ix_inbox_items_source", table_name="inbox_items")
    op.drop_index("ix_inbox_items_workspace_created", table_name="inbox_items")
    op.drop_table("inbox_items")
    op.drop_index("ix_annotations_document_user", table_name="annotations")
    op.drop_table("annotations")
