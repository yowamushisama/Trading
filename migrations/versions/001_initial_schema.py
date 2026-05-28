"""Initial schema — all 11 tables.

Revision ID: 001
Revises:
Create Date: 2026-05-28
"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "candles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("timeframe", sa.String(10), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(20, 8), nullable=False),
        sa.Column("high", sa.Numeric(20, 8), nullable=False),
        sa.Column("low", sa.Numeric(20, 8), nullable=False),
        sa.Column("close", sa.Numeric(20, 8), nullable=False),
        sa.Column("volume", sa.Numeric(20, 8), nullable=False),
        sa.Column("closed", sa.Boolean(), nullable=False, server_default="true"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "timeframe", "open_time", name="uq_candles_symbol_tf_time"),
    )
    op.create_index("ix_candles_symbol_tf_time", "candles", ["symbol", "timeframe", "open_time"])

    op.create_table(
        "signals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("strategy", sa.String(50), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("timeframe", sa.String(10), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("entry", sa.Numeric(20, 8), nullable=True),
        sa.Column("stop", sa.Numeric(20, 8), nullable=True),
        sa.Column("target", sa.Numeric(20, 8), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_signals_strategy_ts", "signals", ["strategy", "ts"])

    op.create_table(
        "order_lists",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("list_client_id", sa.String(100), nullable=False),
        sa.Column("exchange_list_id", sa.String(100), nullable=True),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="PENDING"),
        sa.Column("raw_json", postgresql.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("list_client_id", name="uq_order_lists_list_client_id"),
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("client_order_id", sa.String(100), nullable=False),
        sa.Column("exchange_order_id", sa.String(100), nullable=True),
        sa.Column("parent_list_id", sa.BigInteger(), sa.ForeignKey("order_lists.id"), nullable=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("qty", sa.Numeric(20, 8), nullable=False),
        sa.Column("qty_filled", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("price", sa.Numeric(20, 8), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="PENDING_LOCAL"),
        sa.Column("ts_created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ts_updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_json", postgresql.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_order_id", name="uq_orders_client_order_id"),
    )
    op.create_index("ix_orders_status", "orders", ["status"])

    op.create_table(
        "trades",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("strategy", sa.String(50), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("entry_order_id", sa.BigInteger(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("exit_order_id", sa.BigInteger(), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("qty", sa.Numeric(20, 8), nullable=False),
        sa.Column("entry_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("exit_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("pnl_usdt", sa.Numeric(20, 8), nullable=True),
        sa.Column("pnl_r", sa.Numeric(10, 4), nullable=True),
        sa.Column("fees_paid", sa.Numeric(20, 8), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_reason", sa.String(50), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trades_strategy_opened", "trades", ["strategy", "opened_at"])

    op.create_table(
        "risk_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("payload", postgresql.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_risk_events_ts", "risk_events", ["ts"])

    op.create_table(
        "bot_state",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", postgresql.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_table(
        "daily_performance",
        sa.Column("date", sa.String(10), primary_key=True),
        sa.Column("starting_equity", sa.Numeric(20, 8), nullable=False),
        sa.Column("ending_equity", sa.Numeric(20, 8), nullable=True),
        sa.Column("pnl", sa.Numeric(20, 8), nullable=True),
        sa.Column("trades", sa.Integer(), server_default="0"),
        sa.Column("wins", sa.Integer(), server_default="0"),
        sa.Column("losses", sa.Integer(), server_default="0"),
        sa.Column("max_dd_intraday", sa.Numeric(10, 6), nullable=True),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("date"),
    )

    op.create_table(
        "strategy_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("strategy", sa.String(50), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", postgresql.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "news_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("sentiment_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("tagger", sa.String(20), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url", name="uq_news_items_url"),
    )
    op.create_index("ix_news_published", "news_items", ["published_at"])

    op.create_table(
        "exchange_filters_snapshot",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("filters", postgresql.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_exchange_filters_symbol", "exchange_filters_snapshot", ["symbol"])


def downgrade() -> None:
    op.drop_table("exchange_filters_snapshot")
    op.drop_table("news_items")
    op.drop_table("strategy_runs")
    op.drop_table("daily_performance")
    op.drop_table("bot_state")
    op.drop_table("risk_events")
    op.drop_table("trades")
    op.drop_table("orders")
    op.drop_table("order_lists")
    op.drop_table("signals")
    op.drop_table("candles")
