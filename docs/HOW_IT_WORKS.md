# How the BTC Trading Bot Works
### A complete technical reference

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Scalping — Short-Duration Trades (minutes to hours)](#2-scalping--short-duration-trades-minutes-to-hours)
3. [Swing Trading — Long-Duration Trades (days to weeks)](#3-swing-trading--long-duration-trades-days-to-weeks)
4. [How Trade Amounts Are Determined](#4-how-trade-amounts-are-determined)
5. [How Stop Losses Are Set](#5-how-stop-losses-are-set)
6. [The Risk Engine — 14 Gates Every Trade Must Pass](#6-the-risk-engine--14-gates-every-trade-must-pass)
7. [How the LLM Is Used](#7-how-the-llm-is-used)
8. [How News Is Converted Into Trading Signals](#8-how-news-is-converted-into-trading-signals)
9. [How Both Strategies Share the Same Account](#9-how-both-strategies-share-the-same-account)
10. [Order Execution and Protection](#10-order-execution-and-protection)
11. [What Gets Stored in the Database](#11-what-gets-stored-in-the-database)
12. [Changing Parameters](#12-changing-parameters)

---

## 1. System Overview

The bot runs two independent strategies simultaneously — a **scalper** for short moves and a **swing trader** for multi-day positions — but they share one account and one risk engine. Every signal either passes all 14 risk gates and becomes a live order, or it is rejected and the rejection is logged with an explanation.

```
Live BTC/USDT candles (Binance REST)
         │
         ▼
┌─────────────────┐    ┌─────────────────┐
│  ScalperStrategy │    │  SwingStrategy  │
│  5m/15m/1H      │    │  4H/1D/1W       │
└────────┬────────┘    └────────┬────────┘
         │                      │
         ▼                      ▼
       Signal?               Signal?
         │                      │
         └──────────┬───────────┘
                    ▼
            ┌──────────────┐
            │  RiskEngine  │  ← 14 gates checked in order
            │  (shared)    │
            └──────┬───────┘
                   │
         ┌─────────┴─────────┐
         │                   │
      REJECTED             ALLOWED
         │                   │
    Log to DB          Calculate size
    LLM explains       Place OTOCO order
                       Log to DB
```

The bot only takes **long (buy) trades** in Spot mode. Short selling requires futures, which is designed but disabled by default.

---

## 2. Scalping — Short-Duration Trades (minutes to hours)

**File:** `src/btc_bot/strategy/scalper.py`

### What it targets
Quick momentum moves on Bitcoin — typically lasting **30 minutes to 4 hours**. It buys when price is breaking out or pulling back in the direction of the larger trend, with volume confirming real interest.

### Three-timeframe structure

The scalper uses three candle timeframes simultaneously. All three must agree before a trade fires.

```
1H candle   →  Is the hourly trend going up?         (Regime filter)
   └─ YES
      │
15m candle  →  Is momentum building on 15 minutes?   (Confirmation)
      └─ YES
         │
5m candle   →  Is there a specific entry right now?  (Execution trigger)
```

### Step 1 — 1H Regime Gate

Checked in `strategy/regime.py`:

| Condition | What it checks | Why |
|---|---|---|
| `close > EMA(200, 1H)` | BTC price is above its 200-period hourly moving average | Only trade longs when the trend is up |
| `ATR%(14) between 0.4% and 2.5%` | Volatility is in a normal range | Below 0.4% = dead, sideways chop. Above 2.5% = panic/spike, unpredictable |
| `ADX ≥ 25` | The trend has enough directional strength | Weak ADX means ranging, not trending |

If the 1H regime is not `trend_up`, the scalper produces **no signal**. It waits.

### Step 2 — 15m Confirmation

All three conditions must be true at the same time:

| Condition | Value | Meaning |
|---|---|---|
| `EMA(20, 15m) > EMA(50, 15m)` | Short MA above long MA | Momentum is up on 15-minute chart |
| `45 ≤ RSI(14, 15m) ≤ 70` | RSI in mid-zone | Not oversold (no bottom-fishing), not overbought (no chasing tops) |
| `Volume z-score > 0` | Volume above its 20-bar average | Real money participating, not empty price movement |

RSI above 70 is deliberately rejected — that means price has already run hard and is likely to pull back before another leg up. Entering at 70+ means buying after everyone else already bought.

### Step 3 — 5m Entry Trigger

The scalper looks for one of two setups on the 5-minute chart:

**Setup A — Breakout**
```
Price closes above the highest high of the last 12 candles (1 hour)
AND current candle volume ≥ 1.3× the 20-bar average volume
```
This means price pushed through a resistance level that had held for an hour, with above-average participation. The 1.3× volume threshold filters out fake breakouts where price nudges above a level with no commitment.

**Setup B — Pullback continuation**
```
The candle's low touched the 5m EMA(20) within 0.1% tolerance
AND the candle closed above EMA(20)
AND it was a bullish candle (close > open)
```
Price dipped back to the moving average and buyers stepped in — classic continuation entry in an uptrend.

### Typical trade timeline (scalper)

```
T+0:00  Signal detected on 5m close
T+0:01  Risk engine runs 14 gates, sizes position
T+0:01  OTOCO order placed: limit entry + SL bracket + TP bracket
T+0:05  Entry fills on next 5m candle (or does not, order cancelled at 30s stale timeout)
T+?     Trade runs until stop or target is hit — typically 30 minutes to 4 hours
```

---

## 3. Swing Trading — Long-Duration Trades (days to weeks)

**File:** `src/btc_bot/strategy/swing.py`

### What it targets
Larger multi-day moves — typically lasting **2 days to 3 weeks**. It waits for BTC to pull back to support during an ongoing uptrend, then buys the dip with a wide stop and a 2R+ target.

### Three-timeframe structure

```
1W candle   →  Is the weekly trend going up?           (Regime filter)
   └─ YES
      │
1D candle   →  Is the daily trend aligned + not extended? (Confirmation)
      └─ YES
         │
4H candle   →  Is there a pullback entry right now?    (Execution trigger)
```

### Step 1 — 1W Regime Gate

```
close(1W) > EMA(50, weekly)
```

Price must be above its 50-week moving average. This is approximately the 10-month average. If BTC is below this level, the bot does not look for swing longs. This single check filters out bear markets entirely.

### Step 2 — 1D Confirmation

All conditions checked on the daily close:

| Condition | Value | Meaning |
|---|---|---|
| `EMA(20, 1D) > EMA(50, 1D)` | Daily momentum up | Medium-term trend is bullish on the daily chart |
| `RSI(14, 1D) > 50` | RSI above midpoint | Daily momentum positive, not weak |
| `close ≤ EMA(20, 1D) + 2 × ATR(14, 1D)` | Not overextended | Buying within 2 ATRs of the moving average — not chasing after a huge run |

The overextension check is critical. If BTC just ran 15% in 3 days and is sitting far above the EMA, the swing strategy waits for a pullback rather than chasing.

### Step 3 — 4H Entry Trigger

```
candle.low touched EMA(20, 4H) within 0.2% tolerance
AND candle closed above its open (bullish candle)
AND candle volume ≥ 20-bar average volume
```

The 4-hour chart must show price pulling back to the 20-period EMA with a bullish reversal candle. This is the classic "dip-buy at the moving average" entry. The volume check ensures the reversal has real participation.

### Stop calculation for swing trades (more detail in Section 5)

The stop is placed at whichever is wider:
- `entry - 1.5 × ATR(14, 4H)` — volatility-based buffer
- Below the most recent swing low on the 4H chart

This means the stop is beneath actual market structure (a prior low), so normal price oscillation does not hit it.

### Typical trade timeline (swing)

```
T+0:00   4H signal detected
T+0:01   Risk engine approves, sizes position
T+0:01   OTOCO order placed (limit entry + SL + TP)
T+4h     Entry fills on next 4H open (or not — stale timeout is 300s for swing limit orders)
T+2–21d  Trade runs until structure breaks (SL) or target hit (2R+)
```

### Why swing wins over scalper when both signal

Both strategies share a maximum of **1 open position** at a time. When both fire simultaneously:
- The swing trade is chosen
- The scalper signal is logged as "rejected — swing trade priority"

Reason: swing trades have a higher minimum R:R (2.0 vs 1.5), wider stops that survive normal volatility better, and lower proportional fee impact on larger moves.

---

## 4. How Trade Amounts Are Determined

**File:** `src/btc_bot/risk/sizing.py`

**The central rule: position size is always derived from how much you are willing to lose on this trade, divided by where your stop is. Never from a fixed dollar amount or fixed BTC quantity.**

### The formula

```
Risk budget  =  Account equity  ×  risk_per_trade_pct
Stop distance  =  entry_price  −  stop_price

Raw quantity  =  Risk budget  ÷  Stop distance
Final quantity  =  round_down(Raw quantity, stepSize)
```

### Worked example

```
Account equity:         $10,000 USDT
Risk per trade:         0.25%
Risk budget:            $10,000 × 0.0025 = $25

Entry price:            $50,000
Stop price:             $49,000   (ATR-based, 2% below)
Stop distance:          $50,000 − $49,000 = $1,000 per BTC

Raw quantity:           $25 ÷ $1,000 = 0.025 BTC
After step-size rounding: 0.025 BTC (BTC/USDT step size = 0.00001)

Notional value:         0.025 × $50,000 = $1,250
If stop hits:           lose 0.025 × $1,000 = $25 = 0.25% of $10,000  ✓
```

The position size is deliberately **small**. $1,250 exposure on a $10,000 account means BTC going to zero would only cost 12.5% of capital, and a normal stop-out costs $25. The bot never bets more than 0.25% per trade.

### What changes the size automatically

| Factor | Effect |
|---|---|
| Wider stop (higher ATR) | Smaller qty — bigger volatility, tighter risk budget |
| Tighter stop | Larger qty — but capped at 0.5% hard limit |
| Smaller account | Smaller qty |
| Larger account | Larger qty, proportionally |

### Hard caps that override everything

After computing size, the engine validates against Binance exchange filters fetched live:
- Qty must be ≥ `minQty` (0.00001 BTC for BTC/USDT)
- Qty must be ≤ `maxQty` (9000 BTC)
- Notional (qty × price) must be ≥ `minNotional` ($5 for BTC/USDT)
- Actual risk % after rounding must not exceed 0.5% hard cap

If the sized trade would be below the minimum notional at the allowed risk, the trade is rejected: "Notional too small at allowed risk."

### Live ramp-up cap

During the **first 30 days of live trading**, all position sizes are automatically reduced to 10% of their calculated value. This is enforced in code (`live/runner.py`) and cannot be overridden by config. A $25 risk trade becomes a $2.50 risk trade until the bot has proven itself.

---

## 5. How Stop Losses Are Determined

**Formula used in both strategies:**
```
stop = entry − (ATR_STOP_K × ATR(14, execution_timeframe))
```

Where:
- `ATR` = Average True Range over the last 14 candles
- `ATR_STOP_K` = 1.5 (configurable via `ATR_STOP_K` in `.env`)
- ATR is measured on the execution timeframe (5m for scalper, 4H for swing)

### Why ATR?

ATR measures how much BTC moves in a typical candle. Using `1.5 × ATR` places the stop outside normal candle noise. If ATR on 5m is $200, the stop is $300 below entry. A normal pullback of $150 won't hit it. A genuine reversal of $350 will.

### Example — Scalper stop

```
BTC price:              $50,000
ATR(14) on 5m:          $200 (price moves ~$200 per typical 5m candle)
ATR_STOP_K:             1.5
Stop:                   $50,000 − (1.5 × $200) = $49,700
Stop distance:          $300
```

### Example — Swing stop

```
BTC price:              $50,000
ATR(14) on 4H:          $800 (much larger because 4H candles are bigger)
ATR_STOP_K:             1.5
ATR-based stop:         $50,000 − (1.5 × $800) = $48,800
Swing low (10 candles): $48,500 (prior 4H low)
Final stop:             $48,500 − small buffer = $48,492
                        ← whichever is lower/wider wins
```

The swing stop also incorporates **market structure**: it won't be placed above the last swing low, because if price trades below that level, the trend has broken.

### Stop rejection rules

A stop that is less than **0.1% from entry** is automatically rejected by the risk engine as "too tight." This prevents trades where the stop could be hit by the spread alone.

### Trailing stop (after 1R profit)

Once a trade reaches 1R profit (the trade has moved the same distance as the initial stop distance), a trailing stop activates. For the scalper, this trails at 1 × ATR below the highest price reached. For the swing, it trails below the most recent 4H swing low. This locks in some profit while still letting winners run.

---

## 6. The Risk Engine — 14 Gates Every Trade Must Pass

**File:** `src/btc_bot/risk/engine.py`

Every signal from every strategy is passed through 14 checks in sequence. If any check fails, the trade is rejected, the reason is logged to the `signals` table in the database with `accepted=false`, and the LLM can explain why.

```
Gate  1  │ HALT file or HALT env var → reject immediately
Gate  2  │ Kill switch active (volatility spike, API errors, etc.) → reject
Gate  3  │ Short trade on Spot mode → always reject (longs only)
Gate  4  │ News pause active (high-impact negative headline) → reject
Gate  5  │ Already at max open positions (1) → reject
Gate  6  │ Today's realised loss ≥ 1.5% of equity → halt for rest of day
Gate  7  │ This week's realised loss ≥ 4% of equity → halt for rest of week
Gate  8  │ 3 consecutive losses → 4-hour cooldown
Gate  9  │ Per-trade risk exceeds daily loss cap → reject (sizing error)
Gate 10  │ Stop missing or stop distance < 0.1% → reject
Gate 11  │ R:R < 1.5 (scalper) or < 2.0 (swing) → reject
Gate 12  │ Expected move < round-trip fees + slippage buffer → reject
Gate 13  │ Exchange filter violations (min qty, min notional, price range) → reject
Gate 14  │ Calculated size exceeds 0.5% risk hard cap → reject
```

### What the daily and weekly caps mean in practice

```
$10,000 account:
  Daily loss cap:   $10,000 × 1.5% = $150 max loss per day
  Weekly loss cap:  $10,000 × 4%   = $400 max loss per week
```

If the daily cap is hit, no new trades fire until midnight UTC. The existing open trade still runs and its stop-loss is still managed normally — only new entries are blocked.

### Consecutive loss cooldown

After 3 losses in a row:
- A 4-hour cooldown clock starts
- No new trades can open during that window
- The cooldown resets if a winning trade occurs before the 3rd loss

This prevents the psychological trap of "revenge trading" — trying to immediately win back losses with increasingly reckless entries.

### What cannot be overridden

These rules exist as **code logic**, not config values. They cannot be changed by editing `.env`:
- No martingale (doubling size after losses)
- No averaging down (buying more of a losing position)
- No widening stops (moving the stop further away after entry)
- No removing stops (every position must always have a stop)
- No short selling in Spot mode

---

## 7. How the LLM Is Used

**Files:** `src/btc_bot/llm/`, `src/btc_bot/llm/commentary.py`

### The fundamental rule

**The LLM cannot trade. It cannot place orders. It cannot modify positions. It cannot override any risk rule.**

The risk engine enforces this by design: no order-placement function is exposed to any LLM provider. The LLM only receives read-only data and returns text.

### Three supported providers

Set `LLM_PROVIDER` in `.env`:

| Provider | Model (default) | When to use |
|---|---|---|
| `anthropic` | `claude-opus-4-7` | Best analysis quality; uses prompt caching to reduce cost on repeated calls |
| `openai` | `gpt-4o` | Good balance of speed and quality |
| `groq` | `llama-3.3-70b-versatile` | Fastest, cheapest — good for high-frequency commentary |
| `none` | — | Disable LLM entirely; bot runs fine without it |

To switch providers, change `LLM_PROVIDER=groq` in `.env` and restart. No code changes required.

### What the LLM actually does

#### 1. Signal explanation (after every signal)
Every time a signal is evaluated — whether allowed or rejected — the LLM writes a 2-3 sentence explanation:

```
Input to LLM:
  "A scalper strategy signal was REJECTED (R:R 1.2 < minimum 1.5).
   Entry: $50,200. Stop: $49,900. Target: $50,560.
   Market regime: trend_up. RSI: 62.1.
   Explain why this outcome makes sense."

LLM output (stored in logs):
  "The signal was correctly rejected because the target of $50,560
   represents only 1.2x the risk distance, falling short of the 1.5R
   minimum. While the trend and RSI confirm a bullish setup, a 0.72%
   move to target after round-trip fees of 0.15% leaves insufficient
   margin of safety."
```

This makes every rejection auditable in plain English.

#### 2. Daily performance summary
At the end of each trading day, the LLM writes a 3-sentence summary stored in the `daily_performance` table:

```
Input: trades=4, wins=2, losses=2, pnl=-$12, regime=range_bound, top news
Output: "Today's 4 trades resulted in a slight loss of $12 (-0.12%),
         consistent with the range-bound 1H regime that limited
         directional momentum. The two wins were scalper pullback
         trades during the morning session, while losses came from
         breakout attempts that reversed on weak volume.
         No high-impact news events affected session decisions."
```

#### 3. Regime narrative
The LLM translates numeric regime data into a plain-language label stored alongside each trade:

```
Input: price=$50,000, EMA200=$47,500, ATR%=0.8%, ADX=31
Output: "BTC is in a moderate uptrend with healthy volatility
         — suitable for momentum entries with normal position sizing."
```

#### 4. Optional news classification (LLM tagger)
When `NEWS_TAGGER=llm` in `.env`, the LLM classifies each news headline into one of the categories below. This is **advisory only** — the deterministic keyword tagger is always the source of truth for risk pause decisions. The LLM tag is stored as `llm:category` in the `tags` array for reference.

### What the system prompt tells the LLM

```python
COMMENTARY_SYSTEM_PROMPT = """You are a read-only trading analyst assistant.

Your role is STRICTLY limited to:
- Summarizing market conditions from provided data
- Explaining why a trade signal was accepted or rejected
- ...

You CANNOT and MUST NOT:
- Place, modify, or cancel any orders
- Override or suggest bypassing any risk rules
- Increase position sizes
- Disable or modify stop-loss levels
- Make autonomous trading decisions

Risk rules are enforced in code and cannot be overridden by your output.
"""
```

This prompt is included in every LLM call. The Anthropic adapter caches it to avoid resending it on every request (reducing token cost by ~80% on repeated calls).

---

## 8. How News Is Converted Into Trading Signals

**Files:** `src/btc_bot/news/`, `src/btc_bot/news/tagger_keyword.py`, `src/btc_bot/news/ingest.py`

News does not generate buy signals. It generates **pause signals** — temporary blocks on new trade entries.

### Data sources

| Source | Type | Frequency |
|---|---|---|
| CoinDesk RSS | Crypto news | Polled every 15 minutes |
| The Block RSS | Crypto/macro news | Polled every 15 minutes |
| Bitcoin Magazine RSS | BTC-specific news | Polled every 15 minutes |
| Decrypt RSS | General crypto | Polled every 15 minutes |
| CryptoPanic API | Aggregated crypto news with vote scores | Polled every 15 minutes (60 requests/day budget) |

### The tagging pipeline

Every headline goes through this pipeline in `news/ingest.py`:

```
Headline fetched
      │
      ▼
Keyword tagger (deterministic, always runs)
      │
      ├── Tags: regulatory / hack / exchange-outage / etf-flow / macro-event
      ├── Sentiment: -0.8 (negative), +0.6 (positive), 0.0 (neutral)
      └── is_high_impact_negative: true/false
      │
      ▼ (optional, if NEWS_TAGGER=llm)
LLM tagger (advisory only, never overrides keyword result)
      │
      └── Adds llm:category to tags array
      │
      ▼
Stored in news_items table (Supabase)
      │
      ▼
If any high_impact_negative in last 60 minutes:
   → news_pause_active = True for 30 minutes
```

### Keyword patterns that trigger a pause

**Negative (pause trading):**

| Category | Examples of matching phrases |
|---|---|
| `regulatory` | "ban", "crackdown", "SEC sues", "sanctions", "enforcement action", "blacklist" |
| `hack` | "hacked", "exploited", "stolen", "drained", "breach", "$500M stolen" |
| `exchange-outage` | "exchange down", "outage", "withdrawal halt", "trading halt", "freezes withdrawals" |
| `macro-event` | "FOMC", "interest rate hike/cut/decision", "CPI surprise", "recession", "black swan" |

**Positive (tagged but does not pause):**

| Category | Examples |
|---|---|
| `etf-flow` | "ETF approval", "spot Bitcoin ETF", "institutional accumulation", "ETF record inflow" |

### What "pausing" actually means

When a high-impact negative headline is detected:

1. `NewsManager._pause_until` is set to `now + 30 minutes`
2. `RiskEngine.news_pause_active` is set to `True` on the next loop tick
3. Gate 4 of the risk engine rejects every new trade: `"News pause active — high-impact-negative event detected"`
4. All **existing open positions continue to be managed** normally — their stop-losses still apply
5. After 30 minutes, `is_paused` returns `False` and new entries are allowed again

```
10:00 UTC  "Binance halts withdrawals" headline detected
10:00 UTC  News pause activated until 10:30 UTC
10:05 UTC  Scalper fires a signal — REJECTED: "News pause active"
10:15 UTC  Swing fires a signal — REJECTED: "News pause active"
10:30 UTC  Pause expires
10:35 UTC  Next scalper signal — passes Gate 4, continues to other gates
```

The 30-minute window (configurable via `NEWS_COOLDOWN_MINUTES`) is intentionally short. Longer pauses cause the bot to miss recovery moves after false alarms. Shorter pauses let it re-enter before the situation is clear.

### How a headline turns into a trade block (step by step)

```python
# In news/tagger_keyword.py:
headline = "Binance halts withdrawals citing maintenance"
result = tag_item(headline, body="")

# Regex match: r"\bwithdrawal\s+halt"  →  tag: "exchange-outage"
# result.is_high_impact_negative = True
# result.sentiment = -0.8

# In news/ingest.py:
# new high-impact item → self._pause_until = utcnow() + 30 minutes

# In paper/runner.py main loop:
self.engine.news_pause_active = self.news_manager.is_paused  # True

# In risk/engine.py Gate 4:
if self.news_pause_active:
    return Decision.reject("News pause active...")
```

---

## 9. How Both Strategies Share the Same Account

Both strategies compete for the same single position slot and the same equity. The priority rules are:

1. **Only 1 open position at any time** — if one strategy has a trade open, the other is blocked by Gate 5
2. **When both signal simultaneously, swing wins** — this is implemented in `paper/runner.py` and `live/runner.py`
3. **Both share the same daily and weekly loss caps** — if the scalper burns through the daily cap, the swing is also blocked for the day

This means the strategies are genuinely independent in their signal logic, but coordinated in their risk consumption.

---

## 10. Order Execution and Protection

**Files:** `src/btc_bot/execution/`, `src/btc_bot/exchange/`

### Default order type: Limit

All entry orders use **limit orders** by default, not market orders. This avoids paying the market taker spread on entry. A limit order at the current bid/ask fills at the expected price or better.

Market orders can be enabled with `ALLOW_MARKET_ORDERS=true` in `.env`, but this is off by default.

### OTOCO — The protective order structure

When a trade is approved, all three legs are placed simultaneously as an **OTOCO (One-Triggers-OCO)** order:

```
OTOCO order list:
  ├── Working order:  LIMIT BUY  0.025 BTC @ $50,000   (entry)
  └── Pending OCO:
        ├── LIMIT SELL 0.025 BTC @ $51,125   (take profit)
        └── STOP  SELL 0.025 BTC @ $49,700   (stop loss)
```

The OCO (One-Cancels-Other) bracket activates automatically when the entry fills. When either the stop or target is hit, the other is cancelled. There is **no gap** between the entry fill and the protective stop being active.

### If OTOCO fails

If the exchange rejects the OTOCO order (e.g., not supported on the API endpoint being used), the bot falls into a fallback state machine:

```
State:  PENDING_ENTRY
   ↓ entry order fills
State:  AWAITING_PROTECTION   ← dangerous window
   ↓ SL+TP OCO confirmed
State:  PROTECTED
```

If the bot is stuck in `AWAITING_PROTECTION` for more than **5 seconds** (configurable via `PROTECTION_TIMEOUT_SECONDS`), it immediately closes the position at market price and logs a `risk_event` of severity `critical`. Losing a few cents on slippage is better than holding an unprotected position.

### Stale order cancellation

If a limit entry order has not filled within:
- **30 seconds** (scalper) — the setup has passed, cancel and wait for the next signal
- **300 seconds / 5 minutes** (swing) — the 4H setup may still be valid for a while

Stale orders are cancelled automatically.

### Idempotent order IDs

Every order gets a unique `clientOrderId` like `scalper-entry-3f8a2c1d4b5e`. If the same order is retried (e.g., due to a network timeout), the same ID is reused. Binance will not create a duplicate — it returns the existing order. This prevents accidentally opening double positions during connectivity hiccups.

### The user-data WebSocket (live mode)

In live and testnet modes, the bot listens to the Binance **user-data WebSocket stream** for real-time order events. When Binance sends an `executionReport` message saying an order is `FILLED`, the bot updates its local state immediately — without polling. REST API polling runs every 30 seconds as a backup in case the WebSocket disconnects.

---

## 11. What Gets Stored in the Database

Every event is stored in Supabase PostgreSQL. Nothing is ephemeral.

| Table | What's stored | Why |
|---|---|---|
| `candles` | Every OHLCV candle fetched | Historical replay, gap detection |
| `signals` | Every signal generated, **including rejections** | Diagnose why trades weren't taken |
| `orders` | Every order submitted, with status updates | Audit trail, reconciliation |
| `order_lists` | OTOCO / OCO bracket groups | Track linked protective orders |
| `trades` | Every completed trade: entry, exit, P&L, R-multiple | Performance analysis |
| `risk_events` | Kill switch trips, cap breaches, mismatches | Post-mortem debugging |
| `bot_state` | Current open position, cooldown state | Survive restarts without losing position context |
| `daily_performance` | Per-day summary + LLM narrative | Track account growth |
| `strategy_runs` | Start/end time + config hash per run | Know exactly what version ran when |
| `news_items` | Every news headline with tags + sentiment | Correlate news events with trade outcomes |
| `exchange_filters_snapshot` | Binance LOT_SIZE / MIN_NOTIONAL etc. | Never recalculate on stale data |

The rejection log is particularly valuable. If the bot is not trading and you want to know why, query:
```sql
SELECT ts, strategy, reject_reason
FROM signals
WHERE accepted = false
ORDER BY ts DESC
LIMIT 20;
```

---

## 12. Changing Parameters

All tunable values are in `.env`. The most important ones:

### Risk parameters

| Variable | Default | Effect |
|---|---|---|
| `RISK_PER_TRADE_PCT` | `0.0025` (0.25%) | How much of equity to risk per trade. Hard cap at 0.5%. |
| `DAILY_LOSS_CAP_PCT` | `0.015` (1.5%) | Bot stops taking new trades after losing this much in a day |
| `WEEKLY_LOSS_CAP_PCT` | `0.04` (4%) | Bot stops for the week after losing this much |
| `MAX_CONSEC_LOSSES` | `3` | Consecutive losses before cooldown |
| `CONSEC_LOSS_COOLDOWN_HOURS` | `4` | How long the cooldown lasts |
| `MAX_OPEN_POSITIONS` | `1` | Always 1 for MVP |

### Strategy parameters

| Variable | Default | Effect |
|---|---|---|
| `ATR_STOP_K` | `1.5` | Multiplier on ATR for stop distance. Higher = wider stops = smaller positions |
| `MIN_RR` | `1.5` | Minimum reward:risk ratio. Scalper uses this, swing uses 2.0 hard-coded |
| `STRATEGIES_ENABLED` | `scalper,swing` | Set to `scalper` or `swing` to disable one |

### Fee assumptions

| Variable | Default | Meaning |
|---|---|---|
| `FEE_PER_SIDE_PCT` | `0.00075` (0.075%) | Binance spot fee when paying fees in BNB |
| `SLIPPAGE_BUFFER_BPS` | `5` | Extra buffer in basis points (0.05%) on top of fees |

If you are **not** using BNB to pay fees, change `FEE_PER_SIDE_PCT=0.001` (0.10%). The difference may seem small but over hundreds of trades it matters.

### LLM and news

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `none` | Set to `anthropic`, `openai`, or `groq` to enable |
| `LLM_MODEL` | `claude-opus-4-7` | Specific model to use |
| `NEWS_TAGGER` | `keyword` | Set to `llm` to add LLM classification on top of keyword |
| `NEWS_COOLDOWN_MINUTES` | `30` | How long to pause after a high-impact negative headline |

### To change a parameter

1. Edit `.env`
2. Restart the runner (`Ctrl+C` then `py -3.11 scripts/run_paper_local.py`)

No code changes needed for any of the above. The config is validated at startup — if a value is out of range, the bot refuses to start with a clear error message.
