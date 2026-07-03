from pathlib import Path
import unittest


class RenderLivePlanTest(unittest.TestCase):
    def test_live_plan_recalculates_by_position_side(self):
        source = Path("btc_report/render.py").read_text(encoding="utf-8")
        self.assertIn("function buildShortPlan", source)
        self.assertIn("function buildLongPlan", source)
        self.assertIn("function buildFlatPlan", source)
        self.assertIn("function currentPositionPlanKey", source)
        self.assertIn("function getOrBuildLockedPositionPlan", source)
        self.assertIn("function triggerStatusText", source)
        self.assertIn("lockedPositionPlanKey === key", source)
        self.assertIn("simpleTriggerStatus", source)
        self.assertIn("updateSimplePlan(liveLatest, liveSupport, liveResistance, 'OKX账户实时同步')", source)
        self.assertIn("positionConfig.activeSide = 'flat'", source)
        self.assertIn("side === 'short'", source)
        self.assertIn("side === 'long'", source)


if __name__ == "__main__":
    unittest.main()
