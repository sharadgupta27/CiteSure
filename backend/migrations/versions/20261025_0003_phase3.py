"""phase 3: open-access full text

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-25
"""
from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fulltext_papers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("paper_key", sa.String(length=300), nullable=False),
        sa.Column("doi", sa.String(length=300), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("label", sa.String(length=600), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("source_host", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fulltext_papers")),
        sa.UniqueConstraint("paper_key", name=op.f("uq_fulltext_papers_paper_key")),
    )
    op.create_table(
        "fulltext_chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("paper_id", sa.UUID(), nullable=False),
        sa.Column("ord", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("heading_path", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=False),
        sa.Column("tsv", postgresql.TSVECTOR(), nullable=False),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["fulltext_papers.id"], name=op.f("fk_fulltext_chunks_paper_id_fulltext_papers"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fulltext_chunks")),
    )
    op.create_index("ix_fulltext_chunks_paper_ord", "fulltext_chunks", ["paper_id", "ord"], unique=False)
    op.create_index("ix_fulltext_chunks_tsv", "fulltext_chunks", ["tsv"], unique=False, postgresql_using="gin")
    op.create_index(
        "ix_fulltext_chunks_embedding_hnsw",
        "fulltext_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_table(
        "fulltext_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("paper_key", sa.String(length=300), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("doi", sa.String(length=300), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("error", sa.String(length=60), nullable=True),
        sa.Column("counted", sa.Boolean(), nullable=False),
        sa.Column("cached", sa.Boolean(), nullable=False),
        sa.Column("paper_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(length=600), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("egress", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('queued','running','ready','failed')", name=op.f("ck_fulltext_requests_status")),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["fulltext_papers.id"], name=op.f("fk_fulltext_requests_paper_id_fulltext_papers"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_fulltext_requests_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_fulltext_requests_workspace_id_workspaces"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fulltext_requests")),
    )
    op.create_index(
        "ix_fulltext_requests_workspace_created", "fulltext_requests", ["workspace_id", "created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_fulltext_requests_workspace_created", table_name="fulltext_requests")
    op.drop_table("fulltext_requests")
    op.drop_index(
        "ix_fulltext_chunks_embedding_hnsw",
        table_name="fulltext_chunks",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_index("ix_fulltext_chunks_tsv", table_name="fulltext_chunks", postgresql_using="gin")
    op.drop_index("ix_fulltext_chunks_paper_ord", table_name="fulltext_chunks")
    op.drop_table("fulltext_chunks")
    op.drop_table("fulltext_papers")
