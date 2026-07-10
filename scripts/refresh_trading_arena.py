#!/usr/bin/env python3
"""Refresh upstream inputs, then build AI Trading Arena JSON data."""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUANT_DIR = Path("~/AI-workplace/quant-learning").expanduser()
QUANT_PYTHON = QUANT_DIR / "venv" / "bin" / "python"
QUANT_DB = QUANT_DIR / "data" / "trading_arena.db"
OPENCLAW_INVESTMENTS = Path("~/.openclaw/workspace-explorer/investments").expanduser()
MAX_AI_ANALYSIS_AGE_DAYS = 10
EXPECTED_SOURCES = {
    "quant_learning",
    "ai_analyst",
    "spy",
    "etf_aggressive",
    "etf_balanced",
    "etf_conservative",
}
VALID_PRICE_STATUSES = {"actual", "carried_forward", "fallback"}


def run(cmd: list[str], cwd: Path) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def refresh_quant_learning(end: str) -> None:
    python = QUANT_PYTHON if QUANT_PYTHON.exists() else Path(sys.executable)
    run(
        [str(python), "daily_runner.py", "--end", end, "--db", str(QUANT_DB)],
        cwd=QUANT_DIR,
    )


def build_data(end: str) -> None:
    run([sys.executable, "scripts/build_trading_arena_data.py", "--end", end], cwd=ROOT)


def load_output(filename: str) -> list[dict]:
    path = ROOT / "data" / filename
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise RuntimeError(f"{filename} must contain a JSON list")
    return rows


def load_health() -> dict:
    path = ROOT / "data" / "health.json"
    health = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(health, dict):
        raise RuntimeError("health.json must contain a JSON object")
    return health


def assert_complete_sources(filename: str, rows: list[dict]) -> None:
    sources = {row.get("source") for row in rows if isinstance(row, dict)}
    missing = EXPECTED_SOURCES - sources
    if missing:
        raise RuntimeError(f"{filename} missing sources: {sorted(missing)}")


def assert_valid_number(filename: str, row: dict, field: str) -> None:
    value = row.get(field)
    if value is None or not isinstance(value, (int, float)) or math.isnan(float(value)) or math.isinf(float(value)):
        raise RuntimeError(f"{filename} has invalid {field}: {row}")


def assert_numeric_quality(filename: str, rows: list[dict]) -> None:
    required = {
        "signals.json": ["price", "shares", "amount", "cash_after"],
        "equity_curve.json": ["total_value", "cash", "positions_value", "total_cost", "return_pct"],
        "holdings.json": ["shares", "cost_price", "current_price", "value", "profit_loss", "return_pct"],
    }.get(filename, [])
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError(f"{filename} contains a non-object row: {row!r}")
        for field in required:
            assert_valid_number(filename, row, field)
        if filename == "holdings.json":
            status = row.get("price_status", "actual")
            if status not in VALID_PRICE_STATUSES:
                raise RuntimeError(f"holdings.json has invalid price_status: {row}")


def assert_equity_dates(equity_rows: list[dict]) -> None:
    latest_by_source = {}
    for row in equity_rows:
        source = row.get("source")
        row_date = row.get("date")
        if source and row_date:
            latest_by_source[source] = max(latest_by_source.get(source, row_date), row_date)
    if set(latest_by_source) != EXPECTED_SOURCES:
        raise RuntimeError(f"Unexpected equity sources: {latest_by_source}")
    latest_dates = set(latest_by_source.values())
    if len(latest_dates) != 1:
        raise RuntimeError(f"Equity latest dates are not aligned: {latest_by_source}")


def latest_stock_analysis_date() -> date | None:
    latest: date | None = None
    for path in OPENCLAW_INVESTMENTS.glob("stock_analysis_*.json"):
        match = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
        if not match:
            continue
        parsed = datetime.strptime(match.group(1), "%Y-%m-%d").date()
        latest = parsed if latest is None else max(latest, parsed)
    return latest


def assert_ai_analysis_fresh(end: str) -> None:
    latest = latest_stock_analysis_date()
    if latest is None:
        raise RuntimeError("No stock_analysis_*.json files found for AI Analyst")
    end_day = datetime.strptime(end, "%Y-%m-%d").date()
    age = (end_day - latest).days
    if age > MAX_AI_ANALYSIS_AGE_DAYS:
        raise RuntimeError(
            f"Latest AI Analyst stock_analysis is stale: {latest.isoformat()} ({age} days old)"
        )



def assert_health(health: dict, equity_rows: list[dict], holdings_rows: list[dict]) -> None:
    latest_market = max(row["date"] for row in equity_rows)
    if health.get("latest_market_date") != latest_market:
        raise RuntimeError(f"health.json latest_market_date mismatch: {health}")
    if health.get("source_count") != len(EXPECTED_SOURCES):
        raise RuntimeError(f"health.json source_count mismatch: {health}")
    for field in ["carried_forward_prices", "latest_carried_forward_prices"]:
        value = health.get(field)
        if value is None or not isinstance(value, int) or value < 0:
            raise RuntimeError(f"health.json invalid {field}: {health}")
    if not health.get("latest_ai_analysis_date"):
        raise RuntimeError(f"health.json missing latest_ai_analysis_date: {health}")


def validate_outputs(end: str) -> None:
    outputs = {
        filename: load_output(filename)
        for filename in ["strategies.json", "signals.json", "equity_curve.json", "holdings.json"]
    }
    for filename, rows in outputs.items():
        assert_complete_sources(filename, rows)
        assert_numeric_quality(filename, rows)
    assert_equity_dates(outputs["equity_curve.json"])
    assert_health(load_health(), outputs["equity_curve.json"], outputs["holdings.json"])
    assert_ai_analysis_fresh(end)
    print("Trading Arena output validation passed.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh Trading Arena upstream data and JSON outputs.")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--skip-quant", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    datetime.strptime(args.end, "%Y-%m-%d")
    if not args.skip_quant:
        refresh_quant_learning(args.end)
    build_data(args.end)
    validate_outputs(args.end)


if __name__ == "__main__":
    main()
