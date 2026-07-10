#!/usr/bin/env python3
"""Build AI Trading Arena static JSON data from OpenClaw outputs.

This script intentionally lives in the ai-portfolio repository. OpenClaw
agents produce upstream research and portfolio files; this script owns the
website-ready JSON contract under data/.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OPENCLAW_INVESTMENTS = Path("~/.openclaw/workspace-explorer/investments").expanduser()
ETF_TRACKING = OPENCLAW_INVESTMENTS / "portfolio_data" / "portfolio_tracking.json"
QUANT_DB = Path("~/AI-workplace/quant-learning/data/trading_arena.db").expanduser()

START_DATE = date(2026, 6, 15)
INITIAL_CASH = 10_000.0
WEEKLY_CONTRIBUTION = 500.0
DCA_WEEKDAY = 1  # Tuesday

ETF_SOURCE_MAP = {
    "组合A-激进型": ("etf_aggressive", "DCA Aggressive"),
    "组合B-平衡型": ("etf_balanced", "DCA Balanced"),
    "组合C-稳健型": ("etf_conservative", "DCA Conservative"),
}
ETF_ALLOCATIONS = {
    "etf_aggressive": {"VOO": 0.425, "VGT": 0.425, "SMH": 0.15},
    "etf_balanced": {"VOO": 0.50, "VGT": 0.40, "SMH": 0.10},
    "etf_conservative": {"VOO": 0.60, "VGT": 0.35, "SMH": 0.05},
}


def iso_day(value: Any) -> str:
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def parse_day(value: str | date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


def clean_number(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {k: clean_number(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean_number(v) for v in value]
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(clean_number(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_download(raw: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()
    data = raw
    if isinstance(data.columns, pd.MultiIndex):
        if "Close" in data.columns.get_level_values(0):
            data = data["Close"]
        elif "Close" in data.columns.get_level_values(-1):
            data = data.xs("Close", level=-1, axis=1)
    elif "Close" in data.columns:
        data = data[["Close"]].rename(columns={"Close": tickers[0]})
    data = data.copy()
    data.index = pd.to_datetime(data.index).tz_localize(None).normalize()
    if isinstance(data, pd.Series):
        data = data.to_frame(tickers[0])
    return data.sort_index()


def download_closes(tickers: set[str], start: date, end: date) -> pd.DataFrame:
    tickers = sorted(t for t in tickers if t)
    if not tickers:
        return pd.DataFrame()
    raw = yf.download(
        tickers,
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        auto_adjust=False,
        progress=False,
        group_by="column",
    )
    return normalize_download(raw, tickers)


def price_on(prices: pd.DataFrame, ticker: str, day: str | date, fallback: float | None = None) -> float | None:
    price, _status = price_lookup(prices, ticker, day, fallback=fallback, allow_carry_forward=True)
    return price


def execution_price_on(prices: pd.DataFrame, ticker: str, day: str | date, fallback: float | None = None) -> float | None:
    price, _status = price_lookup(prices, ticker, day, fallback=fallback, allow_carry_forward=False)
    return price


def valuation_price_on(prices: pd.DataFrame, ticker: str, day: str | date) -> tuple[float | None, str]:
    return price_lookup(prices, ticker, day, fallback=None, allow_carry_forward=True)


def price_lookup(
    prices: pd.DataFrame,
    ticker: str,
    day: str | date,
    fallback: float | None = None,
    allow_carry_forward: bool = True,
) -> tuple[float | None, str]:
    if ticker not in prices.columns:
        return fallback, "fallback" if fallback is not None else "missing"
    ts = pd.Timestamp(parse_day(day))
    if ts in prices.index and pd.notna(prices.loc[ts, ticker]):
        return float(prices.loc[ts, ticker]), "actual"
    if allow_carry_forward:
        series = prices.loc[prices.index <= ts, ticker].dropna()
        if not series.empty:
            return float(series.iloc[-1]), "carried_forward"
    return fallback, "fallback" if fallback is not None else "missing"


def trading_days(prices: pd.DataFrame, start: date) -> list[pd.Timestamp]:
    return [idx for idx in prices.index if idx.date() >= start]


def load_quant_learning() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Read existing QuantAI rows from the SQLite DB, falling back to current JSON."""
    if QUANT_DB.exists():
        with sqlite3.connect(QUANT_DB) as conn:
            signals = pd.read_sql_query(
                "SELECT * FROM signals WHERE source='quant_learning' ORDER BY date, id",
                conn,
            ).to_dict("records")
            equity = pd.read_sql_query(
                "SELECT * FROM equity_curve WHERE source='quant_learning' ORDER BY date",
                conn,
            ).to_dict("records")
            holdings = pd.read_sql_query(
                "SELECT * FROM holdings WHERE source='quant_learning' ORDER BY date, ticker",
                conn,
            ).to_dict("records")
        if equity:
            return signals, normalize_contributed_cost(equity), holdings

    return (
        [r for r in load_json(DATA_DIR / "signals.json", []) if r.get("source") == "quant_learning"],
        normalize_contributed_cost([r for r in load_json(DATA_DIR / "equity_curve.json", []) if r.get("source") == "quant_learning"]),
        [r for r in load_json(DATA_DIR / "holdings.json", []) if r.get("source") == "quant_learning"],
    )


