from __future__ import annotations

"""AE-level deterministic aggregation for Weekly AE Attention.

Architectural role:
- Business-logic module
- Aggregates already-derived per-deal signals into AE-level attention inputs

Explicit non-responsibilities:
- No file IO
- No config loading
- No CLI orchestration
- No UI behavior
- No LLM calls
- No final action mapping in this step
- No management-report shaping

Note:
- This lives under `python/pipeline/` as a pragmatic source location because the
  repository currently has no usable source-backed `python/domain/` module yet.
- Treat this as a dedicated business slice, not as a general pipeline helper.
"""

from typing import Any, Dict

import pandas as pd

from python.app.weekly_attention_config import WeeklyAttentionConfig
from python.pipeline.constants import (
    COL_AE,
    COL_AMOUNT_CLEAN,
    COL_FORECAST_CATEGORY,
)


def _sum_amount(df: pd.DataFrame) -> float:
    if df is None or df.empty or COL_AMOUNT_CLEAN not in df.columns:
        return 0.0
    return float(df[COL_AMOUNT_CLEAN].fillna(0.0).sum())


def _safe_gap(goal: float | None, actual: float) -> float | None:
    if goal is None:
        return None
    return max(0.0, float(goal) - float(actual))


def _coverage_vs_gap(pipeline_value: float, gap_to_verbal: float | None, gap_to_target: float | None) -> float | None:
    base_gap = gap_to_verbal if gap_to_verbal is not None else gap_to_target
    if base_gap is None or base_gap <= 0:
        return None
    return float(pipeline_value) / float(base_gap)


def _avg_health(df: pd.DataFrame) -> float | None:
    if df is None or df.empty or "next_step_health_score" not in df.columns:
        return None
    scores = [
        float(v)
        for v in df["next_step_health_score"].tolist()
        if v is not None and pd.notna(v)
    ]
    if not scores:
        return None
    return float(sum(scores) / len(scores))


def _top_deal_concentration(df: pd.DataFrame, top_n: int = 3) -> float | None:
    if df is None or df.empty or COL_AMOUNT_CLEAN not in df.columns:
        return None
    total = _sum_amount(df)
    if total <= 0:
        return None
    top_total = float(df[COL_AMOUNT_CLEAN].fillna(0.0).sort_values(ascending=False).head(top_n).sum())
    return top_total / total


def _active_view_for_ae(ae_name: str, config: WeeklyAttentionConfig) -> str:
    ae_cfg = config.ae_inputs.get(ae_name)
    if ae_cfg and ae_cfg.active_view:
        return ae_cfg.active_view
    return config.settings.fallback_active_view or "weekly"


