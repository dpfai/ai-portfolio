# AI Trading Arena

Static GitHub Pages dashboard for comparing AI/quant trading strategies.

## Data Pipeline

Website data lives in `data/*.json`, including `data/health.json` for the site status strip. The full refresh entrypoint is:

```bash
python3 scripts/refresh_trading_arena.py --end YYYY-MM-DD
```

That wrapper updates QuantAI first, then calls `scripts/build_trading_arena_data.py`. It runs `quant-learning/daily_runner.py` so QuantAI does not stall, then rebuilds daily values for all strategies. AI Analyst uses existing OpenClaw `stock_analysis_*.json` files as weekly decision points; daily refresh only marks current holdings to market. Trading Arena never generates stock analysis files.

AI Analyst execution rule: a `stock_analysis_YYYY-MM-DD.json` file is a decision made on `YYYY-MM-DD`; any buy/sell signal is executed on the next trading day, using that next trading day's price. The decision day itself only marks existing holdings to market.

Refresh validation fails before publish if any required source is missing, critical numeric fields are null/NaN, strategy latest dates are misaligned, `health.json` is inconsistent, or the latest AI Analyst stock analysis is more than 10 days old. Daily holding valuation may carry forward the latest available past price when the current-day quote is missing, and those rows are marked with `price_status=carried_forward`; execution prices for new trades still require a valid source price. AI Analyst signal reasons are normalized into English when `signals.json` is generated.

The generator is intentionally kept in this repository. OpenClaw produces upstream research and portfolio files, while this repo owns the final Trading Arena JSON contract.

Current data sources:

- `quant_learning`: QuantAI rows read from `~/AI-workplace/quant-learning/data/trading_arena.db` when available.
- `ai_analyst`: OpenClaw Haiyan stock analysis files under `~/.openclaw/workspace-explorer/investments/stock_analysis_*.json`; weekly decisions, daily valuation.
- `spy`: SPY buy-and-hold benchmark with Tuesday DCA.
- `etf_aggressive`, `etf_balanced`, `etf_conservative`: OpenClaw ETF portfolio tracker data from `~/.openclaw/workspace-explorer/investments/portfolio_data/portfolio_tracking.json`.

The OpenClaw cron task `AI Trading Arena 数据发布 (乐天)` should trigger `scripts/refresh_trading_arena.py` from the main agent. Trading Arena publish logic should not be moved into `quant-learning`; that project may be updated/read as a QuantAI source only.


## Frontend

Shared browser utilities live in `common.js`: cache versioning, strategy metadata, formatting helpers, range filtering, data loading, and the data health strip. Page-specific files should keep only page rendering logic.

## Tests

Run the local rule tests with:

```bash
python3 -m unittest tests/test_data_rules.py
```

These tests use in-memory sample data and do not require network access. They cover carry-forward valuation, execution-price strictness, AI Analyst next-trading-day execution, weekend gaps, and SPY DCA cash behavior.
