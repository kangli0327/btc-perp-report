from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from btc_report.daily_report import build_daily_report, daily_report_date, load_recent_daily_reports, render_daily_card
from btc_report.macro_events import MacroBrief, MacroEvent


CN_TZ = ZoneInfo("Asia/Shanghai")


class DailyReportTest(unittest.TestCase):
    def test_daily_report_date_rolls_before_8am(self):
        self.assertEqual(daily_report_date(datetime(2026, 9, 11, 7, 59, tzinfo=CN_TZ)), "2026-09-10")
        self.assertEqual(daily_report_date(datetime(2026, 9, 11, 8, 0, tzinfo=CN_TZ)), "2026-09-11")

    def test_daily_report_generates_card_and_archive_json(self):
        indicators = SimpleNamespace(
            latest_price=76740.0,
            resistance=77212.0,
            support=76394.0,
            atr_15m=220.0,
            risk_level="中",
        )
        position = SimpleNamespace(
            long=SimpleNamespace(quantity_btc=0.5, entry_price=79175.0, leverage=100),
            short=SimpleNamespace(quantity_btc=0.0, entry_price=0.0, leverage=100),
        )
        advice = SimpleNamespace(
            trade_mode="只管理持仓",
            long_score=35,
            short_score=84,
            risk_score=20,
            strategy_reason="下降趋势里等待反弹受阻。",
        )
        event = MacroEvent(
            title="美国8月CPI通胀数据",
            source="BLS",
            url="https://www.bls.gov/",
            scheduled_at=datetime(2026, 9, 11, 20, 30, tzinfo=CN_TZ),
            impact="高",
            btc_view="CPI影响BTC波动。",
            btc_direction="待公布：低于预期偏利多，高于预期偏利空。",
        )
        macro = MacroBrief(
            window_start=datetime(2026, 9, 11, 8, 0, tzinfo=CN_TZ),
            window_end=datetime(2026, 9, 18, 8, 0, tzinfo=CN_TZ),
            events=[event],
            summary="未来7天识别到1个宏观事件。",
            forecast="待公布。",
            warnings=[],
        )
        with TemporaryDirectory() as temp:
            with patch("btc_report.daily_report._fetch_worker_json", return_value=(None, "测试降级")):
                report = build_daily_report(
                    datetime(2026, 9, 11, 8, 1, tzinfo=CN_TZ),
                    indicators,  # type: ignore[arg-type]
                    position,  # type: ignore[arg-type]
                    advice,  # type: ignore[arg-type]
                    macro,
                    Path(temp),
                )
            card = render_daily_card(report, load_recent_daily_reports(Path(temp)))
            self.assertIn("加密日报", card)
            self.assertIn("BTC 标记价", card)
            self.assertTrue((Path(temp) / "2026-09-11.json").exists())


if __name__ == "__main__":
    unittest.main()
