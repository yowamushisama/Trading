"""Add macro_news_scores and macro_news_inputs tables.

Revision ID: 002
Revises: 001
Create Date: 2026-05-28
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "macro_news_scores",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("computed_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("final_score", sa.Numeric(4, 3), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=False),
        sa.Column("subscores", postgresql.JSON(), nullable=True),
        sa.Column("drivers", postgresql.JSON(), nullable=True),
        sa.Column("rates_snapshot", postgresql.JSON(), nullable=True),
        sa.Column("top_headlines", postgresql.JSON(), nullable=True),
        sa.Column("gdelt_summary", postgresql.JSON(), nullable=True),
        sa.Column("etf_summary", postgresql.JSON(), nullable=True),
        sa.Column("calendar_summary", postgresql.JSON(), nullable=True),
        sa.Column("llm_provider", sa.String(50), nullable=True),
        sa.Column("llm_model", sa.String(100), nullable=True),
        sa.Column("llm_prompt_hash", sa.String(32), nullable=True),
        sa.Column("llm_raw_response", sa.Text(), nullable=True),
        sa.Column("score_schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_macro_news_scores_computed_at", "macro_news_scores", ["computed_at_utc"])

    op.create_table(
        "macro_news_inputs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("score_id", sa.BigInteger(),
                  sa.ForeignKey("macro_news_scores.id"), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSON(), nullable=True),
        sa.Column("fetch_ok", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("macro_news_inputs")
    op.drop_table("macro_news_scores")