def build_weekly_attention_ae_inputs(
    signals_df: pd.DataFrame,
    bookings_df: pd.DataFrame,
    config: WeeklyAttentionConfig,
) -> Dict[str, Dict[str, Any]]:
    """Aggregate per-deal signals into AE-level deterministic inputs.

    This function preserves time horizon explicitly:
    - weekly exposure metrics remain weekly
    - quarterly risk counts remain quarterly
    """
    if signals_df is None or signals_df.empty or COL_AE not in signals_df.columns:
        return {}

    bookings_by_ae: Dict[str, float] = {}
    if bookings_df is not None and not bookings_df.empty and COL_AE in bookings_df.columns:
        for ae_name, g in bookings_df.groupby(COL_AE, dropna=False):
            ae_key = str(ae_name).strip() if ae_name is not None else "(unknown)"
            bookings_by_ae[ae_key] = _sum_amount(g)

    result: Dict[str, Dict[str, Any]] = {}

    for ae_name, g in signals_df.groupby(COL_AE, dropna=False):
        ae_key = str(ae_name).strip() if ae_name is not None else "(unknown)"
        ae_cfg = config.ae_inputs.get(ae_key)

        target_value = ae_cfg.target if ae_cfg else None
        verbal_value = ae_cfg.verbal if ae_cfg else None
        bookings_to_date = float(bookings_by_ae.get(ae_key, 0.0))
        active_view = _active_view_for_ae(ae_key, config)

        close_this_week_mask = g["close_this_week"].fillna(False).astype(bool) if "close_this_week" in g.columns else pd.Series(False, index=g.index)
        close_this_quarter_mask = g["close_this_quarter"].fillna(False).astype(bool) if "close_this_quarter" in g.columns else pd.Series(False, index=g.index)
        poor_next_step_mask = g["poor_next_step_flag"].fillna(False).astype(bool) if "poor_next_step_flag" in g.columns else pd.Series(False, index=g.index)
        missing_next_step_mask = g["missing_next_step_flag"].fillna(False).astype(bool) if "missing_next_step_flag" in g.columns else pd.Series(False, index=g.index)
        execution_risk_mask = g["execution_risk_flag"].fillna(False).astype(bool) if "execution_risk_flag" in g.columns else pd.Series(False, index=g.index)

        if COL_FORECAST_CATEGORY in g.columns:
            forecast_category = g[COL_FORECAST_CATEGORY].fillna("").astype(str)
            commit_mask = forecast_category.str.contains("commit", case=False, na=False)
            green_upside_mask = forecast_category.str.contains("green upside", case=False, na=False)
        else:
            commit_mask = pd.Series(False, index=g.index)
            green_upside_mask = pd.Series(False, index=g.index)

        relevant_window_mask = close_this_quarter_mask if active_view == "quarterly" else close_this_week_mask
        relevant_df = g[relevant_window_mask].copy()

        gap_to_target = _safe_gap(target_value, bookings_to_date)
        gap_to_verbal = _safe_gap(verbal_value, bookings_to_date)

        result[ae_key] = {
            "ae_name": ae_key,
            "active_view": active_view,
            "target": target_value,
            "verbal": verbal_value,
            "bookings_to_date": bookings_to_date,
            "gap_to_target": gap_to_target,
            "gap_to_verbal": gap_to_verbal,
            "commit_value_this_week": _sum_amount(g[close_this_week_mask & commit_mask]),
            "green_upside_value_this_week": _sum_amount(g[close_this_week_mask & green_upside_mask]),
            "pipeline_value_this_week": _sum_amount(g[close_this_week_mask]),
            "pipeline_value_this_quarter": _sum_amount(g[close_this_quarter_mask]),
            "poor_next_step_value": _sum_amount(g[poor_next_step_mask]),
            "poor_next_step_commit_value": _sum_amount(g[poor_next_step_mask & commit_mask]),
            "missing_next_step_value_this_week": _sum_amount(g[close_this_week_mask & missing_next_step_mask]),
            "count_risk_deals_this_week": int(g[close_this_week_mask & execution_risk_mask].shape[0]),
            "count_risk_deals_this_quarter": int(g[close_this_quarter_mask & execution_risk_mask].shape[0]),
            "concentration_top_deals": _top_deal_concentration(relevant_df, top_n=3),
            "coverage_vs_gap": _coverage_vs_gap(
                _sum_amount(relevant_df),
                gap_to_verbal,
                gap_to_target,
            ),
            "avg_next_step_health": _avg_health(g),
            "nr_relevant_deals": int(len(relevant_df)),
        }

    return result


def _relevant_pipeline_value(ae_data: Dict[str, Any]) -> float:
    active_view = ae_data.get("active_view") or "weekly"
    if active_view == "quarterly":
        return float(ae_data.get("pipeline_value_this_quarter") or 0.0)
    return float(ae_data.get("pipeline_value_this_week") or 0.0)


def _relevant_risk_deal_count(ae_data: Dict[str, Any]) -> int:
    active_view = ae_data.get("active_view") or "weekly"
    if active_view == "quarterly":
        return int(ae_data.get("count_risk_deals_this_quarter") or 0)
    return int(ae_data.get("count_risk_deals_this_week") or 0)


def _performance_pressure_score(ae_data: Dict[str, Any]) -> float:
    score = 0.0
    gap_to_target = ae_data.get("gap_to_target")
    gap_to_verbal = ae_data.get("gap_to_verbal")
    coverage_vs_gap = ae_data.get("coverage_vs_gap")

    if gap_to_verbal is not None and gap_to_verbal > 0:
        score += 2.0
    elif gap_to_target is not None and gap_to_target > 0:
        score += 1.0

    if coverage_vs_gap is not None:
        if coverage_vs_gap < 0.5:
            score += 2.0
        elif coverage_vs_gap < 1.0:
            score += 1.0

    return score