def normalize_contributed_cost(equity: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Use cumulative contributed capital as total_cost for strategy comparisons."""
    normalized: list[dict[str, Any]] = []
    for row in sorted(equity, key=lambda r: r["date"]):
        item = dict(row)
        current = parse_day(item["date"])
        contributed = INITIAL_CASH
        cursor = START_DATE + timedelta(days=1)
        while cursor <= current:
            if cursor.weekday() == DCA_WEEKDAY:
                contributed += WEEKLY_CONTRIBUTION
            cursor += timedelta(days=1)
        item["total_cost"] = contributed
        item["return_pct"] = (float(item["total_value"]) - contributed) / contributed
        normalized.append(item)
    return normalized


def rebuild_quant_learning(
    signals: list[dict[str, Any]],
    prices: pd.DataFrame,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Rebuild QuantAI holdings/equity from signals so stale DB snapshots do not leak in."""
    equity: list[dict[str, Any]] = []
    holdings_rows: list[dict[str, Any]] = []
    positions: dict[str, dict[str, float]] = defaultdict(lambda: {"shares": 0.0, "cost": 0.0})
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for signal in signals:
        by_day[signal["date"]].append(signal)

    cash = INITIAL_CASH
    total_contributed = INITIAL_CASH
    for i, day in enumerate(trading_days(prices, START_DATE)):
        day_str = iso_day(day)
        if i > 0 and day.weekday() == DCA_WEEKDAY:
            cash += WEEKLY_CONTRIBUTION
            total_contributed += WEEKLY_CONTRIBUTION

        for signal in sorted(by_day.get(day_str, []), key=lambda r: r["id"]):
            ticker = signal["ticker"]
            price = float(signal.get("price") or execution_price_on(prices, ticker, day_str) or 0)
            shares = float(signal.get("shares") or 0)
            amount = float(signal.get("amount") or shares * price)
            if signal["action"] == "buy" and shares > 0:
                positions[ticker]["shares"] += shares
                positions[ticker]["cost"] += amount
                cash -= amount
            elif signal["action"] == "sell" and shares > 0 and positions[ticker]["shares"] > 0:
                old_shares = positions[ticker]["shares"]
                sold_shares = min(shares, old_shares)
                cost_reduction = positions[ticker]["cost"] * (sold_shares / old_shares)
                positions[ticker]["shares"] -= sold_shares
                positions[ticker]["cost"] -= cost_reduction
                cash += amount
                if positions[ticker]["shares"] <= 1e-10:
                    positions[ticker] = {"shares": 0.0, "cost": 0.0}

        positions_value = 0.0
        for ticker, pos in sorted(positions.items()):
            if pos["shares"] <= 0:
                continue
            px, price_status = valuation_price_on(prices, ticker, day_str)
            if not px:
                continue
            positions_value += pos["shares"] * px
            holdings_rows.append(holding_row(day_str, "quant_learning", ticker, pos["shares"], pos["cost"], px, price_status))
        equity.append(equity_row(day_str, "quant_learning", cash + positions_value, cash, positions_value, total_contributed))

    return equity, holdings_rows


def build_spy(prices: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    signals: list[dict[str, Any]] = []
    equity: list[dict[str, Any]] = []
    holdings_rows: list[dict[str, Any]] = []
    days = trading_days(prices, START_DATE)
    if not days or "SPY" not in prices.columns:
        return signals, equity, holdings_rows

    shares = 0.0
    total_cost = 0.0
    cash = INITIAL_CASH

    for i, day in enumerate(days):
        day_str = iso_day(day)
        price = execution_price_on(prices, "SPY", day_str)
        if not price:
            continue
        if i == 0:
            amount = cash
            shares += amount / price
            total_cost += amount
            cash -= amount
            signals.append(signal_row("spy", day_str, "buy_hold", "buy", "SPY", price, amount / price, amount, cash, "Initial SPY buy-and-hold"))
        elif day.weekday() == DCA_WEEKDAY:
            amount = WEEKLY_CONTRIBUTION
            shares += amount / price
            total_cost += amount
            signals.append(signal_row("spy", day_str, "buy_hold", "buy", "SPY", price, amount / price, amount, cash, "Weekly SPY DCA"))

        value = shares * price
        holdings_rows.append(holding_row(day_str, "spy", "SPY", shares, total_cost, price, "actual"))
        equity.append(equity_row(day_str, "spy", value, cash, value, total_cost))
    return signals, equity, holdings_rows


def build_etf(prices: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    raw = load_json(ETF_TRACKING, {})
    portfolios = raw.get("portfolios", raw)
    signals: list[dict[str, Any]] = []
    equity: list[dict[str, Any]] = []
    holdings_rows: list[dict[str, Any]] = []
    days = trading_days(prices, START_DATE)

    for cn_name, (source, _name) in ETF_SOURCE_MAP.items():
        portfolio = portfolios.get(cn_name)
        if not portfolio:
            continue
        txs = sorted(portfolio.get("transactions", []), key=lambda t: (t.get("date", ""), t.get("etf", "")))
        initial_total = sum(float(tx.get("amount") or 0) for tx in txs if tx.get("type") == "initial_investment")
        initial_scale = INITIAL_CASH / initial_total if initial_total > 0 else 1.0
        positions: dict[str, dict[str, float]] = defaultdict(lambda: {"shares": 0.0, "cost": 0.0})
        cash = INITIAL_CASH
        total_contributed = INITIAL_CASH
        contributed_dates: set[str] = set()
        tx_index = 0
        for day in days:
            day_str = iso_day(day)
            while tx_index < len(txs) and txs[tx_index].get("date", "") <= day_str:
                tx = txs[tx_index]
                ticker = tx.get("etf")
                amount = float(tx.get("amount") or 0)
                tx_price = float(tx.get("price") or 0)
                shares = float(tx.get("shares") or (amount / tx_price if tx_price else 0))
                if tx.get("type") == "initial_investment":
                    amount *= initial_scale
                    shares *= initial_scale
                if ticker and amount > 0 and shares > 0:
                    if tx.get("type") == "weekly_investment" and tx["date"] not in contributed_dates:
                        cash += WEEKLY_CONTRIBUTION
                        total_contributed += WEEKLY_CONTRIBUTION
                        contributed_dates.add(tx["date"])
                    positions[ticker]["shares"] += shares
                    positions[ticker]["cost"] += amount
                    cash -= amount
                    signals.append(signal_row(source, tx["date"], "dca", "buy", ticker, tx_price, shares, amount, cash, tx.get("type", "ETF DCA")))
                tx_index += 1

            positions_value = 0.0
            for ticker, pos in sorted(positions.items()):
                if pos["shares"] <= 0:
                    continue
                px, price_status = valuation_price_on(prices, ticker, day_str)
                if not px:
                    continue
                positions_value += pos["shares"] * px
                holdings_rows.append(holding_row(day_str, source, ticker, pos["shares"], pos["cost"], px, price_status))
            if positions_value > 0:
                equity.append(equity_row(day_str, source, cash + positions_value, cash, positions_value, total_contributed))

    return signals, equity, holdings_rows


def analysis_date_from_path(path: Path) -> str | None:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    return match.group(1) if match else None


def load_analysis_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    paths = sorted(OPENCLAW_INVESTMENTS.glob("stock_analysis_*.json"))
    result_path = OPENCLAW_INVESTMENTS.parent / "stock_analysis_results.json"
    if result_path.exists():
        paths.append(result_path)

    for path in paths:
        fallback_date = analysis_date_from_path(path)
        data = load_json(path, [])
        records: list[dict[str, Any]]
        if isinstance(data, list):
            records = [r for r in data if isinstance(r, dict)]
        elif isinstance(data, dict):
            records = [r for r in data.get("stocks", data.get("results", [])) if isinstance(r, dict)]
        else:
            continue
        for record in records:
            item = dict(record)
            item["date"] = item.get("date") or fallback_date
            if item.get("date"):
                items.append(item)
    return sorted(items, key=lambda r: (r.get("date", ""), r.get("code", "")))


def action_from_analysis(stock: dict[str, Any]) -> str | None:
    ai = stock.get("ai_analysis") or {}
    tech = stock.get("technical_indicators") or {}
    analysis = stock.get("analysis") or {}
    text = " ".join(
        str(v)
        for v in [
            ai.get("operation_advice"),
            tech.get("buy_signal"),
            analysis.get("suggestion"),
        ]
        if v is not None
    )
    if any(word in text for word in ["强烈买入", "买入", "加仓"]):
        return "buy"
    if any(word in text for word in ["卖出", "减仓", "清仓"]):
        return "sell"
    return None


def stock_price_hint(stock: dict[str, Any]) -> float | None:
    for path in [
        ("current_price",),
        ("technical_indicators", "current_price"),
        ("price_data", "current_price"),
    ]:
        value: Any = stock
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return None


def next_trading_day_after(days: list[pd.Timestamp], decision_day: str) -> str | None:
    decision = parse_day(decision_day)
    for day in days:
        if day.date() > decision:
            return iso_day(day)
    return None


def build_ai_analyst(prices: pd.DataFrame, items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    signals: list[dict[str, Any]] = []
    equity: list[dict[str, Any]] = []
    holdings_rows: list[dict[str, Any]] = []
    days = trading_days(prices, START_DATE)
    by_execution_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        decision_date = item.get("date")
        if not decision_date or decision_date < START_DATE.isoformat():
            continue
        execution_date = next_trading_day_after(days, decision_date)
        if not execution_date:
            continue
        executable = dict(item)
        executable["decision_date"] = decision_date
        by_execution_day[execution_date].append(executable)

    cash = INITIAL_CASH
    total_contributed = INITIAL_CASH
    positions: dict[str, dict[str, float]] = defaultdict(lambda: {"shares": 0.0, "cost": 0.0})

    for i, day in enumerate(days):
        day_str = iso_day(day)
        if i > 0 and day.weekday() == DCA_WEEKDAY:
            cash += WEEKLY_CONTRIBUTION
            total_contributed += WEEKLY_CONTRIBUTION

        for stock in by_execution_day.get(day_str, []):
            ticker = stock.get("code")
            if not ticker:
                continue
            action = action_from_analysis(stock)
            if not action:
                continue
            px = execution_price_on(prices, ticker, day_str, stock_price_hint(stock))
            if not px:
                continue
            reason = analysis_reason(stock, action)
            if action == "buy" and cash > 1:
                amount = min(cash * 0.30, cash)
                shares = amount / px
                positions[ticker]["shares"] += shares
                positions[ticker]["cost"] += amount
                cash -= amount
                signals.append(signal_row("ai_analyst", day_str, "llm_analysis", "buy", ticker, px, shares, amount, cash, reason))
            elif action == "sell" and positions[ticker]["shares"] > 0:
                shares = positions[ticker]["shares"]
                amount = shares * px
                cash += amount
                signals.append(signal_row("ai_analyst", day_str, "llm_analysis", "sell", ticker, px, shares, amount, cash, reason))
                positions[ticker] = {"shares": 0.0, "cost": 0.0}

        positions_value = 0.0
        for ticker, pos in sorted(positions.items()):
            if pos["shares"] <= 0:
                continue
            px, price_status = valuation_price_on(prices, ticker, day_str)
            if not px:
                continue
            positions_value += pos["shares"] * px
            holdings_rows.append(holding_row(day_str, "ai_analyst", ticker, pos["shares"], pos["cost"], px, price_status))
        equity.append(equity_row(day_str, "ai_analyst", cash + positions_value, cash, positions_value, total_contributed))

    return signals, equity, holdings_rows


def translate_signal_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    mapping = [
        ("强烈买入", "strong buy"),
        ("买入", "buy"),
        ("加仓", "add"),
        ("卖出", "sell"),
        ("减仓", "reduce"),
        ("清仓", "exit"),
        ("持有", "hold"),
        ("观望", "watch"),
        ("强势多头", "strong bullish trend"),
        ("多头排列", "bullish alignment"),
        ("弱势多头", "weak bullish trend"),
        ("强势空头", "strong bearish trend"),
        ("空头排列", "bearish alignment"),
        ("弱势空头", "weak bearish trend"),
        ("震荡", "range-bound"),
        ("高", "high"),
        ("中", "medium"),
        ("低", "low"),
    ]
    for chinese, english in mapping:
        if chinese in text:
            return english
    if text.isascii():
        return text
    return None


def analysis_reason(stock: dict[str, Any], action: str) -> str:
    ai = stock.get("ai_analysis") or {}
    tech = stock.get("technical_indicators") or {}
    analysis = stock.get("analysis") or {}
    parts = [f"OpenClaw weekly analysis: {action.upper()} signal"]

    advice = translate_signal_text(ai.get("operation_advice") or analysis.get("suggestion"))
    if advice:
        parts.append(f"advice={advice}")

    technical_signal = translate_signal_text(tech.get("buy_signal"))
    if technical_signal:
        parts.append(f"technical={technical_signal}")

    trend = translate_signal_text(tech.get("trend_status"))
    if trend:
        parts.append(f"trend={trend}")

    score = tech.get("signal_score") or analysis.get("score")
    if isinstance(score, (int, float)):
        parts.append(f"score={score:.0f}/100")

    confidence = translate_signal_text(ai.get("confidence_level"))
    if confidence:
        parts.append(f"confidence={confidence}")

    target = ai.get("target_price") or analysis.get("target_price_suggested")
    if target not in (None, ""):
        parts.append(f"target={target}")

    stop_loss = ai.get("stop_loss") or analysis.get("stop_loss")
    if stop_loss not in (None, ""):
        parts.append(f"stop={stop_loss}")

    return "; ".join(parts)[:240]


def signal_row(source: str, day: str, strategy: str, action: str, ticker: str, price: float, shares: float, amount: float, cash: float, reason: str) -> dict[str, Any]:
    return {
        "id": f"{source}_{day}_{ticker}_{action}",
        "date": day,
        "source": source,
        "strategy": strategy,
        "action": action,
        "ticker": ticker,
        "price": price,
        "shares": shares,
        "amount": amount,
        "cash_after": cash,
        "reason": reason,
    }


def holding_row(day: str, source: str, ticker: str, shares: float, total_cost: float, price: float, price_status: str = "actual") -> dict[str, Any]:
    value = shares * price
    profit_loss = value - total_cost
    return {
        "date": day,
        "source": source,
        "ticker": ticker,
        "shares": shares,
        "cost_price": total_cost / shares if shares else 0.0,
        "current_price": price,
        "value": value,
        "price_status": price_status,
        "profit_loss": profit_loss,
        "return_pct": profit_loss / total_cost if total_cost else 0.0,
    }


def equity_row(day: str, source: str, total_value: float, cash: float, positions_value: float, total_cost: float) -> dict[str, Any]:
    return {
        "date": day,
        "source": source,
        "total_value": total_value,
        "cash": cash,
        "positions_value": positions_value,
        "total_cost": total_cost,
        "return_pct": (total_value - total_cost) / total_cost if total_cost else 0.0,
    }


def strategies_payload() -> list[dict[str, Any]]:
    return [
        {
            "source": "quant_learning",
            "name": "QuantAI Four-Vote Composite",
            "tickers": ["SPY", "QQQ", "VOO", "VGT", "SMH"],
            "initial_cash": INITIAL_CASH,
            "weekly_contribution": WEEKLY_CONTRIBUTION,
            "sub_strategies": ["MA20/MA50 crossover", "RSI mean reversion", "Bollinger Bands", "ML direction classifier"],
        },
        {
            "source": "ai_analyst",
            "name": "AI Analyst (OpenClaw 海岩)",
            "tickers": "OpenClaw stock_analysis universe",
            "initial_cash": INITIAL_CASH,
            "weekly_contribution": WEEKLY_CONTRIBUTION,
            "sub_strategies": ["OpenClaw technical scan", "LLM operation advice"],
        },
        {
            "source": "spy",
            "name": "SPY Buy & Hold",
            "tickers": ["SPY"],
            "initial_cash": INITIAL_CASH,
            "weekly_contribution": WEEKLY_CONTRIBUTION,
            "sub_strategies": ["Initial all-in buy", "Tuesday DCA"],
        },
        *[
            {
                "source": source,
                "name": name,
                "tickers": list(ETF_ALLOCATIONS[source].keys()),
                "initial_cash": None,
                "weekly_contribution": WEEKLY_CONTRIBUTION,
                "allocations": ETF_ALLOCATIONS[source],
                "sub_strategies": ["OpenClaw ETF portfolio tracker", "Tuesday DCA"],
            }
            for _cn, (source, name) in ETF_SOURCE_MAP.items()
        ],
    ]


def validate(equity: list[dict[str, Any]]) -> None:
    expected = {"quant_learning", "ai_analyst", "spy", "etf_aggressive", "etf_balanced", "etf_conservative"}
    actual = {row["source"] for row in equity}
    missing = expected - actual
    if missing:
        raise RuntimeError(f"Missing equity sources: {sorted(missing)}")


def latest_date(rows: list[dict[str, Any]]) -> str | None:
    dates = sorted(row.get("date") for row in rows if row.get("date"))
    return dates[-1] if dates else None


def health_payload(
    equity: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    analysis_items: list[dict[str, Any]],
) -> dict[str, Any]:
    latest_holdings_date = latest_date(holdings)
    latest_holdings = [row for row in holdings if row.get("date") == latest_holdings_date]
    latest_ai_analysis = latest_date(analysis_items)
    return {
        "latest_market_date": latest_date(equity),
        "latest_signal_date": latest_date(signals),
        "latest_ai_analysis_date": latest_ai_analysis,
        "source_count": len({row.get("source") for row in equity if row.get("source")}),
        "carried_forward_prices": sum(1 for row in holdings if row.get("price_status") == "carried_forward"),
        "latest_carried_forward_prices": sum(1 for row in latest_holdings if row.get("price_status") == "carried_forward"),
    }



def insights_payload(equity: list[dict[str, Any]], holdings: list[dict[str, Any]], signals: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate long-term performance insights with holding-level attribution."""
    if not equity:
        return {"date": date.today().isoformat(), "error": "no equity data"}

    source_names = {
        "quant_learning": "Quant AI",
        "ai_analyst": "AI Analyst",
        "spy": "SPY Benchmark",
        "etf_aggressive": "DCA Aggressive",
        "etf_balanced": "DCA Balanced",
        "etf_conservative": "DCA Conservative",
    }

    strategy_profiles = {
        "quant_learning": {
            "approach": "Four-vote composite (MA/RSI/Bollinger/Random Forest)",
            "strengths": "combines trend-following, mean reversion, volatility breakout, and ML prediction",
            "weaknesses": "systematic rules may miss nuanced market context",
        },
        "ai_analyst": {
            "approach": "LLM-based market analysis with selective stock picks",
            "strengths": "active risk management with cash positioning",
            "weaknesses": "weekly decision frequency, slower reaction to sudden moves",
        },
        "spy": {
            "approach": "Passive S&P 500 benchmark",
            "strengths": "broad market diversification",
            "weaknesses": "no active risk management",
        },
        "etf_aggressive": {
            "approach": "DCA into tech-heavy ETFs (VGT 42.5%, SMH 15%, VOO 42.5%)",
            "strengths": "captures tech sector growth trends",
            "weaknesses": "concentrated tech exposure vulnerable to sector rotation",
        },
        "etf_balanced": {
            "approach": "DCA into diversified ETF portfolio",
            "strengths": "balanced allocation reduces volatility",
            "weaknesses": "lower upside potential",
        },
        "etf_conservative": {
            "approach": "DCA into conservative ETF portfolio",
            "strengths": "lowest volatility, capital preservation",
            "weaknesses": "lowest expected return",
        },
    }

    latest_date = max(row["date"] for row in equity)

    # Calculate metrics for each source
    metrics = {}
    for source in source_names:
        rows = sorted([r for r in equity if r["source"] == source], key=lambda r: r["date"])
        if len(rows) < 2:
            continue
        last_val = rows[-1].get("total_value", 0)
        total_cost = rows[-1].get("total_cost", 0)
        total_return_pct = (last_val - total_cost) / total_cost * 100 if total_cost > 0 else 0

        daily_returns = []
        for i in range(1, len(rows)):
            prev = rows[i-1].get("total_value", 0)
            curr = rows[i].get("total_value", 0)
            if prev > 0:
                daily_returns.append((curr - prev) / prev)
        vol = (sum(r**2 for r in daily_returns) / len(daily_returns)) ** 0.5 * (252 ** 0.5) * 100 if daily_returns else 0

        peak = rows[0].get("total_value", 0)
        max_dd = 0
        for r in rows:
            v = r.get("total_value", 0)
            if v > peak:
                peak = v
            dd = (peak - v) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        avg_daily = sum(daily_returns) / len(daily_returns) if daily_returns else 0
        std_daily = (sum((r - avg_daily)**2 for r in daily_returns) / len(daily_returns)) ** 0.5 if daily_returns else 1
        sharpe = (avg_daily / std_daily) * (252 ** 0.5) if std_daily > 0 else 0

        # Holding-level attribution
        src_holdings = [h for h in holdings if h["source"] == source and h["date"] == latest_date]
        sorted_by_pl = sorted(src_holdings, key=lambda h: h.get("profit_loss", 0), reverse=True)

        winners = []
        losers = []
        total_pl = sum(h.get("profit_loss", 0) for h in src_holdings)
        for h in sorted_by_pl:
            pl = h.get("profit_loss", 0)
            ret = h.get("return_pct", 0) * 100
            ticker = h.get("ticker", "?")
            value = h.get("value", 0)
            if pl > 0:
                winners.append({"ticker": ticker, "profit_loss": pl, "return_pct": ret, "value": value})
            elif pl < 0:
                losers.append({"ticker": ticker, "profit_loss": pl, "return_pct": ret, "value": value})

        metrics[source] = {
            "name": source_names.get(source, source),
            "total_return_pct": total_return_pct,
            "volatility": vol,
            "max_drawdown": max_dd,
            "sharpe": sharpe,
            "current_value": last_val,
            "total_invested": total_cost,
            "total_pl": total_pl,
            "winners": winners,
            "losers": losers,
            "days": len(rows),
        }

    if not metrics:
        return {"date": latest_date, "error": "insufficient data"}

    ranked = sorted(metrics.items(), key=lambda x: x[1]["total_return_pct"], reverse=True)
    top_source, top_m = ranked[0]
    bottom_source, bottom_m = ranked[-1]
    top_profile = strategy_profiles.get(top_source, {})
    bottom_profile = strategy_profiles.get(bottom_source, {})

    def build_attribution_reason(m, profile, is_top):
        """Build a data-driven reason based on actual holdings."""
        parts = []
        parts.append(f"{m['total_return_pct']:+.2f}% net return (${m['current_value']:,.0f} vs ${m['total_invested']:,.0f} invested)")

        if is_top:
            parts.append(f"Strategy: {profile.get('approach', 'N/A')}")

        # Holding attribution
        if m["winners"]:
            win_text = ", ".join([f"{w['ticker']} (+${w['profit_loss']:.0f}, +{w['return_pct']:.1f}%)" for w in m["winners"][:3]])
            parts.append(f"Top contributors: {win_text}")
        if m["losers"]:
            lose_text = ", ".join([f"{l['ticker']} (${l['profit_loss']:.0f}, {l['return_pct']:.1f}%)" for l in m["losers"][:3]])
            parts.append(f"Main drags: {lose_text}")

        if is_top:
            if m["winners"] and not m["losers"]:
                parts.append(f"All positions profitable, led by {m['winners'][0]['ticker']}")
            elif m["total_pl"] > 0:
                win_total = sum(w["profit_loss"] for w in m["winners"])
                lose_total = sum(l["profit_loss"] for l in m["losers"]) if m["losers"] else 0
                parts.append(f"Gains (${win_total:.0f}) outweigh losses (${lose_total:.0f})")
            parts.append(f"Risk: {m['volatility']:.1f}% vol, {m['max_drawdown']:.1f}% max drawdown, Sharpe {m['sharpe']:.2f}")
        else:
            parts.append(f"Strategy: {profile.get('approach', 'N/A')}")
            if m["losers"] and not m["winners"]:
                parts.append(f"All positions negative, worst is {m['losers'][0]['ticker']}")
            elif m["total_pl"] < 0:
                lose_total = sum(l["profit_loss"] for l in m["losers"]) if m["losers"] else 0
                win_total = sum(w["profit_loss"] for w in m["winners"]) if m["winners"] else 0
                parts.append(f"Losses (${lose_total:.0f}) exceed gains (${win_total:.0f})")
            parts.append(f"Risk: {m['volatility']:.1f}% vol, {m['max_drawdown']:.1f}% max drawdown, Sharpe {m['sharpe']:.2f}")

        return ". ".join(parts) + "."

    top_reason = build_attribution_reason(top_m, top_profile, is_top=True)
    bottom_reason = build_attribution_reason(bottom_m, bottom_profile, is_top=False)

    ranking = " > ".join([f"{m['name']} ({m['total_return_pct']:+.2f}%)" for _, m in ranked])

    # Latest signals
    latest_signals = [s for s in signals if s["date"] == latest_date][:3]
    signal_text = [f"{source_names.get(s['source'], s['source'])} {s['action']} {s['ticker']}" for s in latest_signals]

    return {
        "date": latest_date,
        "top_performer": {
            "name": top_m["name"],
            "return_pct": f"{top_m['total_return_pct']:+.2f}%",
            "reason": top_reason,
        },
        "bottom_performer": {
            "name": bottom_m["name"],
            "return_pct": f"{bottom_m['total_return_pct']:+.2f}%",
            "reason": bottom_reason,
        },
        "ranking": ranking,
        "latest_signals": signal_text if signal_text else ["No signals on latest date"],
        "metrics": {
            m["name"]: {
                "total_return": f"{m['total_return_pct']:+.2f}%",
                "current_value": f"${m['current_value']:,.0f}",
                "total_invested": f"${m['total_invested']:,.0f}",
                "volatility": f"{m['volatility']:.1f}%",
                "max_drawdown": f"{m['max_drawdown']:.1f}%",
                "sharpe": f"{m['sharpe']:.2f}",
            }
            for _, m in ranked
        },
    }



def main() -> None:
    parser = argparse.ArgumentParser(description="Build AI Trading Arena JSON files.")
    parser.add_argument("--end", default=date.today().isoformat())
    args = parser.parse_args()
    end = parse_day(args.end)

    analysis_items = load_analysis_items()
    tickers = {"SPY", "QQQ", "VOO", "VGT", "SMH"}
    tickers.update(item.get("code") for item in analysis_items if item.get("code"))
    prices = download_closes(tickers, START_DATE, end)

    q_signals, _q_equity, _q_holdings = load_quant_learning()
    q_equity, q_holdings = rebuild_quant_learning(q_signals, prices)
    spy_signals, spy_equity, spy_holdings = build_spy(prices)
    etf_signals, etf_equity, etf_holdings = build_etf(prices)
    ai_signals, ai_equity, ai_holdings = build_ai_analyst(prices, analysis_items)

    signals = sorted(q_signals + spy_signals + etf_signals + ai_signals, key=lambda r: (r["date"], r["source"], r["ticker"], r["id"]))
    equity = sorted(q_equity + spy_equity + etf_equity + ai_equity, key=lambda r: (r["date"], r["source"]))
    holdings = sorted(q_holdings + spy_holdings + etf_holdings + ai_holdings, key=lambda r: (r["date"], r["source"], r["ticker"]))
    validate(equity)

    write_json(DATA_DIR / "strategies.json", strategies_payload())
    write_json(DATA_DIR / "signals.json", signals)
    write_json(DATA_DIR / "equity_curve.json", equity)
    write_json(DATA_DIR / "holdings.json", holdings)
    write_json(DATA_DIR / "health.json", health_payload(equity, holdings, signals, analysis_items))
    write_json(DATA_DIR / "insights.json", insights_payload(equity, holdings, signals))

    print("Generated Trading Arena data:")
    for source in sorted({row["source"] for row in equity}):
        rows = [row for row in equity if row["source"] == source]
        print(f"  {source}: {len(rows)} equity rows, {rows[0]['date']} -> {rows[-1]['date']}")


if __name__ == "__main__":
    main()
