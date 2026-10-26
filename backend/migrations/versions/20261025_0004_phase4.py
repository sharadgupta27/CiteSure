"""phase 4: learning layer

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reading_progress",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("last_page", sa.Integer(), nullable=True),
        sa.Column("pages_read", sa.ARRAY(sa.Integer()), nullable=False),
        sa.Column("percent", sa.Float(), nullable=False),
        sa.Column("last_opened_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("percent >= 0 AND percent <= 100", name=op.f("ck_reading_progress_percent")),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name=op.f("fk_reading_progress_document_id_documents"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_reading_progress_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "document_id", name=op.f("pk_reading_progress")),
    )
    op.create_index("ix_reading_progress_user_opened", "reading_progress", ["user_id", "last_opened_at"], unique=False)

    op.create_table(
        "study_sets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_study_sets_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_study_sets_workspace_id_workspaces"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_study_sets")),
        sa.UniqueConstraint("user_id", "workspace_id", "name", name=op.f("uq_study_sets_user_id")),
    )

    op.create_table(
        "study_set_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("study_set_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("ref_title", sa.String(length=300), nullable=True),
        sa.Column("ref_url", sa.String(length=1000), nullable=True),
        sa.Column("ref_source", sa.String(length=40), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('document','reference')", name=op.f("ck_study_set_items_kind")),
        sa.CheckConstraint(
            "(kind = 'document' AND document_id IS NOT NULL)"
            " OR (kind = 'reference' AND ref_title IS NOT NULL AND ref_url IS NOT NULL)",
            name=op.f("ck_study_set_items_shape"),
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name=op.f("fk_study_set_items_document_id_documents"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["study_set_id"], ["study_sets.id"], name=op.f("fk_study_set_items_study_set_id_study_sets"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_study_set_items")),
        sa.UniqueConstraint("study_set_id", "document_id", name=op.f("uq_study_set_items_study_set_id")),
    )
    op.create_index("ix_study_set_items_set_position", "study_set_items", ["study_set_id", "position"], unique=False)

    op.create_table(
        "learning_plans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("study_set_id", sa.UUID(), nullable=True),
        sa.Column("thread_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("topic", sa.String(length=300), nullable=True),
        sa.Column("hours_per_week", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["study_set_id"], ["study_sets.id"], name=op.f("fk_learning_plans_study_set_id_study_sets"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], name=op.f("fk_learning_plans_thread_id_threads"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_learning_plans_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_learning_plans_workspace_id_workspaces"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learning_plans")),
    )
    op.create_index("ix_learning_plans_user_workspace", "learning_plans", ["user_id", "workspace_id", "created_at"], unique=False)

    op.create_table(
        "learning_plan_steps",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("week", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("label", sa.String(length=300), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("ord_start", sa.Integer(), nullable=False),
        sa.Column("ord_end", sa.Integer(), nullable=False),
        sa.Column("est_minutes", sa.Integer(), nullable=False),
        sa.Column("answer_id", sa.UUID(), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["answer_id"], ["answers.id"], name=op.f("fk_learning_plan_steps_answer_id_answers"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name=op.f("fk_learning_plan_steps_document_id_documents"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["learning_plans.id"], name=op.f("fk_learning_plan_steps_plan_id_learning_plans"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learning_plan_steps")),
    )
    op.create_index("ix_learning_plan_steps_plan_position", "learning_plan_steps", ["plan_id", "position"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_learning_plan_steps_plan_position", table_name="learning_plan_steps")
    op.drop_table("learning_plan_steps")
    op.drop_index("ix_learning_plans_user_workspace", table_name="learning_plans")
    op.drop_table("learning_plans")
    op.drop_index("ix_study_set_items_set_position", table_name="study_set_items")
    op.drop_table("study_set_items")
    op.drop_table("study_sets")
    op.drop_index("ix_reading_progress_user_opened", table_name="reading_progress")
    op.drop_table("reading_progress")
