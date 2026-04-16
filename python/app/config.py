import json
import os
import csv
from dataclasses import dataclass
from typing import Any, Dict, Optional

from python.app.weekly_attention_config import (
    ActionThresholds,
    AmountWeightSettings,
    ForecastPriorityWeights,
    NextStepHealthThresholds,
    WeeklyAEInput,
    WeeklyAttentionConfig,
    WeeklyAttentionSettings,
)

DEFAULT_WEEKLY_ATTENTION_SUPPORTED_VIEW = "weekly"
DEFAULT_WEEKLY_ATTENTION_COVERAGE_FACTOR = 1.0
DEFAULT_WEEKLY_ATTENTION_ACTIVE_VIEW = "weekly"

DEFAULT_NEXT_STEP_HEALTH_THRESHOLDS = {
    "good_min": 7.0,
    "watch_min": 5.0,
    "poor_max": 5.0,
}

DEFAULT_ACTION_THRESHOLDS = {
    "monitor_min": 1.0,
    "ae_attention_min": 2.0,
    "manager_attention_min": 3.0,
    "urgent_manager_attention_min": 4.0,
}

DEFAULT_FORECAST_PRIORITY_WEIGHTS = {
    "commit": 1.0,
    "green_upside": 0.8,
    "upside": 0.6,
    "other": 0.3,
}

DEFAULT_AMOUNT_WEIGHT_SETTINGS = {
    "small_max": 25000.0,
    "medium_max": 100000.0,
    "small_weight": 0.5,
    "medium_weight": 1.0,
    "large_weight": 1.5,
}


@dataclass
class LLMConfig:
    backend: str
    model: str
    timeout_sec: int
    retries: int = 0
    ollama_path: Optional[str] = None


