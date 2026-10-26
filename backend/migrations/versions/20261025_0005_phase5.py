"""phase 5: audit, OIDC identities, vault

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("actor_email", sa.String(length=320), nullable=True),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("target", sa.String(length=200), nullable=True),
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
        sa.UniqueConstraint("seq", name=op.f("uq_audit_log_seq")),
    )
    op.create_index("ix_audit_log_workspace_seq", "audit_log", ["workspace_id", "seq"], unique=False)
    op.create_index("ix_audit_log_actor_seq", "audit_log", ["actor_id", "seq"], unique=False)
    op.create_index("ix_audit_log_action_seq", "audit_log", ["action", "seq"], unique=False)
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"], unique=False)

    # Append-only at the database: even the application's own role cannot rewrite history. Retention (deleting old
    # rows) is a deliberate operator action: see docs/audit-dashboard.md.
    op.execute(
        """
        CREATE FUNCTION audit_log_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only (% not allowed)', TG_OP USING ERRCODE = 'insufficient_privilege';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER audit_log_no_update_delete BEFORE UPDATE OR DELETE ON audit_log "
        "FOR EACH ROW EXECUTE FUNCTION audit_log_append_only()"
    )
    op.execute(
        "CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_log_append_only()"
    )

    op.create_table(
        "oidc_identities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("issuer", sa.String(length=300), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_oidc_identities_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oidc_identities")),
        sa.UniqueConstraint("issuer", "subject", name=op.f("uq_oidc_identities_issuer")),
    )
    op.create_index(op.f("ix_oidc_identities_user_id"), "oidc_identities", ["user_id"], unique=False)

    op.create_table(
        "oidc_group_grants",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], name=op.f("fk_oidc_group_grants_group_id_groups"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_oidc_group_grants_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "group_id", name=op.f("pk_oidc_group_grants")),
    )


def downgrade() -> None:
    op.drop_table("oidc_group_grants")
    op.drop_index(op.f("ix_oidc_identities_user_id"), table_name="oidc_identities")
    op.drop_table("oidc_identities")
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log")
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_update_delete ON audit_log")
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_index("ix_audit_log_action_seq", table_name="audit_log")
    op.drop_index("ix_audit_log_actor_seq", table_name="audit_log")
    op.drop_index("ix_audit_log_workspace_seq", table_name="audit_log")
    op.drop_table("audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_append_only()")
