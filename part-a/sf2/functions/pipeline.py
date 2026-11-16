"""SF-2 (pipeline analítico) - tareas del Step Functions. Python 3.12, solo stdlib.

Todas las tareas son MOCK por defecto (MOCK=true): BigQuery y el entrenamiento real aún no
existen. Cada handler respeta el contrato de entrada/salida que usa la máquina de estados, de modo
que sustituir un mock por la versión real no obliga a tocar el ASL.

Handlers (módulo `pipeline`):
  list_zones       -> {"zones": [...]}                       zonas a procesar
  sync_bigquery    -> {"rows_synced": n, "tables": {...}}    DynamoDB -> BigQuery (dataset fleet)
  train_zone       -> {"zone_id", "candidate": {...}}        reentrena el modelo de una zona
  evaluate_model   -> {..., "evaluation": {..., "promote"}}  compara candidato vs. modelo vigente
  promote_model    -> {"zone_id", "promoted": true, ...}     registra el candidato como vigente
  backup_to_azure  -> {"copied": bool, "target": "azure://..."}  respaldo A10
  summarize        -> {"zones_total", "promoted", ...}       resumen + métricas EMF

Las métricas se emiten con EMF (emf.py viaja junto al código de la Lambda).
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Dict, List

try:  # empaquetado: emf.py viaja junto al código
    import emf
except ImportError:  # pruebas desde el repo
    try:
        from observability import emf  # type: ignore
    except ImportError:  # sin EMF las métricas se omiten, el pipeline sigue
        class emf:  # type: ignore
            @staticmethod
            def emit(*args: Any, **kwargs: Any) -> Dict[str, Any]:
                return {}

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

NAMESPACE = "ArquiFusion/SF2"
# Tablas del dataset BigQuery `fleet` (contrato v1.3, seccion 11). alerts_out la escribe B;
# model_runs la escribe este pipeline (una fila por zona y corrida) en la version real.
BQ_SYNC_TABLES = ("telemetry", "machines", "technicians", "incidents")
DEFAULT_ZONES = "ZONA-NORTE-01,ZONA-NORTE-02,ZONA-SUR-01"


def _env() -> str:
    return os.environ.get("ENV_NAME", "test")


def _mock() -> bool:
    return os.environ.get("MOCK", "true").lower() == "true"


def _min_improvement() -> float:
    """Mejora relativa mínima del F1 (precision/recall) para promover el candidato."""
    return float(os.environ.get("PROMOTE_MIN_IMPROVEMENT", "0.02"))


def _max_recall_drop() -> float:
    """Caída absoluta máxima de recall tolerada: perder fallas reales es peor que un falso aviso."""
    return float(os.environ.get("MAX_RECALL_DROP", "0.02"))


def _f1(precision: float, recall: float) -> float:
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def _unit(*parts: str) -> float:
    """Número determinista en [0, 1) a partir de textos (mocks reproducibles)."""
    digest = hashlib.sha256("|".join(parts).encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def list_zones(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    override = event.get("zones") if isinstance(event, dict) else None
    if override:
        zones: List[str] = [str(z) for z in override]
    else:
        zones = [z.strip() for z in os.environ.get("ZONES", DEFAULT_ZONES).split(",") if z.strip()]
    if not zones:
        raise ValueError("no hay zonas configuradas")
    return {"zones": zones}


def sync_bigquery(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    """MOCK: la versión real leerá DynamoDB (Telemetry/Alerts) y cargará BigQuery."""
    if event.get("force_failure"):  # permite probar Retry/Catch del ASL
        raise RuntimeError("BigQueryUnavailable: fallo simulado")
    rows = int(_unit("rows", str(event.get("run_id", ""))) * 50000) + 1000
    weights = {"telemetry": 0.90, "machines": 0.02, "technicians": 0.01, "incidents": 0.07}
    tables = {t: int(rows * weights[t]) for t in BQ_SYNC_TABLES}
    # la version real hace upsert con la clave natural (machine_id+timestamp, incident_id) = idempotente
    emf.emit(NAMESPACE, {"RowsSynced": (rows, "Count")}, {"Env": _env()})
    return {"rows_synced": rows, "tables": tables, "mock": _mock()}


def train_zone(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    """MOCK: la versión real lanzará el reentrenamiento en BigQuery ML (Boosted Tree de B)."""
    zone = event["zone_id"]
    run = str(event.get("run_id", ""))
    return {
        "zone_id": zone,
        "run_id": run,
        "candidate": {
            "model_id": "af-model-%s-%s" % (zone.lower(), run[:8] or "local"),
            # Mismas métricas que B guarda en fleet.model_runs (contrato 6.12).
            "precision": round(0.60 + _unit("cand-p", zone, run) * 0.30, 4),
            "recall": round(0.55 + _unit("cand-r", zone, run) * 0.35, 4),
            "mean_lead_time_h": round(24 + _unit("cand-l", zone, run) * 48, 1),
            "mock": _mock(),
        },
    }


def evaluate_model(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    """Compara el candidato con el modelo vigente usando precision/recall (como model_runs de B).

    Promueve solo si el F1 mejora al menos PROMOTE_MIN_IMPROVEMENT (relativo) Y el recall no cae
    más de MAX_RECALL_DROP. `promote` alimenta la Choice del ASL.
    """
    zone = event["zone_id"]
    cand = event["candidate"]
    cur_p = round(0.60 + _unit("curr-p", zone) * 0.25, 4)
    cur_r = round(0.55 + _unit("curr-r", zone) * 0.30, 4)
    cur_f1, cand_f1 = _f1(cur_p, cur_r), _f1(float(cand["precision"]), float(cand["recall"]))
    improvement = round((cand_f1 - cur_f1) / cur_f1, 4)
    threshold = _min_improvement()
    recall_ok = float(cand["recall"]) >= cur_r - _max_recall_drop()
    out = dict(event)
    out["evaluation"] = {
        "current": {"precision": cur_p, "recall": cur_r, "f1": round(cur_f1, 4)},
        "candidate": {"precision": cand["precision"], "recall": cand["recall"], "f1": round(cand_f1, 4)},
        "improvement": improvement,
        "threshold": threshold,
        "recall_ok": recall_ok,
        "promote": improvement >= threshold and recall_ok,
    }
    return out


def promote_model(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    """MOCK: la versión real actualizará el modelo vigente (p. ej. parámetro SSM o alias)."""
    return {
        "zone_id": event["zone_id"],
        "promoted": True,
        "status": "OK",
        "model_id": event["candidate"]["model_id"],
        "improvement": event["evaluation"]["improvement"],
        "mock": _mock(),
    }


def backup_to_azure(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    """MOCK: la version real copia a azure://af-backup/... usando el secreto arquifusion/{env}/azure-sas
    (ya existe part-a/backup/azure_backup: reutilizarlo en vez de duplicar)."""
    return {"copied": True, "target": "azure://af-backup/sf2/%s/" % event.get("run_id", "local"), "mock": _mock()}


def summarize(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    results = event.get("results") or []
    failed = sum(1 for r in results if r.get("status") == "FAILED")
    promoted = sum(1 for r in results if r.get("promoted") is True)
    kept = len(results) - failed - promoted
    emf.emit(
        NAMESPACE,
        {
            "ZonesProcessed": (len(results), "Count"),
            "ZonesPromoted": (promoted, "Count"),
            "ZonesKept": (kept, "Count"),
            "ZonesFailed": (failed, "Count"),
        },
        {"Env": _env()},
        properties={"run_id": str(event.get("run_id", ""))},
    )
    return {
        "run_id": event.get("run_id"),
        "rows_synced": event.get("rows_synced"),
        "zones_total": len(results),
        "promoted": promoted,
        "kept": kept,
        "failed": failed,
    }
