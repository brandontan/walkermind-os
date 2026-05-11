# WARP•FORGE REPORT — forge-fast-ui-premium-2
# Track H: Portfolio Charts + Insights

Branch: claude/portfolio-charts-insights-LwbEx
(Note: harness-assigned; declared WARP/CRUSADERBOT-FAST-UI-PREMIUM-2 in task)
Date: 2026-05-11
Validation Tier: STANDARD
Claim Level: PRESENTATION
Sentinel Required: NO

---

## 1. What Was Built

Portfolio chart delivery via Telegram photo (`/chart`, `chart:N` callbacks) and
enhanced `/insights` command with weekly category + signal breakdown.

Feature set:

**Portfolio Chart**
- `services/portfolio_chart.py` — `generate_portfolio_chart(user_id, days)` derives
  daily balance from the `ledger` table (cumulative running sum, no extra schema).
  Returns `(png_bytes, peak, low, now)` or `None` when no ledger data exists.
- Matplotlib Agg backend (server-side, no display); dark theme chart (1080×540px, 120 DPI).
- `bot/handlers/portfolio_chart.py` — `/chart` command (default 7d) and `chart:N` callback.
- Caption: `PORTFOLIO — N DAYS\nPeak: $X | Low: $Y | Now: $Z`
- Empty-data fallback: graceful text message, no exception.
- `bot/keyboards/__init__.py` — `chart_kb(current_days)` — 3-button inline keyboard
  [7 Days] [30 Days] [All Time], active period marked with ✅.
- Registered in `bot/dispatcher.py`: `/chart` command + `chart:` callback pattern.
- `requirements.txt` — `matplotlib>=3.8.0` added.

**Weekly Insights**
- `jobs/weekly_insights.py` — `format_weekly_insights(data)` hierarchy model:
  Summary → By Category (best/worst win rate) → By Signal (best/worst total PNL).
  No AI API. All data from `positions` + `markets` tables, last 7 days, mode='paper'.
- `run_once()` iterates all active users (tier ≥ 2), sends formatted Telegram message.
  Per-user failure is logged and counted; batch never aborts on a single error.
- APScheduler cron: Monday 08:00 Asia/Jakarta, `id="weekly_insights"`.
- Registered in `scheduler.py`.

**Enhanced /insights**
- `pnl_insights.py` now appends the weekly breakdown section below the existing
  all-time stats panel, using `format_weekly_insights` from `jobs/weekly_insights.py`.
  Both the `/insights` command and the `insights:refresh` callback receive the
  enhanced output.

---

## 2. Current System Architecture

```
Telegram bot
  ├── /chart [chart_command]          → services/portfolio_chart.py
  │     └── chart:N callback          → generate_portfolio_chart(user_id, days)
  │           └── ledger table        → cumulative balance series → _generate_png()
  │
  ├── /insights [pnl_insights_command] → _fetch_insights() [all-time stats]
  │     └── insights:refresh callback  + _fetch_weekly_stats() [7-day category+signal]
  │           └── positions + markets → format_weekly_insights()
  │
Scheduler
  └── weekly_insights cron            → jobs/weekly_insights.run_job()
        Monday 08:00 Asia/Jakarta       → run_once() → notifications.send()
```

---

## 3. Files Created / Modified

**Created:**
- `projects/polymarket/crusaderbot/services/portfolio_chart.py`
- `projects/polymarket/crusaderbot/jobs/weekly_insights.py`
- `projects/polymarket/crusaderbot/bot/handlers/portfolio_chart.py`
- `projects/polymarket/crusaderbot/tests/test_portfolio_charts_insights.py` (27 tests)

**Modified:**
- `projects/polymarket/crusaderbot/bot/keyboards/__init__.py` — added `chart_kb()`
- `projects/polymarket/crusaderbot/bot/dispatcher.py` — registered `/chart` + `chart:` callback + import
- `projects/polymarket/crusaderbot/bot/handlers/pnl_insights.py` — weekly section appended
- `projects/polymarket/crusaderbot/scheduler.py` — weekly_insights cron added
- `requirements.txt` — `matplotlib>=3.8.0`

---

## 4. What Is Working

- `/chart` sends a PNG photo with caption and 3-period inline keyboard.
- `chart:7`, `chart:30`, `chart:all` callbacks swap the period; active button marked ✅.
- Empty ledger → text fallback, no crash.
- `/insights` returns the all-time panel followed by the 7-day category/signal breakdown.
- Weekly cron registered: Monday 08:00 Asia/Jakarta, `id="weekly_insights"`, `coalesce=True`.
- `format_weekly_insights` handles zero-trades empty state gracefully.
- Per-user failures in `run_once()` do not abort the batch.
- 27 hermetic tests green (no DB, no network).

---

## 5. Known Issues

- **Environment:** `eth_account` not installed in local CI sandbox — 2 pre-existing
  scheduler-import tests in `test_daily_pnl_summary.py` fail locally; unrelated to
  this task. CI on the actual runner is expected to be green.
- **Branch name mismatch:** harness auto-assigned `claude/portfolio-charts-insights-LwbEx`;
  declared branch was `WARP/CRUSADERBOT-FAST-UI-PREMIUM-2`. WARP🔹CMD should rename
  before merge per branch naming rules.
- **portfolio_snapshots table:** does not exist in schema; chart derives from `ledger`
  cumulative sum. If a dedicated snapshots table is added later, `_fetch_daily_balance_series`
  should be updated.
- **Chart for new users with no ledger entries:** returns None → fallback text. Expected
  behavior until first deposit/trade.

---

## 6. What Is Next

- WARP🔹CMD review → merge (no SENTINEL required, Tier: STANDARD).
- Optional follow-on: add `/chart` shortcut button to dashboard keyboard.
- Rename branch from `claude/...` to `WARP/CRUSADERBOT-FAST-UI-PREMIUM-2` before merge.

---

**Validation Tier:** STANDARD
**Claim Level:** PRESENTATION
**Validation Target:** `/chart` photo delivery, `chart:N` period switch, `/insights` weekly section, weekly cron registration
**Not in Scope:** AI-generated insights, live price data, DB schema changes, trading logic
**Suggested Next Step:** WARP🔹CMD review → merge
