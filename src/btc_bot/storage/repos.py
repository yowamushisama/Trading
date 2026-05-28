"""Repository layer — all DB writes go through here. Read-back returns ORM objects."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from btc_bot.storage.models import (
    BotState,
    Candle,
    DailyPerformance,
    ExchangeFilterSnapshot,
    NewsItem,
    Order,
    OrderList,
    RiskEvent,
    Signal,
    StrategyRun,
    Trade,
)
from btc_bot.utils.time import utcnow


# ── Candles ───────────────────────────────────────────────────────────────────

def upsert_candle(session: Session, symbol: str, timeframe: str, row: dict) -> Candle:
    """Insert or update a single candle. Deduplicates on (symbol, timeframe, open_time)."""
    existing = (
        session.query(Candle)
        .filter_by(symbol=symbol, timeframe=timeframe, open_time=row["open_time"])
        .first()
    )
    if existing:
        for k, v in row.items():
            setattr(existing, k, v)
        return existing
    candle = Candle(symbol=symbol, timeframe=timeframe, **row)
    session.add(candle)
    return candle


def bulk_upsert_candles(session: Session, symbol: str, timeframe: str, rows: list[dict]) -> int:
    count = 0
    for row in rows:
        upsert_candle(session, symbol, timeframe, row)
        count += 1
    return count


def get_latest_candle_time(session: Session, symbol: str, timeframe: str) -> datetime | None:
    result = (
        session.query(Candle.open_time)
        .filter_by(symbol=symbol, timeframe=timeframe)
        .order_by(Candle.open_time.desc())
        .first()
    )
    return result[0] if result else None


# ── Signals ───────────────────────────────────────────────────────────────────

def save_signal(
    session: Session,
    strategy: str,
    symbol: str,
    timeframe: str,
    side: str,
    entry: float | None,
    stop: float | None,
    target: float | None,
    accepted: bool,
    reason: str = "",
    reject_reason: str = "",
    confidence: float | None = None,
) -> Signal:
    sig = Signal(
        strategy=strategy,
        symbol=symbol,
        timeframe=timeframe,
        ts=utcnow(),
        side=side,
        entry=entry,
        stop=stop,
        target=target,
        confidence=confidence,
        reason=reason,
        accepted=accepted,
        reject_reason=reject_reason if not accepted else None,
    )
    session.add(sig)
    return sig


# ── Orders ────────────────────────────────────────────────────────────────────

def create_order(
    session: Session,
    client_order_id: str,
    symbol: str,
    side: str,
    order_type: str,
    qty: float,
    price: float | None = None,
    parent_list_id: int | None = None,
) -> Order:
    now = utcnow()
    order = Order(
        client_order_id=client_order_id,
        symbol=symbol,
        side=side,
        type=order_type,
        qty=qty,
        qty_filled=0,
        price=price,
        parent_list_id=parent_list_id,
        status="PENDING_LOCAL",
        ts_created=now,
        ts_updated=now,
    )
    session.add(order)
    return order


def update_order_status(
    session: Session,
    client_order_id: str,
    status: str,
    qty_filled: float | None = None,
    exchange_order_id: str | None = None,
    raw: dict | None = None,
) -> Order | None:
    order = session.query(Order).filter_by(client_order_id=client_order_id).first()
    if order is None:
        return None
    order.status = status
    order.ts_updated = utcnow()
    if qty_filled is not None:
        order.qty_filled = qty_filled
    if exchange_order_id:
        order.exchange_order_id = exchange_order_id
    if raw:
        order.raw_json = raw
    return order


def get_order(session: Session, client_order_id: str) -> Order | None:
    return session.query(Order).filter_by(client_order_id=client_order_id).first()


# ── Order Lists ───────────────────────────────────────────────────────────────

def create_order_list(
    session: Session,
    list_client_id: str,
    kind: str,
    raw: dict | None = None,
) -> OrderList:
    now = utcnow()
    ol = OrderList(
        list_client_id=list_client_id,
        kind=kind,
        status="PENDING",
        raw_json=raw,
        created_at=now,
        updated_at=now,
    )
    session.add(ol)
    return ol


# ── Trades ────────────────────────────────────────────────────────────────────

def open_trade(
    session: Session,
    strategy: str,
    symbol: str,
    entry_order_id: int,
    qty: float,
    entry_price: float,
) -> Trade:
    trade = Trade(
        strategy=strategy,
        symbol=symbol,
        entry_order_id=entry_order_id,
        qty=qty,
        entry_price=entry_price,
        opened_at=utcnow(),
    )
    session.add(trade)
    return trade


def close_trade(
    session: Session,
    trade: Trade,
    exit_order_id: int,
    exit_price: float,
    exit_reason: str,
    fees_paid: float,
) -> Trade:
    stop_dist = float(trade.entry_price) - float(trade.entry_price) * 0.015  # fallback
    pnl_usdt = (exit_price - float(trade.entry_price)) * float(trade.qty) - fees_paid
    # pnl_r requires stop distance; stored when available
    trade.exit_order_id = exit_order_id
    trade.exit_price = exit_price
    trade.exit_reason = exit_reason
    trade.pnl_usdt = pnl_usdt
    trade.fees_paid = fees_paid
    trade.closed_at = utcnow()
    return trade


def get_open_trades(session: Session, strategy: str | None = None) -> list[Trade]:
    q = session.query(Trade).filter(Trade.closed_at.is_(None))
    if strategy:
        q = q.filter_by(strategy=strategy)
    return q.all()


# ── Risk Events ───────────────────────────────────────────────────────────────

def log_risk_event(
    session: Session,
    kind: str,
    severity: str,
    payload: dict | None = None,
) -> RiskEvent:
    event = RiskEvent(ts=utcnow(), kind=kind, severity=severity, payload=payload)
    session.add(event)
    return event


# ── Bot State ─────────────────────────────────────────────────────────────────

def set_state(session: Session, key: str, value: dict) -> BotState:
    state = session.query(BotState).filter_by(key=key).first()
    if state:
        state.value = value
        state.updated_at = utcnow()
    else:
        state = BotState(key=key, value=value, updated_at=utcnow())
        session.add(state)
    return state


def get_state(session: Session, key: str) -> dict | None:
    row = session.query(BotState).filter_by(key=key).first()
    return row.value if row else None


# ── Daily Performance ─────────────────────────────────────────────────────────

def upsert_daily_performance(
    session: Session,
    date_str: str,
    starting_equity: float,
    ending_equity: float | None = None,
    pnl: float | None = None,
    trades: int = 0,
    wins: int = 0,
    losses: int = 0,
    max_dd_intraday: float | None = None,
    summary_text: str | None = None,
) -> DailyPerformance:
    row = session.query(DailyPerformance).filter_by(date=date_str).first()
    if row:
        if ending_equity is not None:
            row.ending_equity = ending_equity
        if pnl is not None:
            row.pnl = pnl
        row.trades = trades
        row.wins = wins
        row.losses = losses
        if max_dd_intraday is not None:
            row.max_dd_intraday = max_dd_intraday
        if summary_text:
            row.summary_text = summary_text
        return row
    row = DailyPerformance(
        date=date_str,
        starting_equity=starting_equity,
        ending_equity=ending_equity,
        pnl=pnl,
        trades=trades,
        wins=wins,
        losses=losses,
        max_dd_intraday=max_dd_intraday,
        summary_text=summary_text,
    )
    session.add(row)
    return row


# ── Strategy Runs ─────────────────────────────────────────────────────────────

def start_strategy_run(
    session: Session, strategy: str, mode: str, config_hash: str | None = None
) -> StrategyRun:
    run = StrategyRun(
        strategy=strategy, mode=mode, config_hash=config_hash, started_at=utcnow()
    )
    session.add(run)
    return run


def end_strategy_run(
    session: Session, run: StrategyRun, summary: dict | None = None
) -> StrategyRun:
    run.ended_at = utcnow()
    run.summary = summary
    return run


# ── News Items ────────────────────────────────────────────────────────────────

def upsert_news_item(
    session: Session,
    source: str,
    url: str,
    title: str,
    body: str,
    published_at: datetime | None,
    tags: list[str],
    sentiment_score: float | None,
    tagger: str,
) -> tuple[NewsItem, bool]:
    """Returns (item, is_new)."""
    existing = session.query(NewsItem).filter_by(url=url).first()
    if existing:
        return existing, False
    item = NewsItem(
        source=source,
        url=url,
        title=title,
        body=body,
        published_at=published_at,
        tags=tags,
        sentiment_score=sentiment_score,
        tagger=tagger,
    )
    session.add(item)
    return item, True


def get_recent_high_impact_news(
    session: Session, minutes: int = 60
) -> list[NewsItem]:
    from datetime import timedelta
    cutoff = utcnow() - timedelta(minutes=minutes)
    return (
        session.query(NewsItem)
        .filter(
            NewsItem.published_at >= cutoff,
            NewsItem.sentiment_score < -0.5,
        )
        .all()
    )


# ── Exchange Filters ──────────────────────────────────────────────────────────

def save_exchange_filters(
    session: Session, symbol: str, filters_json: dict
) -> ExchangeFilterSnapshot:
    snap = ExchangeFilterSnapshot(
        symbol=symbol, fetched_at=utcnow(), filters=filters_json
    )
    session.add(snap)
    return snap
