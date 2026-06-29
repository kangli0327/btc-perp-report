import unittest

from btc_report.advice import build_advice
from btc_report.config import PositionConfig, PositionSide, PreferenceConfig
from btc_report.indicators import Indicators


class AdviceTest(unittest.TestCase):
    def test_build_advice_for_uptrend_has_long_plan(self):
        position = PositionConfig(
            account_equity_usdt=10000,
            available_margin_usdt=6000,
            long=PositionSide(quantity_btc=0.1, entry_price=60000, leverage=3, stop_loss=58000, take_profit=70000),
            short=PositionSide(),
        )
        pref = PreferenceConfig(
            style="aggressive_trend_following",
            max_total_notional_pct=1.8,
            max_single_add_pct=0.35,
            max_drawdown_pct=0.18,
            risk_per_trade_pct=0.03,
            allow_long=True,
            allow_short=True,
            preferred_timeframe="4h",
        )
        indicators = Indicators(
            latest_price=65000,
            change_4h_pct=1.2,
            change_24h_pct=4.0,
            high_24h=66000,
            low_24h=62000,
            volatility_24h_pct=1.5,
            volume_4h_ratio=1.1,
            funding_rate_pct=0.01,
            avg_funding_rate_pct=0.01,
            open_interest=100000,
            basis_pct=0.02,
            trend="上升趋势",
            risk_level="中",
            support=63000,
            resistance=66000,
            warnings=[],
        )

        advice = build_advice(position, pref, indicators)

        self.assertEqual(advice.bias, "偏多")
        self.assertIn("止损", advice.long_plan)
        self.assertIn("止盈", advice.long_plan)
        self.assertTrue(advice.action_items)


if __name__ == "__main__":
    unittest.main()