def _pipeline_rescue_potential_score(ae_data: Dict[str, Any]) -> float:
    score = 0.0
    relevant_pipeline_value = _relevant_pipeline_value(ae_data)
    commit_value_this_week = float(ae_data.get("commit_value_this_week") or 0.0)
    green_upside_value_this_week = float(ae_data.get("green_upside_value_this_week") or 0.0)
    concentration_top_deals = ae_data.get("concentration_top_deals")

    if relevant_pipeline_value > 0:
        score += 1.0
    if commit_value_this_week > 0:
        score += 1.0
    if green_upside_value_this_week > 0:
        score += 1.0
    if concentration_top_deals is not None and concentration_top_deals >= 0.6:
        score += 1.0

    return score


def _execution_risk_score(ae_data: Dict[str, Any]) -> float:
    score = 0.0
    relevant_risk_deals = _relevant_risk_deal_count(ae_data)
    poor_next_step_commit_value = float(ae_data.get("poor_next_step_commit_value") or 0.0)
    poor_next_step_value = float(ae_data.get("poor_next_step_value") or 0.0)
    missing_next_step_value_this_week = float(ae_data.get("missing_next_step_value_this_week") or 0.0)
    active_view = ae_data.get("active_view") or "weekly"

    if relevant_risk_deals > 0:
        score += 1.0
    if relevant_risk_deals >= 3:
        score += 1.0
    if poor_next_step_commit_value > 0:
        score += 1.0

    # Missing next step exposure remains explicitly weekly and is not silently
    # reused as a generic quarterly urgency metric.
    if active_view == "weekly" and missing_next_step_value_this_week > 0:
        score += 1.0
    elif active_view != "weekly" and poor_next_step_value > 0:
        score += 1.0

    return score


def _action_threshold(value: float | None, fallback: float) -> float:
    if value is None:
        return fallback
    return float(value)


def _map_action(
    ae_data: Dict[str, Any],
    config: WeeklyAttentionConfig,
) -> str:
    thresholds = config.settings.action_thresholds
    performance_pressure = _performance_pressure_score(ae_data)
    pipeline_rescue_potential = _pipeline_rescue_potential_score(ae_data)
    execution_risk = _execution_risk_score(ae_data)
    total_score = performance_pressure + pipeline_rescue_potential + execution_risk
    relevant_pipeline_value = _relevant_pipeline_value(ae_data)

    monitor_min = _action_threshold(thresholds.monitor_min, 1.0)
    ae_attention_min = _action_threshold(thresholds.ae_attention_min, 2.0)
    manager_attention_min = _action_threshold(thresholds.manager_attention_min, 3.0)
    urgent_manager_attention_min = _action_threshold(thresholds.urgent_manager_attention_min, 4.0)

    # Guardrail: supporting next-step signals cannot create attention without
    # either performance pressure or relevant pipeline exposure.
    if relevant_pipeline_value <= 0 and performance_pressure <= 0:
        return "NO_ACTION"

    if (
        total_score >= urgent_manager_attention_min
        and performance_pressure >= 2.0
        and pipeline_rescue_potential >= 1.0
        and execution_risk >= 1.0
    ):
        return "URGENT_MANAGER_ATTENTION"

    if (
        total_score >= manager_attention_min
        and performance_pressure >= 1.0
        and (pipeline_rescue_potential >= 1.0 or execution_risk >= 2.0)
    ):
        return "MANAGER_ATTENTION"

    if (
        total_score >= ae_attention_min
        and (pipeline_rescue_potential >= 1.0 or performance_pressure >= 1.0)
    ):
        return "AE_ATTENTION"

    if total_score >= monitor_min:
        return "MONITOR"

    return "NO_ACTION"


def apply_weekly_attention_actions(
    ae_inputs: Dict[str, Dict[str, Any]],
    config: WeeklyAttentionConfig,
) -> Dict[str, Dict[str, Any]]:
    """Apply deterministic action mapping to AE-level Weekly Attention inputs."""
    result: Dict[str, Dict[str, Any]] = {}

    for ae_name, ae_data in ae_inputs.items():
        performance_pressure = _performance_pressure_score(ae_data)
        pipeline_rescue_potential = _pipeline_rescue_potential_score(ae_data)
        execution_risk = _execution_risk_score(ae_data)

        enriched = dict(ae_data)
        enriched["scores"] = {
            "performance_pressure": performance_pressure,
            "pipeline_rescue_potential": pipeline_rescue_potential,
            "execution_risk": execution_risk,
            "total": performance_pressure + pipeline_rescue_potential + execution_risk,
        }
        enriched["action"] = _map_action(ae_data, config)
        result[ae_name] = enriched

    return result
