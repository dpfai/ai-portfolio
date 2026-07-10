import unittest
import pandas as pd

from scripts import build_trading_arena_data as arena


class TradingArenaDataRulesTest(unittest.TestCase):
    def test_valuation_can_carry_forward_but_execution_cannot(self):
        prices = pd.DataFrame(
            {"ABC": [10.0, None, 12.0]},
            index=pd.to_datetime(["2026-06-15", "2026-06-16", "2026-06-17"]),
        )
        self.assertEqual(arena.valuation_price_on(prices, "ABC", "2026-06-16"), (10.0, "carried_forward"))
        self.assertIsNone(arena.execution_price_on(prices, "ABC", "2026-06-16"))
        self.assertEqual(arena.execution_price_on(prices, "ABC", "2026-06-16", 11.0), 11.0)

    def test_ai_analyst_executes_on_next_trading_day(self):
        prices = pd.DataFrame(
            {"ABC": [100.0, 110.0]},
            index=pd.to_datetime(["2026-06-19", "2026-06-22"]),
        )
        items = [
            {
                "date": "2026-06-19",
                "code": "ABC",
                "ai_analysis": {"operation_advice": "买入", "confidence_level": "高"},
                "technical_indicators": {"buy_signal": "买入", "trend_status": "多头排列"},
            }
        ]
        signals, equity, holdings = arena.build_ai_analyst(prices, items)
        self.assertEqual([row["date"] for row in signals], ["2026-06-22"])
        self.assertEqual(signals[0]["price"], 110.0)
        self.assertFalse([row for row in holdings if row["date"] == "2026-06-19"])
        self.assertTrue([row for row in holdings if row["date"] == "2026-06-22"])
        self.assertEqual([row["date"] for row in equity], ["2026-06-19", "2026-06-22"])

    def test_weekend_dates_are_not_generated(self):
        prices = pd.DataFrame(
            {"SPY": [100.0, 101.0]},
            index=pd.to_datetime(["2026-06-19", "2026-06-22"]),
        )
        _signals, equity, holdings = arena.build_spy(prices)
        dates = {row["date"] for row in equity + holdings}
        self.assertEqual(dates, {"2026-06-19", "2026-06-22"})
        self.assertNotIn("2026-06-20", dates)
        self.assertNotIn("2026-06-21", dates)

    def test_spy_dca_invests_available_cash(self):
        prices = pd.DataFrame(
            {"SPY": [100.0, 105.0]},
            index=pd.to_datetime(["2026-06-15", "2026-06-16"]),
        )
        signals, equity, _holdings = arena.build_spy(prices)
        self.assertEqual([row["amount"] for row in signals], [10000.0, 500.0])
        self.assertTrue(all(abs(row["cash"]) < 1e-9 for row in equity))
        self.assertEqual(equity[-1]["total_cost"], 10500.0)


if __name__ == "__main__":
    unittest.main()
