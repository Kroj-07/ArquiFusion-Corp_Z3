import os
import re
from functools import cached_property


_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]+$")


class BigQueryRepository:
    def __init__(self, project, dataset, client=None):
        if not _IDENTIFIER.fullmatch(project) or not _IDENTIFIER.fullmatch(dataset):
            raise ValueError("Invalid BigQuery project or dataset identifier")
        self.project = project
        self.dataset = dataset
        self._client = client

    @cached_property
    def client(self):
        if self._client is None:
            from google.cloud import bigquery
            self._client = bigquery.Client(project=self.project)
        return self._client

    def _rows(self, sql, parameters=()):
        from google.cloud import bigquery
        if not isinstance(parameters, (list, tuple)):
            parameters = [parameters]
        config = bigquery.QueryJobConfig(query_parameters=list(parameters))
        return [dict(row.items()) for row in self.client.query(sql, job_config=config).result()]

    @property
    def prefix(self):
        return f"`{self.project}.{self.dataset}"

    def fuel(self):
        return self._rows(f"""
            SELECT machine_id, actual_lph, expected_lph, delta_pct
            FROM {self.prefix}.fuel_analytics` ORDER BY ABS(delta_pct) DESC
        """)

    def utilization(self):
        return self._rows(f"""
            SELECT machine_id, sampled_operating_pct, cost_index
            FROM {self.prefix}.utilization_analytics`
            ORDER BY sampled_operating_pct DESC
        """)

    def maintenance(self):
        return self._rows(f"""
            SELECT machine_id, remaining_operating_hours, basis
            FROM {self.prefix}.maintenance_predictions`
            ORDER BY remaining_operating_hours
        """)

    def common_cause(self):
        return self._rows(f"""
            SELECT zone_id, machine_ids, hypothesis, FALSE AS confirmed
            FROM {self.prefix}.common_cause_analytics`
            ORDER BY zone_id
        """)

    def spare_parts(self, zone_id=None):
        parameters = ()
        filter_sql = ""
        if zone_id:
            filter_sql = "WHERE zone_id = @zone_id"
            parameters = self._string_parameter("zone_id", zone_id)
        return self._rows(f"""
            SELECT zone_id, component, expected_demand, suggested_min_stock, irregular
            FROM {self.prefix}.spare_parts_analytics` {filter_sql}
            ORDER BY expected_demand DESC
        """, parameters)

    def risk(self, limit):
        return self._rows(f"""
            SELECT machine_id, score, suspected_component, confidence, generated_at
            FROM {self.prefix}.risk_predictions`
            ORDER BY score DESC
            LIMIT @limit
        """, self._integer_parameter("limit", limit))

    def alert(self, alert_id):
        return self._rows(f"""
            SELECT alert_id, machine_id, zone_id, created_at, type, severity, score,
                   confidence, summary, suspected_component, recommended_action,
                   evidence, related_machine_ids, common_factor
            FROM {self.prefix}.alerts_out`
            WHERE alert_id = @alert_id
            LIMIT 1
        """, self._string_parameter("alert_id", alert_id))

    def pending_alerts(self, limit):
        return self._rows(f"""
            SELECT alert_id, machine_id, zone_id, created_at, type, severity, score,
                   confidence, summary, suspected_component, recommended_action,
                   evidence, related_machine_ids, common_factor
            FROM {self.prefix}.alerts_out`
            WHERE delivered_at IS NULL AND IFNULL(is_sample, FALSE) = FALSE
            ORDER BY created_at
            LIMIT @limit
        """, (self._integer_parameter("limit", limit),))

    def mark_alert_delivered(self, alert_id):
        from google.cloud import bigquery
        query = f"""
            UPDATE {self.prefix}.alerts_out`
            SET delivered_at = COALESCE(delivered_at, CURRENT_TIMESTAMP())
            WHERE alert_id = @alert_id AND IFNULL(is_sample, FALSE) = FALSE
        """
        config = bigquery.QueryJobConfig(
            query_parameters=[self._string_parameter("alert_id", alert_id)]
        )
        self.client.query(query, job_config=config).result()

    def history(self, machine_id, limit=20):
        return self._rows(f"""
            SELECT timestamp, engine_temp_c, vibration_mm_s, pressure_bar, fuel_rate_lph
            FROM {self.prefix}.telemetry`
            WHERE machine_id = @machine_id
            ORDER BY timestamp DESC LIMIT @limit
        """, (
            self._string_parameter("machine_id", machine_id),
            self._integer_parameter("limit", limit),
        ))

    @staticmethod
    def _string_parameter(name, value):
        from google.cloud import bigquery
        return bigquery.ScalarQueryParameter(name, "STRING", value)

    @staticmethod
    def _integer_parameter(name, value):
        from google.cloud import bigquery
        return bigquery.ScalarQueryParameter(name, "INT64", value)

    @classmethod
    def from_environment(cls):
        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        dataset = os.environ.get("BIGQUERY_DATASET", "fleet")
        if not project:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT must be configured")
        return cls(project, dataset)
