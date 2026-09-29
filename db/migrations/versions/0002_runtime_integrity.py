"""Runtime aggregates, retry scheduling, and tenant-safe references."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Revision 0001 in the initial MVP used Base.metadata.create_all(). These
    # guards keep a fresh install safe while still upgrading databases created
    # before these runtime-integrity fields existed.
    inspector = sa.inspect(op.get_bind())
    columns = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in ("users", "sync_jobs", "user_daily_features")
    }
    additions = {
        "users": [sa.Column("is_mfa_capable", sa.Boolean(), nullable=False, server_default=sa.true())],
        "sync_jobs": [
            sa.Column(
                "next_attempt_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        ],
        "user_daily_features": [
            sa.Column("external_sender_ratio", sa.Float(), nullable=False, server_default="0"),
            sa.Column("suspicious_header_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sender_domain_novelty", sa.Float(), nullable=False, server_default="0"),
            sa.Column(
                "feature_version",
                sa.String(length=40),
                nullable=False,
                server_default="UserDailyFeaturesV1",
            ),
            sa.Column(
                "calculated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        ],
    }
    for table, candidates in additions.items():
        for column in candidates:
            if column.name not in columns[table]:
                op.add_column(table, column)

    existing_indexes = {
        table: {index["name"] for index in inspector.get_indexes(table)}
        for table in ("user_daily_features", "feedback")
    }
    if "ix_user_daily_tenant_user_day" not in existing_indexes["user_daily_features"]:
        op.create_index(
            "ix_user_daily_tenant_user_day",
            "user_daily_features",
            ["tenant_id", "user_id", "day"],
        )
    if "ix_feedback_tenant_risk_created" not in existing_indexes["feedback"]:
        op.create_index(
            "ix_feedback_tenant_risk_created",
            "feedback",
            ["tenant_id", "risk_id", "created_at"],
        )

    def has_foreign_key(table: str, constrained: list[str], referred: str) -> bool:
        return any(
            item["constrained_columns"] == constrained and item["referred_table"] == referred
            for item in inspector.get_foreign_keys(table)
        )

    foreign_keys = [
        ("fk_email_features_tenant_user", "email_features", "users", ["tenant_id", "user_id"], ["tenant_id", "id"]),
        ("fk_user_daily_tenant_user", "user_daily_features", "users", ["tenant_id", "user_id"], ["tenant_id", "id"]),
        ("fk_risk_scores_tenant_user", "risk_scores", "users", ["tenant_id", "user_id"], ["tenant_id", "id"]),
        ("fk_feedback_tenant_risk", "feedback", "risk_scores", ["tenant_id", "risk_id"], ["tenant_id", "id"]),
    ]
    for name, table, referred, local_columns, remote_columns in foreign_keys:
        if not has_foreign_key(table, local_columns, referred):
            op.create_foreign_key(
                name,
                table,
                referred,
                local_columns,
                remote_columns,
                ondelete="CASCADE",
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    targets = [
        ("feedback", ["tenant_id", "risk_id"], "risk_scores"),
        ("risk_scores", ["tenant_id", "user_id"], "users"),
        ("user_daily_features", ["tenant_id", "user_id"], "users"),
        ("email_features", ["tenant_id", "user_id"], "users"),
    ]
    for table, columns, referred in targets:
        for foreign_key in inspector.get_foreign_keys(table):
            if (
                foreign_key["constrained_columns"] == columns
                and foreign_key["referred_table"] == referred
                and foreign_key["name"]
            ):
                op.drop_constraint(foreign_key["name"], table, type_="foreignkey")
                break
    indexes = {
        table: {index["name"] for index in inspector.get_indexes(table)}
        for table in ("feedback", "user_daily_features")
    }
    if "ix_feedback_tenant_risk_created" in indexes["feedback"]:
        op.drop_index("ix_feedback_tenant_risk_created", table_name="feedback")
    if "ix_user_daily_tenant_user_day" in indexes["user_daily_features"]:
        op.drop_index("ix_user_daily_tenant_user_day", table_name="user_daily_features")
    user_daily_columns = {
        column["name"] for column in inspector.get_columns("user_daily_features")
    }
    for column in (
        "calculated_at",
        "feature_version",
        "sender_domain_novelty",
        "suspicious_header_count",
        "external_sender_ratio",
    ):
        if column in user_daily_columns:
            op.drop_column("user_daily_features", column)
    if "next_attempt_at" in {column["name"] for column in inspector.get_columns("sync_jobs")}:
        op.drop_column("sync_jobs", "next_attempt_at")
    if "is_mfa_capable" in {column["name"] for column in inspector.get_columns("users")}:
        op.drop_column("users", "is_mfa_capable")
