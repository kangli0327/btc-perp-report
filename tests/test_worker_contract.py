from pathlib import Path
import unittest


class WorkerContractTest(unittest.TestCase):
    def test_worker_returns_all_positions_and_active_position(self):
        source = Path("workers/okx-account-worker.js").read_text(encoding="utf-8")
        self.assertIn("function parsePositions", source)
        self.assertIn("function selectActivePosition", source)
        self.assertIn("positions: parsedPositions", source)
        self.assertIn("hasHedgedPositions: parsedPositions.length > 1", source)
        self.assertIn("Cache-Control", source)
        self.assertIn("no-store", source)
        self.assertIn("function weeklyPerformance", source)
        self.assertIn("weekProfitCny", source)
        self.assertIn("weeklyLossLimitCny", source)
        self.assertIn("weeklyRiskStatus", source)
        self.assertIn("function macroBrief", source)
        self.assertIn('url.pathname === "/macro"', source)
        self.assertIn("placeholder: true", source)
        self.assertIn("function officialMacroEvents", source)
        self.assertIn("recentReleasedEvents", source)
        self.assertIn("upcomingEvents", source)
        self.assertIn("RECENT_MACRO_KEEP_MS", source)
        self.assertIn("美国7月CPI通胀数据", source)
        self.assertIn("macroStatus", source)


if __name__ == "__main__":
    unittest.main()
