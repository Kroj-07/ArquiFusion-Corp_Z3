import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.generate import ALERT_TYPES, SEVERITIES, build_dataset, build_sample_alerts


class GeneratorTests(unittest.TestCase):
    def test_contract_sample_shape_and_deterministic_counts(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        machines, telemetry, labels, failures = build_dataset(seed=7, machines=10, days=30, start=start)
        self.assertEqual(len(machines), 10)
        self.assertEqual(len(telemetry), 1200)
        self.assertEqual(len(labels), len(telemetry))
        self.assertTrue(failures)
        self.assertEqual(
            set(telemetry[0]),
            {"schema_version", "machine_id", "timestamp", "location", "status", "metrics", "ingested_at"},
        )
        self.assertEqual(telemetry[0]["schema_version"], "1.0")
        self.assertIn("engine_temp_c", telemetry[0]["metrics"])

    def test_twenty_alerts_cover_contract_enums(self):
        alerts = build_sample_alerts(seed=2)
        self.assertEqual(len(alerts), 20)
        self.assertEqual({alert["type"] for alert in alerts}, set(ALERT_TYPES))
        self.assertEqual({alert["severity"] for alert in alerts}, set(SEVERITIES))
        self.assertTrue(all(alert["score"] <= 100 for alert in alerts))
        common = next(alert for alert in alerts if alert["type"] == "common_cause")
        self.assertIn("common_factor", common)
        self.assertGreaterEqual(len(common["related_machine_ids"]), 2)


if __name__ == "__main__":
    unittest.main()
