import unittest
from decimal import Decimal

from flatten import METRIC_COLUMNS, flatten_telemetry

ITEM = {
    "schema_version": "1.0", "machine_id": "MCH-000123", "timestamp": "2026-11-14T15:04:05Z",
    "zone_id": "ZONA-NORTE-02", "status": "operating", "location": {"lat": Decimal("-12.0464"), "lon": Decimal("-77.0428")},
    "metrics": {"engine_temp_c": Decimal("92.4"), "vibration_mm_s": 4.8, "pressure_bar": 6.1, "fuel_rate_lph": 31.2,
                "load_kg": 12400, "speed_kmh": 18.5, "engine_rpm": 1850, "operating_hours_total": 3240.7},
    "ingest_message_id": "abc", "ingested_at": "2026-11-14T15:04:07Z", "ttl": 1234567,
}


class FlattenTelemetry(unittest.TestCase):
    def test_columns_match_bigquery_table(self):
        row = flatten_telemetry(ITEM)
        expected = {"schema_version", "machine_id", "timestamp", "ingested_at", "latitude", "longitude", "zone_id", "status", *METRIC_COLUMNS}
        self.assertEqual(set(row), expected)  # ni ttl, ni ingest_message_id, ni objetos anidados

    def test_values_are_json_floats(self):
        row = flatten_telemetry(ITEM)
        self.assertEqual(row["latitude"], -12.0464)
        self.assertIsInstance(row["engine_temp_c"], float)
        self.assertEqual(row["zone_id"], "ZONA-NORTE-02")

    def test_missing_metric_becomes_null(self):
        item = {**ITEM, "metrics": {"engine_temp_c": 90}}
        self.assertIsNone(flatten_telemetry(item)["pressure_bar"])

    def test_non_telemetry_ignored(self):
        self.assertIsNone(flatten_telemetry({"alert_id": "ALT-1"}))

    def test_zone_inside_location_is_accepted(self):
        item = {k: v for k, v in ITEM.items() if k != "zone_id"}
        item["location"] = {"lat": 1, "lon": 2, "zone_id": "ZONA-SUR-01"}
        self.assertEqual(flatten_telemetry(item)["zone_id"], "ZONA-SUR-01")


if __name__ == "__main__":
    unittest.main()
