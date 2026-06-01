"""add_metric_events

Revision ID: 20260602_000000
Revises: 20260601_000000
Create Date: 2026-06-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260602_000000"
down_revision = "20260601_000000"
branch_labels = None
depends_on = None


_INDEXES = (
    ("idx_metric_events_occurred_at", ["occurred_at"]),
    ("idx_metric_events_user_time", ["user_id", "occurred_at"]),
    ("idx_metric_events_event_source_time", ["event_type", "source", "occurred_at"]),
    ("idx_metric_events_agent_model_time", ["agent_kind", "provider", "model", "occurred_at"]),
    ("idx_metric_events_status_time", ["status", "occurred_at"]),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "metric_events" not in existing_tables:
        op.create_table(
            "metric_events",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("idempotency_key", sa.String(length=255), nullable=False),
            sa.Column("occurred_at", sa.DateTime(), nullable=False),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("source", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=True),
            sa.Column("owner_scope", sa.String(length=128), nullable=True),
            sa.Column("session_id", sa.String(length=36), nullable=True),
            sa.Column("run_id", sa.String(length=36), nullable=True),
            sa.Column("task_id", sa.String(length=255), nullable=True),
            sa.Column("log_id", sa.String(length=36), nullable=True),
            sa.Column("project_repo_id", sa.String(length=36), nullable=True),
            sa.Column("agent_kind", sa.String(length=32), nullable=True),
            sa.Column("provider", sa.String(length=64), nullable=True),
            sa.Column("model", sa.String(length=128), nullable=True),
            sa.Column("status", sa.String(length=24), nullable=True),
            sa.Column("error_kind", sa.String(length=64), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cache_write_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cost_microusd", sa.Integer(), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("idempotency_key", name="uq_metric_events_idempotency_key"),
        )

    existing_indexes = (
        {index["name"] for index in inspector.get_indexes("metric_events")}
        if "metric_events" in inspector.get_table_names()
        else set()
    )
    for name, columns in _INDEXES:
        if name not in existing_indexes:
            op.create_index(name, "metric_events", columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "metric_events" not in existing_tables:
        return

    existing_indexes = {index["name"] for index in inspector.get_indexes("metric_events")}
    for name, _columns in _INDEXES:
        if name in existing_indexes:
            op.drop_index(name, table_name="metric_events")

    op.drop_table("metric_events")