def _find_project_root(start_dir: str) -> str:
    """
    Vind project root door vanaf start_dir omhoog te lopen totdat we config.json vinden.
    Werkt op laptop/VM zonder absolute paden.
    """
    cur = os.path.abspath(start_dir)
    while True:
        candidate = os.path.join(cur, "config.json")
        if os.path.exists(candidate):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            raise FileNotFoundError(
                "config.json niet gevonden. Plaats config.json in je project root "
                "(naast data/ en outputs/)."
            )
        cur = parent


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Laad config.json.
    - Als config_path None is: zoek config.json automatisch vanuit deze file locatie.
    """
    if config_path is None:
        project_root = _find_project_root(os.path.dirname(__file__))
        config_path = os.path.join(project_root, "config.json")
    else:
        project_root = os.path.dirname(os.path.abspath(config_path))

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Vul dynamische paden in
    cfg.setdefault("paths", {})
    cfg["paths"]["project_root"] = project_root

    # Resolve data/outputs naar absolute paden
    data_dir = cfg["paths"].get("data_dir", "data")
    outputs_dir = cfg["paths"].get("outputs_dir", "outputs")
    weekly_attention_ae_inputs = cfg["paths"].get(
        "weekly_attention_ae_inputs",
        os.path.join("data", "weekly_attention", "ae_inputs.csv"),
    )
    weekly_attention_settings = cfg["paths"].get(
        "weekly_attention_settings",
        os.path.join("data", "weekly_attention", "settings.json"),
    )

    cfg["paths"]["data_dir_abs"] = os.path.join(project_root, data_dir)
    cfg["paths"]["outputs_dir_abs"] = os.path.join(project_root, outputs_dir)
    cfg["paths"]["weekly_attention_ae_inputs_abs"] = os.path.join(project_root, weekly_attention_ae_inputs)
    cfg["paths"]["weekly_attention_settings_abs"] = os.path.join(project_root, weekly_attention_settings)

    return cfg


def get_llm_config(cfg: Dict[str, Any]) -> LLMConfig:
    llm = cfg.get("llm")
    if not llm:
        raise KeyError("'llm' section ontbreekt in config.json")

    backend = llm.get("backend")
    model = llm.get("model")
    timeout_sec = llm.get("timeout_sec")

    if not backend or not model or timeout_sec is None:
        raise KeyError("'llm.backend', 'llm.model' en 'llm.timeout_sec' zijn verplicht in config.json")

    return LLMConfig(
        backend=backend,
        model=model,
        timeout_sec=int(timeout_sec),
        retries=int(llm.get("retries", 0)),
        ollama_path=llm.get("ollama_path"),
    )


def get_path(cfg: Dict[str, Any], key: str) -> str:
    """
    Handige helper om paden op te vragen.
    keys:
    - data_dir_abs
    - outputs_dir_abs
    """
    paths = cfg.get("paths", {})
    if key not in paths:
        raise KeyError(f"Pad '{key}' niet gevonden in config paths.")
    return paths[key]


def _to_optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_weekly_attention_config(cfg: Dict[str, Any]) -> WeeklyAttentionConfig:
    paths = cfg.get("paths", {}) or {}
    ae_inputs_path = paths.get("weekly_attention_ae_inputs_abs")
    settings_path = paths.get("weekly_attention_settings_abs")

    ae_inputs: Dict[str, WeeklyAEInput] = {}
    if ae_inputs_path and os.path.exists(ae_inputs_path):
        with open(ae_inputs_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ae_name = str((row or {}).get("ae_name", "")).strip()
                if not ae_name:
                    continue
                ae_inputs[ae_name] = WeeklyAEInput(
                    ae_name=ae_name,
                    target=_to_optional_float(row.get("target")),
                    verbal=_to_optional_float(row.get("verbal")),
                    low=_to_optional_float(row.get("low")),
                    high=_to_optional_float(row.get("high")),
                    coverage_factor=_to_optional_float(row.get("coverage_factor")),
                    active_view=(str(row.get("active_view")).strip() or None) if row.get("active_view") is not None else None,
                )

    settings_payload: Dict[str, Any] = {}
    if settings_path and os.path.exists(settings_path):
        with open(settings_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                settings_payload = data

    next_step_health_payload = settings_payload.get("next_step_health") or {}
    action_thresholds_payload = settings_payload.get("action_thresholds") or {}
    forecast_weights_payload = settings_payload.get("forecast_priority_weights") or {}
    amount_weights_payload = settings_payload.get("amount_weights") or {}

    settings = WeeklyAttentionSettings(
        supported_view_default=str(
            settings_payload.get("supported_view_default", DEFAULT_WEEKLY_ATTENTION_SUPPORTED_VIEW)
        ),
        fallback_coverage_factor=(
            _to_optional_float(settings_payload.get("fallback_coverage_factor"))
            if _to_optional_float(settings_payload.get("fallback_coverage_factor")) is not None
            else DEFAULT_WEEKLY_ATTENTION_COVERAGE_FACTOR
        ),
        fallback_active_view=str(
            settings_payload.get("fallback_active_view", DEFAULT_WEEKLY_ATTENTION_ACTIVE_VIEW)
        ),
        next_step_health=NextStepHealthThresholds(
            good_min=(
                _to_optional_float(next_step_health_payload.get("good_min"))
                if _to_optional_float(next_step_health_payload.get("good_min")) is not None
                else DEFAULT_NEXT_STEP_HEALTH_THRESHOLDS["good_min"]
            ),
            watch_min=(
                _to_optional_float(next_step_health_payload.get("watch_min"))
                if _to_optional_float(next_step_health_payload.get("watch_min")) is not None
                else DEFAULT_NEXT_STEP_HEALTH_THRESHOLDS["watch_min"]
            ),
            poor_max=(
                _to_optional_float(next_step_health_payload.get("poor_max"))
                if _to_optional_float(next_step_health_payload.get("poor_max")) is not None
                else DEFAULT_NEXT_STEP_HEALTH_THRESHOLDS["poor_max"]
            ),
        ),
        action_thresholds=ActionThresholds(
            monitor_min=(
                _to_optional_float(action_thresholds_payload.get("monitor_min"))
                if _to_optional_float(action_thresholds_payload.get("monitor_min")) is not None
                else DEFAULT_ACTION_THRESHOLDS["monitor_min"]
            ),
            ae_attention_min=(
                _to_optional_float(action_thresholds_payload.get("ae_attention_min"))
                if _to_optional_float(action_thresholds_payload.get("ae_attention_min")) is not None
                else DEFAULT_ACTION_THRESHOLDS["ae_attention_min"]
            ),
            manager_attention_min=(
                _to_optional_float(action_thresholds_payload.get("manager_attention_min"))
                if _to_optional_float(action_thresholds_payload.get("manager_attention_min")) is not None
                else DEFAULT_ACTION_THRESHOLDS["manager_attention_min"]
            ),
            urgent_manager_attention_min=(
                _to_optional_float(action_thresholds_payload.get("urgent_manager_attention_min"))
                if _to_optional_float(action_thresholds_payload.get("urgent_manager_attention_min")) is not None
                else DEFAULT_ACTION_THRESHOLDS["urgent_manager_attention_min"]
            ),
        ),
        forecast_priority_weights=ForecastPriorityWeights(
            commit=(
                _to_optional_float(forecast_weights_payload.get("commit"))
                if _to_optional_float(forecast_weights_payload.get("commit")) is not None
                else DEFAULT_FORECAST_PRIORITY_WEIGHTS["commit"]
            ),
            green_upside=(
                _to_optional_float(forecast_weights_payload.get("green_upside"))
                if _to_optional_float(forecast_weights_payload.get("green_upside")) is not None
                else DEFAULT_FORECAST_PRIORITY_WEIGHTS["green_upside"]
            ),
            upside=(
                _to_optional_float(forecast_weights_payload.get("upside"))
                if _to_optional_float(forecast_weights_payload.get("upside")) is not None
                else DEFAULT_FORECAST_PRIORITY_WEIGHTS["upside"]
            ),
            other=(
                _to_optional_float(forecast_weights_payload.get("other"))
                if _to_optional_float(forecast_weights_payload.get("other")) is not None
                else DEFAULT_FORECAST_PRIORITY_WEIGHTS["other"]
            ),
        ),
        amount_weights=AmountWeightSettings(
            small_max=(
                _to_optional_float(amount_weights_payload.get("small_max"))
                if _to_optional_float(amount_weights_payload.get("small_max")) is not None
                else DEFAULT_AMOUNT_WEIGHT_SETTINGS["small_max"]
            ),
            medium_max=(
                _to_optional_float(amount_weights_payload.get("medium_max"))
                if _to_optional_float(amount_weights_payload.get("medium_max")) is not None
                else DEFAULT_AMOUNT_WEIGHT_SETTINGS["medium_max"]
            ),
            small_weight=(
                _to_optional_float(amount_weights_payload.get("small_weight"))
                if _to_optional_float(amount_weights_payload.get("small_weight")) is not None
                else DEFAULT_AMOUNT_WEIGHT_SETTINGS["small_weight"]
            ),
            medium_weight=(
                _to_optional_float(amount_weights_payload.get("medium_weight"))
                if _to_optional_float(amount_weights_payload.get("medium_weight")) is not None
                else DEFAULT_AMOUNT_WEIGHT_SETTINGS["medium_weight"]
            ),
            large_weight=(
                _to_optional_float(amount_weights_payload.get("large_weight"))
                if _to_optional_float(amount_weights_payload.get("large_weight")) is not None
                else DEFAULT_AMOUNT_WEIGHT_SETTINGS["large_weight"]
            ),
        ),
    )

    return WeeklyAttentionConfig(ae_inputs=ae_inputs, settings=settings)
