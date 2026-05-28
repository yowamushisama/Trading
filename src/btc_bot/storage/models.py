"""SQLAlchemy ORM models for all 11 tables. UTC everywhere, NUMERIC(20,8) for crypto."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


PRICE = Numeric(20, 8)
QTY = Numeric(20, 8)


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "open_time"),
        Index("ix_candles_symbol_tf_time", "symbol", "timeframe", "open_time"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[float] = mapped_column(PRICE, nullable=False)
    high: Mapped[float] = mapped_column(PRICE, nullable=False)
    low: Mapped[float] = mapped_column(PRICE, nullable=False)
    close: Mapped[float] = mapped_column(PRICE, nullable=False)
    volume: Mapped[float] = mapped_column(PRICE, nullable=False)
    closed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (Index("ix_signals_strategy_ts", "strategy", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    strategy: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # long | short
    entry: Mapped[float] = mapped_column(PRICE, nullable=True)
    stop: Mapped[float] = mapped_column(PRICE, nullable=True)
    target: Mapped[float] = mapped_column(PRICE, nullable=True)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=True)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reject_reason: Mapped[str] = mapped_column(Text, nullable=True)


class OrderList(Base):
    """Tracks linked protective order groups (OCO / OTO / OTOCO)."""
    __tablename__ = "order_lists"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    list_client_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    exchange_list_id: Mapped[str] = mapped_column(String(100), nullable=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # OCO | OTO | OTOCO
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    orders: Mapped[list[Order]] = relationship("Order", back_populates="order_list")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_status", "status"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_order_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    exchange_order_id: Mapped[str] = mapped_column(String(100), nullable=True)
    parent_list_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("order_lists.id"), nullable=True
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    qty: Mapped[float] = mapped_column(QTY, nullable=False)
    qty_filled: Mapped[float] = mapped_column(QTY, nullable=False, default=0)
    price: Mapped[float] = mapped_column(PRICE, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING_LOCAL")
    ts_created: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ts_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=True)

    order_list: Mapped[OrderList | None] = relationship("OrderList", back_populates="orders")


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (Index("ix_trades_strategy_opened", "strategy", "opened_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    strategy: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    entry_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id"), nullable=False
    )
    exit_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id"), nullable=True
    )
    qty: Mapped[float] = mapped_column(QTY, nullable=False)
    entry_price: Mapped[float] = mapped_column(PRICE, nullable=False)
    exit_price: Mapped[float] = mapped_column(PRICE, nullable=True)
    pnl_usdt: Mapped[float] = mapped_column(Numeric(20, 8), nullable=True)
    pnl_r: Mapped[float] = mapped_column(Numeric(10, 4), nullable=True)
    fees_paid: Mapped[float] = mapped_column(Numeric(20, 8), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_reason: Mapped[str] = mapped_column(String(50), nullable=True)


class RiskEvent(Base):
    __tablename__ = "risk_events"
    __table_args__ = (Index("ix_risk_events_ts", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)  # info|warn|critical
    payload: Mapped[dict] = mapped_column(JSON, nullable=True)


class BotState(Base):
    __tablename__ = "bot_state"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DailyPerformance(Base):
    __tablename__ = "daily_performance"

    date: Mapped[str] = mapped_column(String(10), primary_key=True)  # YYYY-MM-DD
    starting_equity: Mapped[float] = mapped_column(PRICE, nullable=False)
    ending_equity: Mapped[float] = mapped_column(PRICE, nullable=True)
    pnl: Mapped[float] = mapped_column(Numeric(20, 8), nullable=True)
    trades: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    max_dd_intraday: Mapped[float] = mapped_column(Numeric(10, 6), nullable=True)
    summary_text: Mapped[str] = mapped_column(Text, nullable=True)


class StrategyRun(Base):
    __tablename__ = "strategy_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    strategy: Mapped[str] = mapped_column(String(50), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, nullable=True)


class NewsItem(Base):
    __tablename__ = "news_items"
    __table_args__ = (Index("ix_news_published", "published_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=True)
    sentiment_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=True)
    tagger: Mapped[str] = mapped_column(String(20), nullable=True)  # keyword | llm


class ExchangeFilterSnapshot(Base):
    __tablename__ = "exchange_filters_snapshot"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    filters: Mapped[dict] = mapped_column(JSON, nullable=False)

    __table_args__ = (Index("ix_exchange_filters_symbol", "symbol"),)
