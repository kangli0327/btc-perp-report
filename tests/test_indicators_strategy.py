import unittest

from btc_report.advice import build_advice
from btc_report.config import PositionConfig, PositionSide, PreferenceConfig
from btc_report.indicators import Indicators, macd, rsi


def pref() -> PreferenceConfig:
    return PreferenceConfig(
        style="冲刺",
        max_total_notional_pct=8,
        max_single_add_pct=0.15,
        max_drawdown_pct=0.12,
        risk_per_trade_pct=0.02,
        allow_long=True,
        allow_short=True,
        preferred_timeframe="15m",
    )


class IndicatorStrategyTest(unittest.TestCase):
    def test_rsi_rises_in_uptrend_and_falls_in_downtrend(self):
        up = [100 + i for i in range(40)]
        down = [140 - i for i in range(40)]
        self.assertGreater(rsi(up), 70)
        self.assertLess(rsi(down), 30)

    def test_macd_histogram_tracks_direction(self):
        up = [100 + i * 0.8 for i in range(60)]
        down = [150 - i * 0.8 for i in range(60)]
        self.assertGreater(macd(up)[2], 0)
        self.assertLess(macd(down)[2], 0)

    def test_strategy_outputs_short_only_when_multi_timeframe_bearish(self):
        ind = Indicators(
            latest_price=60000,
            change_15m_pct=-0.4,
            change_1h_pct=-1.0,
            change_4h_pct=-1.8,
            change_24h_pct=-3.0,
            high_24h=62000,
            low_24h=59000,
            volatility_24h_pct=0.8,
            volume_4h_ratio=1.4,
            funding_rate_pct=0.03,
            avg_funding_rate_pct=0.02,
            open_interest=100000,
            basis_pct=0.01,
            trend="下降趋势",
            risk_level="中",
            support=59500,
            resistance=61000,
            warnings=[],
            rsi_15m=42,
            rsi_1h=43,
            rsi_4h=40,
            macd_hist_15m=-25,
            macd_hist_1h=-55,
            macd_hist_4h=-80,
            volume_ratio_15m=1.6,
            volume_ratio_1h=1.3,
            volume_ratio_4h=1.2,
            ma_state_4h="空头排列",
        )
        advice = build_advice(PositionConfig(10000, 5000, PositionSide(), PositionSide()), pref(), ind)
        self.assertEqual(advice.trade_mode, "只做空")
        self.assertGreater(advice.short_score, advice.long_score)

    def test_strategy_outputs_long_only_when_multi_timeframe_bullish(self):
        ind = Indicators(
            latest_price=60000,
            change_15m_pct=0.4,
            change_1h_pct=1.0,
            change_4h_pct=1.8,
            change_24h_pct=3.0,
            high_24h=61000,
            low_24h=58000,
            volatility_24h_pct=0.8,
            volume_4h_ratio=1.4,
            funding_rate_pct=0.0,
            avg_funding_rate_pct=0.0,
            open_interest=100000,
            basis_pct=0.01,
            trend="上升趋势",
            risk_level="中",
            support=59000,
            resistance=60500,
            warnings=[],
            rsi_15m=58,
            rsi_1h=59,
            rsi_4h=62,
            macd_hist_15m=25,
            macd_hist_1h=55,
            macd_hist_4h=80,
            volume_ratio_15m=1.6,
            volume_ratio_1h=1.3,
            volume_ratio_4h=1.2,
            ma_state_4h="多头排列",
        )
        advice = build_advice(PositionConfig(10000, 5000, PositionSide(), PositionSide()), pref(), ind)
        self.assertEqual(advice.trade_mode, "只做多")
        self.assertGreater(advice.long_score, advice.short_score)

    def test_liquidation_risk_blocks_new_trades(self):
        ind = Indicators(
            latest_price=60000,
            change_15m_pct=0,
            change_1h_pct=0,
            change_4h_pct=0,
            change_24h_pct=0,
            high_24h=61000,
            low_24h=59000,
            volatility_24h_pct=0.2,
            volume_4h_ratio=1.0,
            funding_rate_pct=0,
            avg_funding_rate_pct=0,
            open_interest=100000,
            basis_pct=0,
            trend="震荡/方向不明",
            risk_level="低",
            support=59500,
            resistance=60500,
            warnings=[],
        )
        pos = PositionConfig(10000, 5000, PositionSide(), PositionSide(quantity_btc=0.2, entry_price=59000), liquidation_price=60400)
        advice = build_advice(pos, pref(), ind)
        self.assertEqual(advice.trade_mode, "禁止交易")


if __name__ == "__main__":
    unittest.main()
