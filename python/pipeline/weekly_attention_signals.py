from __future__ import annotations

"""Deterministic per-deal signal derivation for Weekly AE Attention.

Architectural role:
- Business-logic module
- Pure derivation from already-available in-memory data plus typed config

Explicit non-responsibilities:
- No file IO
- No CLI orchestration
- No UI behavior
- No LLM calls
- No AE aggregation
- No action mapping

Note:
- This lives under `python/pipeline/` as a pragmatic source location because the
  repository currently has no usable source-backed `python/domain/` module yet.
- Treat this as a dedicated business slice, not as a general pipeline helper.
"""

from datetime import date, timedelta
from typing import Any

import pandas as pd

from python.app.weekly_attention_config import WeeklyAttentionConfig
from python.pipeline.constants import (
    COL_AMOUNT_CLEAN,
    COL_CLOSE_DATE_PARSED,
    COL_FORECAST_CATEGORY,
    COL_NEXT_STEPS,
    COL_STAGE_CLASS,
)


def _get_today(ctx: Any) -> date:
    today = getattr(ctx, "today", None)
    if isinstance(today, date):
        return today
    return date.today()


def _get_fiscal_quarter_bounds(ctx: Any, today: date) -> tuple[date, date]:
    calendar_cfg = getattr(ctx, "calendar", {}) or {}
    fiscal_start_month = int(calendar_cfg.get("fiscal_year_start_month", 2))
    fiscal_start_day = int(calendar_cfg.get("fiscal_year_start_day", 1))

    if (today.month, today.day) >= (fiscal_start_month, fiscal_start_day):
        fiscal_year_start = date(today.year, fiscal_start_month, fiscal_start_day)
    else:
        fiscal_year_start = date(today.year - 1, fiscal_start_month, fiscal_start_day)

    quarter_starts = [0, 3, 6, 9]
    months_since_start = (today.year - fiscal_year_start.year) * 12 + (today.month - fiscal_year_start.month)
    quarter_index = max(offset for offset in quarter_starts if offset <= months_since_start)

    quarter_start_month = ((fiscal_year_start.month - 1 + quarter_index) % 12) + 1
    quarter_start_year = fiscal_year_start.year + ((fiscal_year_start.month - 1 + quarter_index) // 12)
    quarter_start = date(quarter_start_year, quarter_start_month, fiscal_start_day)

    next_quarter_month = ((quarter_start.month - 1 + 3) % 12) + 1
    next_quarter_year = quarter_start.year + ((quarter_start.month - 1 + 3) // 12)
    next_quarter_start = date(next_quarter_year, next_quarter_month, fiscal_start_day)
    quarter_end = next_quarter_start - timedelta(days=1)
    return quarter_start, quarter_end


def _extract_health_score(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    if isinstance(value, dict):
        score_raw = value.get("score")
        if isinstance(score_raw, (int, float)):
            return float(score_raw)
        if isinstance(score_raw, str):
            try:
                return float(score_raw.strip())
            except ValueError:
                return None
    return None


def _resolve_forecast_priority(row: pd.Series, config: WeeklyAttentionConfig) -> float:
    weights = config.settings.forecast_priority_weights
    forecast_category = str(row.get(COL_FORECAST_CATEGORY, "") or "").strip().lower()
    stage_class = str(row.get(COL_STAGE_CLASS, "") or "").strip().lower()

    commit_weight = float(weights.commit if weights.commit is not None else 1.0)
    green_upside_weight = float(weights.green_upside if weights.green_upside is not None else 0.8)
    upside_weight = float(weights.upside if weights.upside is not None else 0.6)
    other_weight = float(weights.other if weights.other is not None else 0.3)

    if "commit" in forecast_category or stage_class == "commit":
        return commit_weight
    if "green upside" in forecast_category or stage_class == "green upside":
        return green_upside_weight
    if "upside" in forecast_category or stage_class == "upside":
        return upside_weight
    return other_weight


def _resolve_amount_weight(amount: Any, config: WeeklyAttentionConfig) -> float:
    settings = config.settings.amount_weights
    try:
        amount_value = float(amount or 0.0)
    except Exception:
        amount_value = 0.0

    small_max = float(settings.small_max if settings.small_max is not None else 25000.0)
    medium_max = float(settings.medium_max if settings.medium_max is not None else 100000.0)
    small_weight = float(settings.small_weight if settings.small_weight is not None else 0.5)
    medium_weight = float(settings.medium_weight if settings.medium_weight is not None else 1.0)
    large_weight = float(settings.large_weight if settings.large_weight is not None else 1.5)

    if amount_value <= small_max:
        return small_weight
    if amount_value <= medium_max:
        return medium_weight
    return large_weight


def _resolve_health_band(score: float | None, config: WeeklyAttentionConfig) -> str:
    thresholds = config.settings.next_step_health
    good_min = float(thresholds.good_min if thresholds.good_min is not None else 7.0)
    watch_min = float(thresholds.watch_min if thresholds.watch_min is not None else 5.0)

    if score is None:
        return "unknown"
    if score >= good_min:
        return "good"
    if score >= watch_min:
        return "watch"
    return "poor"


def build_weekly_attention_signals(
    ctx: Any,
    active_df: pd.DataFrame,
    config: WeeklyAttentionConfig,
) -> pd.DataFrame:
    """Build deterministic per-deal Weekly AE Attention signals.

    This function is pure business logic:
    - it derives signals from already-available active deals
    - it performs no file IO and no output shaping
    """
    if active_df is None:
        return pd.DataFrame()
    if active_df.empty:
        return active_df.copy()

    df = active_df.copy()
    today = _get_today(ctx)
    fiscal_quarter_start, fiscal_quarter_end = _get_fiscal_quarter_bounds(ctx, today)

    if COL_CLOSE_DATE_PARSED in df.columns:
        close_dates = pd.to_datetime(df[COL_CLOSE_DATE_PARSED], errors="coerce")
        df["close_this_week"] = close_dates.dt.date.between(today, today + timedelta(days=6))
        df["close_this_quarter"] = close_dates.dt.date.between(fiscal_quarter_start, fiscal_quarter_end)
    else:
        df["close_this_week"] = False
        df["close_this_quarter"] = False

    next_steps = (
        df[COL_NEXT_STEPS].fillna("").astype(str).str.strip()
        if COL_NEXT_STEPS in df.columns
        else pd.Series("", index=df.index, dtype=object)
    )
    df["missing_next_step_flag"] = next_steps == ""

    if "next_step_health" in df.columns:
        df["next_step_health_score"] = df["next_step_health"].apply(_extract_health_score)
    else:
        df["next_step_health_score"] = None

    df["next_step_health_band"] = df["next_step_health_score"].apply(
        lambda score: _resolve_health_band(score, config)
    )

    poor_max = float(
        config.settings.next_step_health.poor_max
        if config.settings.next_step_health.poor_max is not None
        else 5.0
    )
    df["poor_next_step_flag"] = df["next_step_health_score"].apply(
        lambda score: score is not None and float(score) < poor_max
    )

    df["forecast_priority"] = df.apply(
        lambda row: _resolve_forecast_priority(row, config),
        axis=1,
    )

    if COL_AMOUNT_CLEAN in df.columns:
        df["amount_weight"] = df[COL_AMOUNT_CLEAN].apply(
            lambda amount: _resolve_amount_weight(amount, config)
        )
        amount_series = df[COL_AMOUNT_CLEAN].fillna(0.0).astype(float)
    else:
        df["amount_weight"] = 0.0
        amount_series = pd.Series(0.0, index=df.index, dtype=float)

    relevant_window_mask = df["close_this_week"] | df["close_this_quarter"]
    df["execution_risk_flag"] = relevant_window_mask & (
        df["missing_next_step_flag"] | df["poor_next_step_flag"]
    )

    df["attention_value"] = amount_series * df["forecast_priority"].astype(float)
    return df
