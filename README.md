# BTC Trading Bot

Production-grade BTC/USDT trading bot. **Survives first, profits second.**

## Quick Start

### Prerequisites
1. Python 3.11+
2. Install dependencies:
   ```
   py -3.11 -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -e ".[dev]"
   ```
3. Copy `.env.example` → `.env` and fill in your values
4. **Delete `binance_keys.txt`** — it contains plaintext keys

### Run tests (Phase 0 — must pass before anything else)
```
set PYTHONPATH=src
py -3.11 -m pytest tests/ -v
```

### Run backtest
```
set PYTHONPATH=src
py -3.11 scripts/run_backtest.py --strategy scalper --from 2023-01-01 --to 2025-01-01
py -3.11 scripts/run_backtest.py --strategy scalper --stress
py -3.11 scripts/run_backtest.py --strategy scalper --walk-forward
```

### Run paper trading (paper_local — mainnet candles, simulated fills)
```
# Set MODE=paper_local in .env
set PYTHONPATH=src
py -3.11 scripts/run_paper_local.py
```

### Stop the bot
```
# Option 1: Create HALT file
echo. > HALT

# Option 2: Set env var
set HALT=true
```

---

## Phases

| Phase | Status | Description |
|-------|--------|-------------|
| 0 | ✅ | Safety scaffold: risk engine, sizing, kill switch, 61 tests |
| 1 | ✅ | Backtest: data, indicators, strategies, metrics, walk-forward |
| 2 | ✅ | paper_local: live candles, simulated fills, no exchange orders |
| 3 | 🔜 | Testnet execution: real orders, user-data WS, OTOCO, news, LLM |
| 4 | 🔒 | Gated live: double-flag, 10% size ramp, monitoring, DR runbook |

---

## Strategy Parameters

### Scalper (configs/strategies/scalper.yaml)
- Execution: 5m candles
- Confirmation: 15m (EMA20 > EMA50, RSI 45–70)
- Regime: 1H (close > EMA200, ATR 0.4%–2.5%)
- Stop: `entry - 1.5 * ATR(14, 5m)`
- Target: min 1.5R

### Swing (configs/strategies/swing.yaml)
- Execution: 4H candles
- Confirmation: 1D (EMA20 > EMA50, RSI > 50)
- Regime: 1W (close > EMA50)
- Stop: `max(1.5 * ATR(14, 4H), swing_low)`
- Target: min 2.0R

To change parameters, edit `configs/strategies/scalper.yaml` or
set environment variables (`ATR_STOP_K`, `MIN_RR`, etc.).

---

## Risk Management

All 14 gates run in order before any trade is allowed:

1. Manual HALT (file or env var)
2. Kill switch (volatility spike, API errors, data gaps, position mismatch)
3. Short trades blocked (Spot mode — longs only)
4. News pause (high-impact-negative tag detected)
5. Open positions ≥ max (1)
6. Daily loss cap hit (1.5%)
7. Weekly loss cap hit (4%)
8. Consecutive-loss cooldown (3 losses → 4h pause)
9. Per-trade risk > 0.25%
10. Stop missing or stop-distance < 0.1%
11. R:R < 1.5
12. Expected move < fees + slippage + buffer
13. Exchange filter validation (qty, notional, price)
14. Position size exceeds risk cap

**Hard-coded rules (cannot be overridden by config or LLM):**
- No martingale
- No averaging down
- No widening stops
- No removing stops

---

## LLM Layer (Phase 3)

LLM is a **read-only commentary assistant** — it cannot trade.

Supported providers (set `LLM_PROVIDER` in `.env`):
- `anthropic` — Claude (default, with prompt caching)
- `openai` — GPT-4o
- `groq` — Llama 3 (fastest, lowest cost)
- `none` — disabled (default)

The LLM has no access to order placement tools.

---

## Before Real-Money Live Trading

Do NOT go live until ALL of these are done:

- [ ] ≥ 90 days green `paper_local` on mainnet candles
- [ ] Backtest stress test passed (PF > 1.2 @ 0.10% fee, DD < 15%)
- [ ] Walk-forward OOS PF > 1.0 on every window
- [ ] Independent code review of `src/btc_bot/risk/` and `src/btc_bot/execution/`
- [ ] API key: withdrawal disabled, IP-whitelisted, Spot trading only
- [ ] External uptime monitor (UptimeRobot / Better Stack) configured
- [ ] Disaster recovery runbook (`docs/DR.md`) tested
- [ ] Phase 3 testnet plumbing drills all passed
- [ ] First 30 days capped at 10% of intended size (enforced in code)

---

## Directory Structure

```
src/btc_bot/
├── config.py          # All settings; validates live mode flags
├── data/              # REST candle fetch, gap detection
├── exchange/          # Adapter interface, Binance Spot, paper_local
├── strategy/          # Indicators, scalper, swing, regime classifier
├── risk/              # Engine (14 gates), sizing, fees, kill switch, protection
├── execution/         # Order manager, idempotency
├── backtest/          # Runner, metrics, walk-forward, stress test
├── paper/             # paper_local runner
├── live/              # Gated live runner
├── llm/               # Provider-agnostic LLM (Anthropic/OpenAI/Groq)
├── news/              # RSS + CryptoPanic + keyword tagger
├── storage/           # SQLAlchemy models, DB session
└── utils/             # Logging, time, halt detection
```
