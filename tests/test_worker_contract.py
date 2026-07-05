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


if __name__ == "__main__":
    unittest.main()
