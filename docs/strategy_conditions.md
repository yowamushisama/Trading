# Strategy Conditions Reference

This document explains every condition both strategies check before generating a signal,
all technical terms used, and concrete real-world scenarios.

---

## Table of Contents

1. [Technical Terms Glossary](#1-technical-terms-glossary)
2. [How a Candle Works](#2-how-a-candle-works)
3. [What is a Timeframe?](#3-what-is-a-timeframe)
4. [Scalper Strategy — Full Conditions](#4-scalper-strategy--full-conditions)
5. [Swing Strategy — Full Conditions](#5-swing-strategy--full-conditions)
6. [After a Signal: The Risk Engine Gates](#6-after-a-signal-the-risk-engine-gates)
7. [Why Both Strategies Are Silent Right Now](#7-why-both-strategies-are-silent-right-now)

---

## 1. Technical Terms Glossary

### EMA (Exponential Moving Average)
An average of price over N candles, where **recent candles count more** than older ones.

- **EMA(20)** = average of the last 20 candles, weighted toward recent price
- **EMA(50)** = same but over 50 candles — slower to react
- **EMA(200)** = very slow, long-term average — the "big picture" trend line

**What it tells you:** Where the average price has been. If current price is above EMA200,
the market has been generally rising. If below, it has been generally falling.

**Example:**
```
BTC price today:  $73,476
BTC EMA200 (1H):  $78,234
→ Price is BELOW EMA200 → downtrend
```

**Why EMA over SMA (Simple Moving Average)?**
EMA reacts faster to recent price changes. A sudden crash shows up in EMA within a few
candles. SMA would still reflect the old high price for many more candles.

---

### ATR (Average True Range)
Measures how much price **moves per candle on average** over the last 14 candles.

True Range of one candle = the largest of:
- High minus Low (the candle's own range)
- |High minus previous close| (gap up scenario)
- |Low minus previous close| (gap down scenario)

ATR = average of those true ranges over 14 candles.

**What it tells you:** Volatility. High ATR = big moves. Low ATR = quiet market.

**Example:**
```
BTC 1H ATR = $450
→ On average each hourly candle moves $450 from its extreme low to extreme high
```

**How the bot uses ATR:**
- To set stop-loss distance: `stop = entry - 1.5 × ATR`
  If ATR = $450, stop is placed $675 below entry.
- To detect if volatility is in a "healthy" range (not too quiet, not explosively volatile)

---

### ATR% (ATR as a Percentage)
ATR divided by current price. Normalises volatility across different price levels.

```
ATR% = ATR / current_price

Example:
ATR = $450, price = $73,000
ATR% = 450 / 73000 = 0.62%
```

**Why use ATR% instead of raw ATR?**
Raw ATR of $450 means something very different when BTC is at $5,000 vs $100,000.
ATR% makes the number comparable regardless of price level.

Valid range in the scalper: **0.4% to 2.5%**
- Below 0.4% → market is sleeping, no real moves happening → classified as **chop**
- Above 2.5% → market is in panic/explosion mode → classified as **high_volatility**
- Both extremes = the bot sits out

---

### ADX (Average Directional Index)
Measures **how strongly the market is trending**, regardless of direction.

Scale: 0 to 100
- **0–20**: No trend, market is drifting or ranging
- **20–25**: Weak trend forming
- **25–40**: Clear trend in progress
- **40+**: Very strong trend

**Important:** ADX does NOT tell you direction (up or down). It only tells you how
strongly price is moving in one direction. Combined with EMA200 (which gives direction),
you get the full picture.

**Example:**
```
ADX = 18 → No real trend, market chopping sideways → scalper stays out
ADX = 31 → Clear trend → scalper considers entering
```

**Threshold in this bot:** ADX must be ≥ 25 to confirm a trend is real.

---

### RSI (Relative Strength Index)
Measures **momentum** — is the market overbought (too high, likely to pull back) or
oversold (too low, likely to bounce)?

Scale: 0 to 100
- **Below 30**: Oversold (sellers exhausted, potential bounce)
- **30–50**: Bearish momentum
- **50–70**: Bullish momentum (healthy uptrend zone)
- **Above 70**: Overbought (buyers exhausted, potential pullback)

**How the scalper uses it (15m RSI):**
Must be between 45 and 70.
- Below 45 → momentum is not bullish enough
- Above 70 → market is overbought, not a safe long entry

**How the swing uses it (1D RSI):**
Must be above 50. Below 50 means daily momentum is still bearish.

---

### Volume Z-Score
Measures whether current volume is **unusually high or low** compared to recent history.

```
Z-score = (current_volume - average_volume_20) / standard_deviation_20
```

- **Z-score > 0**: Volume is above the 20-candle average (more interest than usual)
- **Z-score > 1**: Volume is 1 standard deviation above average (noticeably elevated)
- **Z-score < 0**: Volume is below average (quiet, low conviction)

**What it tells you:** When price moves on high volume, the move is likely real.
When price moves on low volume, it could be a fake-out.

**Example:**
```
Average 15m volume = 100 BTC
Current 15m volume = 145 BTC
Z-score = (145 - 100) / 30 = +1.5 → well above average → valid signal
```

---

### Swing High / Swing Low
The highest high (or lowest low) over the last N candles.

**Swing High (lookback=12)** on 5m chart = the highest price reached in the last 12 candles (= last 60 minutes)

**Why it matters:** Breaking above a swing high with volume is a "breakout" — buyers
have overwhelmed all sellers from the last hour.

---

### Pullback
When price is in an uptrend but temporarily dips back down toward a moving average
before continuing higher.

```
Example:
BTC uptrend → price rises to $75,000
→ Pulls back to EMA20 at $72,000
→ Bounces off EMA20 with a green candle
→ This is a pullback entry
```

Pullbacks are considered **safer entries** than breakouts because you're buying closer
to the support level (EMA), meaning your stop-loss is tighter.

---

### Breakout
When price pushes above a recent resistance level (swing high) with high volume,
signalling that buyers are aggressively in control.

```
Example:
BTC ranging between $70,000–$72,000 for the past hour
→ Price breaks above $72,000 (the swing high) with 2× normal volume
→ This is a breakout entry
```

Breakouts have more momentum but more risk of false breakouts (fakeouts).

---

### R:R (Risk-to-Reward Ratio)
How much you could gain vs. how much you risk on a single trade.

```
Entry: $73,000
Stop:  $72,000  → Risk = $1,000 per BTC
Target: $75,000 → Reward = $2,000 per BTC
R:R = 2000 / 1000 = 2.0
```

A 2.0 R:R means: "I risk $1 to potentially make $2."

**Minimum R:R in this bot:**
- Scalper: 1.5 (make at least $1.50 for every $1 risked)
- Swing: 2.0 (make at least $2.00 for every $1 risked)

Trades with poor R:R are rejected by the risk engine even if the setup looks good.

---

### Regime
The overall market condition: is BTC trending, ranging, or in chaos?

| Regime | Meaning |
|---|---|
| `trend_up` | Clear uptrend — ADX ≥ 25, price above EMA200, normal volatility |
| `trend_down` | Clear downtrend — ADX ≥ 25, price below EMA200, normal volatility |
| `range_bound` | ADX < 25 — price oscillating, no clear direction |
| `chop` | ATR% < 0.4% — market barely moving, no opportunity |
| `high_volatility` | ATR% > 2.5% — market in panic/explosion, too risky |

**The scalper only trades in `trend_up`.** All other regimes return no signal.

---

## 2. How a Candle Works

A candle represents price movement over one time period.

```
      │  ← High (highest price reached)
      │
   ┌──┴──┐
   │     │  ← This is the "body"
   │     │     Green body = closed higher than it opened (bullish)
   └──┬──┘     Red body   = closed lower than it opened (bearish)
      │
      │  ← Low (lowest price reached)

Open  = price when the period started
Close = price when the period ended
High  = highest price touched during the period
Low   = lowest price touched during the period
```

A **bullish candle** = close > open (green). Price went up during this period.
A **bearish candle** = close < open (red). Price went down during this period.

---

## 3. What is a Timeframe?

A timeframe defines how long each candle covers.

| Timeframe | Each candle = | Used for |
|---|---|---|
| 5m | 5 minutes | Scalper execution — precise entry timing |
| 15m | 15 minutes | Scalper confirmation — short-term trend |
| 1H | 1 hour | Scalper regime gate — hourly trend direction |
| 4H | 4 hours | Swing execution — multi-hour setups |
| 1D | 1 day | Swing confirmation — daily trend health |
| 1W | 1 week | Swing regime gate — macro trend direction |

**Why use multiple timeframes?**
Each timeframe answers a different question:
- Weekly/Daily = macro direction ("is the big trend up?")
- Hourly/4H = medium-term confirmation ("is the current move healthy?")
- 5m/15m = precise entry ("is right now a good moment to buy?")

All three timeframes must agree before the bot enters. This is called **multi-timeframe confluence**.

---

## 4. Scalper Strategy — Full Conditions

**Design:** Catches short-to-medium momentum moves using 1H trend as the big filter,
15m as confirmation, and 5m for the exact entry trigger.

**Only takes long (buy) trades.** Never shorts.

---

### Layer 1: 1H Regime Gate

**Timeframe:** 1-hour candles, last 60 days of data

The regime gate is the first and most important filter. If this fails, the strategy
does not even look at the 15m or 5m charts.

**Three checks, all must pass:**

#### Check A: Volatility in range (ATR%)
```
ATR% must be between 0.4% and 2.5%

Too low  (< 0.4%): Market is sleeping → classified as CHOP → no trade
Too high (> 2.5%): Market is in panic → classified as HIGH_VOLATILITY → no trade
```

**Scenario — chop:**
BTC has been trading between $72,900 and $73,100 for hours. Each 1H candle barely moves.
ATR% = 0.15% → regime = chop → scalper skips.

**Scenario — high volatility:**
A major exchange just announced bankruptcy. BTC dropped 8% in one hour.
ATR% = 4.2% → regime = high_volatility → scalper skips. (Good: this protects you from
buying into a crash.)

#### Check B: ADX ≥ 25 (trend is real)
```
ADX measures trend strength, not direction.
ADX must be >= 25 to confirm a real directional move is happening.
```

**Scenario — ADX too low:**
BTC is oscillating between $71,000 and $75,000 with no clear direction.
ADX = 16 → regime = range_bound → scalper skips.

**Scenario — ADX passes:**
BTC has been climbing steadily for 3 days.
ADX = 32 → trend is real, proceed to direction check.

#### Check C: Price above 1H EMA(200) (direction is up)
```
1H EMA200 = average of the last 200 hourly closes (≈ 8 days of data)
Price must be ABOVE this average to confirm uptrend.
```

**Combined result:**
```
ATR% in range + ADX >= 25 + price > EMA200 → regime = trend_up → gate PASSES
ATR% in range + ADX >= 25 + price < EMA200 → regime = trend_down → gate FAILS
```

**Current status (as of your logs):**
```
price=73,476 vs EMA200=~78,234 → price BELOW EMA200 → trend_down → SKIP
```

**What needs to change:** BTC needs to rally above its 8-day hourly average and sustain
a strong directional move (ADX ≥ 25) before this gate opens.

---

### Layer 2: 15m Confirmation

**Timeframe:** 15-minute candles, last 7 days of data

Only reached if the 1H regime gate passed. Three more checks.

#### Check A: 15m EMA(20) > EMA(50) — short-term uptrend
```
EMA20 (last 5 hours of 15m data) must be ABOVE EMA50 (last 12.5 hours)
This confirms the short-term momentum is also upward.
```

**Scenario — passes:**
```
EMA20(15m) = $74,200
EMA50(15m) = $73,800
→ EMA20 > EMA50 → short-term trend is up → check passes
```

**Scenario — fails:**
```
EMA20(15m) = $73,500
EMA50(15m) = $73,900
→ EMA20 < EMA50 → short-term trend still down → skip
```

#### Check B: 15m RSI between 45 and 70
```
RSI must be in the "healthy bullish zone":
- Below 45: momentum not bullish enough, buyers not in control yet
- Above 70: overbought, risky to buy here (likely to pull back soon)
- Between 45–70: momentum is positive but not exhausted
```

**Scenario — RSI too low (45):**
```
RSI(15m) = 38 → buyers haven't taken control → SKIP
```

**Scenario — RSI too high (>70):**
```
RSI(15m) = 74 → market overbought, skip and wait for pullback → SKIP
```

**Scenario — RSI passes:**
```
RSI(15m) = 58 → healthy bullish momentum → CHECK PASSES
```

#### Check C: 15m Volume Z-score > 0
```
Volume on the last 15m candle must be above its 20-candle average.
Z-score > 0 means current volume > average of last 5 hours.
```

**Why:** Low-volume moves are unreliable. If BTC is going up but nobody is trading,
it could reverse easily. Above-average volume = real buying interest.

**Scenario — fails:**
```
Average 15m volume: 80 BTC
Current 15m volume: 60 BTC
Z-score = -1.25 → below average → SKIP
```

**Scenario — passes:**
```
Average 15m volume: 80 BTC
Current 15m volume: 110 BTC
Z-score = +1.1 → above average → CHECK PASSES
```

---

### Layer 3: 5m Execution Trigger

**Timeframe:** 5-minute candles, last 24 hours of data

Only reached if both Layer 1 and Layer 2 passed. The bot now looks for the exact
entry candle. One of two setups must fire — either a **breakout** or a **pullback**.

#### Setup A: Breakout
```
Breakout requires BOTH:
1. current_close > swing_high(last 12 candles)  ← price breaks the 1-hour high
2. current_volume >= 1.3 × average_volume(20)   ← volume is 30%+ above normal
```

**What this looks like:**
BTC has been ranging between $72,800 and $73,200 on the 5m chart for the past hour
(12 candles). Then a candle closes at $73,350 — above the range — and its volume is
140% of the recent average.

**Why volume must confirm:** Without volume, a breakout above the swing high could be
a trap. Market makers sometimes push price above resistance to trigger stop-losses,
then reverse it. Volume above 1.3× average makes a false breakout less likely.

#### Setup B: Pullback to EMA20
```
Pullback requires ALL THREE:
1. current_close > EMA20(5m)           ← still above the average (uptrend intact)
2. candle_low <= EMA20(5m) × 1.001     ← the candle dipped to within 0.1% of EMA20
3. current_close > current_open        ← bullish candle (bounced off EMA and recovered)
```

**What this looks like:**
BTC 5m EMA20 is at $72,950. The latest candle touched as low as $72,980 (within 0.1%
of the EMA), but closed at $73,100 — above both the open and the EMA. This is a
classic "wick to EMA + bounce" candle.

**Why this is a good entry:** You are entering near support (the EMA20), meaning your
stop can be tight (just below the EMA). Tight stop = smaller loss if wrong.

#### If neither breakout nor pullback fires:
```
log: [scalper] SKIP | breakout=False pullback=False
→ No signal this tick
```

---

### Signal Output (if all three layers pass)
```python
entry  = current 5m close price
stop   = entry - (1.5 × 5m ATR)
target = entry + (stop_distance × 1.5)   ← minimum 1.5 R:R
reason = "breakout | regime=trend_up | RSI=58.3"
       OR
       = "pullback | regime=trend_up | RSI=61.2"
```

**Example numbers:**
```
Entry:  $74,000
ATR:    $300
Stop:   $74,000 - (1.5 × $300) = $73,550   ← $450 below entry
Target: $74,000 + $450 × 1.5 = $74,675     ← $675 above entry
R:R:    1.5
```

---

## 5. Swing Strategy — Full Conditions

**Design:** Catches larger multi-day moves. Uses the weekly chart as the macro
filter, daily for confirmation, and 4H for the exact entry trigger.

**Only takes long (buy) trades.** Never shorts.
**Minimum R:R:** 2.0 (vs scalper's 1.5) — bigger trades need bigger reward justification.

---

### Layer 1: 1W Trend Gate

**Timeframe:** 1-week candles, last ~1000 days of data (≈ 143 weeks needed, 60 minimum)

#### Check: Weekly close > EMA(50, weekly)
```
EMA50 on weekly chart = average of the last 50 weeks (~1 year of weekly closes)
Weekly close must be ABOVE this average.
```

This is the most powerful filter. If BTC's weekly price is below its 1-year average,
the bot will not take any long trades regardless of what shorter timeframes show.

**What this means in plain terms:**
The EMA50 on weekly is roughly "where has BTC averaged over the past year?"
If current price is below that, we are in a bear market by definition.

**Current status (as of your logs):**
```
1W close  = $73,476
1W EMA50  = $84,724
Gap       = -$11,248 (-13.3%)

→ BTC needs to rally ~15% and sustain it to clear this gate.
```

**Scenario — gate passes:**
```
BTC rallies to $87,000 over the coming weeks and holds above $84,724.
1W EMA50 itself rises to ~$85,200 as it catches up.
close ($87,000) > EMA50 ($85,200) → gate PASSES
```

**Scenario — gate fails (current):**
```
BTC at $73,476, well below the 1-year average of $84,724.
→ SKIP immediately. No further checks.
```

---

### Layer 2: 1D Confirmation

**Timeframe:** 1-day candles, last 365 days of data (60 minimum)

Only reached if the weekly gate passed. Three checks.

#### Check A: Daily EMA(20) > EMA(50)
```
EMA20 (last 20 days) must be ABOVE EMA50 (last 50 days)
This confirms the daily trend is also upward.
```

**Scenario — fails:**
```
EMA20(1D) = $84,100 (short-term average)
EMA50(1D) = $85,300 (medium-term average)
EMA20 < EMA50 → daily trend still recovering → SKIP
```

**Scenario — passes:**
```
EMA20(1D) = $86,400
EMA50(1D) = $84,900
EMA20 > EMA50 → daily trend is up → check passes
```

#### Check B: Daily RSI ≥ 50
```
RSI on the daily chart must be above 50 — bullish momentum territory.
Below 50 = bearish momentum, not a good time to buy.
```

**Why 50 and not 45 (like the scalper)?**
The swing strategy holds positions for days to weeks. Entering with RSI below 50
on the daily means you are fighting daily momentum, which is risky for longer holds.

**Scenario — fails:**
```
RSI(1D) = 44 → daily momentum still bearish → SKIP
```

**Scenario — passes:**
```
RSI(1D) = 62 → healthy daily momentum → CHECK PASSES
```

#### Check C: Not overextended (close < EMA20 + 2×ATR daily)
```
If price has already run far above the daily EMA20, it is likely to pull back
before going higher. The bot avoids chasing.

Overextended condition:
close > EMA20(1D) + 2 × ATR(1D)
```

**Example:**
```
EMA20(1D) = $86,000
ATR(1D)   = $1,800
Upper bound = $86,000 + 2×$1,800 = $89,600

If BTC close = $91,000 → overextended → SKIP
If BTC close = $87,500 → not overextended → CHECK PASSES
```

**Why this matters:** Buying when price is already 2 ATRs above the mean is statistically
likely to result in a near-term pullback wiping out your position before it goes higher.
The bot waits for a healthier entry point.

---

### Layer 3: 4H Execution Trigger

**Timeframe:** 4-hour candles, last 180 days of data (30 minimum)

Only reached if both weekly and daily gates passed. Four specific conditions must
all fire simultaneously on the same 4H candle.

#### Check A: Pullback to 4H EMA20
```
candle_low <= EMA20(4H) × 1.002
The candle's low must have touched within 0.2% of the 4H EMA20.
```

This means the 4H price dipped down to touch the average before recovering.
The 0.2% buffer accounts for the fact that prices rarely touch the EMA exactly.

**Example:**
```
4H EMA20 = $86,000
Candle low = $86,100 → within 0.2% ($172) of EMA → pullback_to_ema = True
Candle low = $87,500 → too far above EMA → pullback_to_ema = False → SKIP
```

#### Check B: Bullish candle (close > open)
```
The 4H candle must close higher than it opened — a green candle.
```

This confirms that after dipping to the EMA, buyers stepped in and pushed price back up.
A red candle (close < open) at the EMA means sellers are still in control — skip.

**Scenario — bullish reversal at EMA (passes both A and B):**
```
Open:  $85,800
Low:   $86,050  (touched EMA at $86,000)
Close: $86,600  (close > open = bullish candle)
→ pullback_to_ema = True, bullish_candle = True → both checks pass
```

**Scenario — bearish at EMA (fails check B):**
```
Open:  $86,400
Low:   $85,950  (touched EMA)
Close: $86,100  (close < open = red candle, sellers won)
→ pullback_to_ema = True, bullish_candle = False → SKIP
```

#### Check C: Above-average volume
```
Current 4H candle volume must be >= rolling 20-candle average volume.
```

Same principle as the scalper — volume confirms the move is real.
A green candle at EMA on below-average volume could be a weak bounce before continuation lower.

---

### Signal Output (if all three layers pass)
```python
entry  = current 4H close price
stop   = min(entry - 1.5 × 4H_ATR,  swing_low(last 10 candles) - tiny buffer)
         ← the lower of ATR-based stop and the recent structural low
target = entry + (stop_distance × 2.0)   ← minimum 2.0 R:R
reason = "4H pullback to EMA20 | RSI_1D=62.4"
```

**Why use swing low for stop (not just ATR)?**
The structural swing low is where buyers previously stepped in. If price breaks
below that level, the bullish thesis is invalidated. Using whichever stop is lower
(ATR or swing low) gives you the wider, more structurally sound protection.

**Example numbers:**
```
Entry:        $86,600
4H ATR:       $900
ATR stop:     $86,600 - (1.5 × $900) = $85,250
Swing low:    $84,800 (recent 10-candle low)
Final stop:   min($85,250, $84,800) = $84,800

Stop distance = $86,600 - $84,800 = $1,800
Target:        $86,600 + ($1,800 × 2.0) = $90,200

R:R = 2.0
```

---

## 6. After a Signal: The Risk Engine Gates

Even after a strategy produces a signal, the **Risk Engine** runs 14 gates in sequence.
Any single gate failing rejects the trade.

| Gate | What it checks |
|---|---|
| 1 | HALT file — manual emergency stop active? |
| 2 | Kill switch — too many API errors or consecutive losses? |
| 3 | Short trades blocked (Spot mode only supports longs) |
| 4 | News pause — high-impact negative event? |
| 5–9 | Account limits: daily loss cap, weekly loss cap, consecutive losses, cooldown period, max open positions |
| 10 | Per-trade risk cap not exceeded |
| 11 | Stop-loss exists and is at least 0.1% away from entry |
| 12 | R:R meets minimum (1.5 for scalper, 2.0 for swing) |
| 13 | Trade is profitable after fees and slippage |
| 14 | Position size meets Binance minimum order requirements |

**Gate 14 is currently your most likely failure point.**
Your account equity is $5.00 USDT. Binance requires a minimum order of ~$10–20 USDT.
Even if a signal fires through all conditions above, Gate 14 will reject it:
```
Sizing: notional $X.XX below exchange minimum
```
You need at least ~$20–50 USDT to place a real order.

---

## 7. Why Both Strategies Are Silent Right Now

**Scalper:**
```
1H price ($73,476) < 1H EMA200 (~$78,000)
→ regime = trend_down → rejected at Layer 1, Gate A

What needs to happen:
BTC must rally above ~$78,000 on the 1H chart AND maintain ADX >= 25
Approximate timeframe: days to weeks depending on market conditions
```

**Swing:**
```
1W close ($73,476) < 1W EMA50 ($84,724) — gap of ~$11,200 (15%)
→ rejected at Layer 1 immediately

What needs to happen:
BTC must rally and sustain above ~$85,000 for multiple weeks
The 1W EMA50 itself will also need to rise (it lags price)
Approximate timeframe: weeks to months depending on market conditions
```

**This is correct bot behaviour.** The bot is designed to only trade in confirmed
uptrends. Sitting out a downtrend preserves capital. The filters exist specifically
to prevent buying into falling prices.

---

*File: docs/strategy_conditions.md*
*Last updated: 2026-05-28*
