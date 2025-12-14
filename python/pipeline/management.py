from __future__ import annotations

from datetime import date
from typing import Any, Dict, Tuple

import pandas as pd

from python.pipeline.analysis import extract_health_score
from python.pipeline.constants import (
    COL_ACCOUNT,
    COL_AE,
    COL_AMOUNT_CLEAN,
    COL_CLOSE_DATE_PARSED,
    COL_CREATED_DATE,
    COL_FORECAST_CATEGORY,
    COL_NEXT_STEPS,
    COL_OPPORTUNITY,
    COL_STAGE,
    COL_STAGE_CLASS,
)


# === Fiscal helpers ===

def get_fiscal_quarter_bounds(today: date) -> Tuple[date, date]:
    """
    Return fiscal quarter bounds based on Feb-1 fiscal year start.
    Q1: Feb-Apr, Q2: May-Jul, Q3: Aug-Oct, Q4: Nov-Jan
    """
    year = today.year

    if today.month in (2, 3, 4):
        return date(year, 2, 1), date(year, 4, 30)
    if today.month in (5, 6, 7):
        return date(year, 5, 1), date(year, 7, 31)
    if today.month in (8, 9, 10):
        return date(year, 8, 1), date(year, 10, 31)

    # Nov, Dec, Jan
    if today.month == 1:
        return date(year - 1, 11, 1), date(year - 1, 12, 31)
    return date(year, 11, 1), date(year + 1, 1, 31)


def _get_calendar_cfg() -> Dict[str, Any]:
    return {
        "fiscal_year_start_month": 2,
        "fiscal_year_start_day": 1,
    }


def _get_rules_cfg() -> Dict[str, Any]:
    return {
        "next_step_low_score_threshold": 5.0,
        "horizon_days_short": 14,
        "horizon_days_medium": 30,
    }


# === Management JSON builder ===

def build_management_data(
    ctx: Any,
    active_df: pd.DataFrame,
    bookings_df: pd.DataFrame,
    omitted_df: pd.DataFrame,
) -> Dict[str, Any]:
    """
    Bouw een JSON-serialiseerbare management dataset.
    GEEN DataFrames of objecten in output.
    """

    today = ctx.today
    calendar_cfg = _get_calendar_cfg()
    rules_cfg = _get_rules_cfg()
    fiscal_start, fiscal_end = get_fiscal_quarter_bounds(today)

    def _sum_amount(df: pd.DataFrame) -> float:
        if df is None or len(df) == 0:
            return 0.0
        if COL_AMOUNT_CLEAN in df.columns:
            return float(df[COL_AMOUNT_CLEAN].fillna(0.0).sum())
        return 0.0

    def _count_overdue(df: pd.DataFrame) -> int:
        if df is None or COL_CLOSE_DATE_PARSED not in df.columns:
            return 0
        return int(((df[COL_CLOSE_DATE_PARSED].notna()) & (df[COL_CLOSE_DATE_PARSED] < today)).sum())

    def _count_no_next_step(df: pd.DataFrame) -> int:
        if df is None or COL_NEXT_STEPS not in df.columns:
            return 0
        return int((df[COL_NEXT_STEPS].fillna("").astype(str).str.strip() == "").sum())

    def _health_stats(df: pd.DataFrame) -> Dict[str, Any]:
        scores = []
        if df is not None and "next_step_health" in df.columns:
            for v in df["next_step_health"].tolist():
                s = extract_health_score(v)
                if s is not None:
                    scores.append(float(s))

        if not scores:
            return {
                "avg": None,
                "count": 0,
                "low_count": 0,
            }

        low_threshold = rules_cfg["next_step_low_score_threshold"]
        return {
            "avg": sum(scores) / len(scores),
            "count": len(scores),
            "low_count": sum(1 for s in scores if s < low_threshold),
        }

    management_data: Dict[str, Any] = {
        "meta": {
            "generated_on": today.isoformat(),
            "fiscal_quarter_start": fiscal_start.isoformat(),
            "fiscal_quarter_end": fiscal_end.isoformat(),
        },
        "calendar": calendar_cfg,
        "rules": rules_cfg,
        "totals": {
            "active_pipeline": _sum_amount(active_df),
            "bookings": _sum_amount(bookings_df),
            "omitted": _sum_amount(omitted_df),
            "nr_active_deals": int(len(active_df)),
            "nr_bookings_deals": int(len(bookings_df)),
            "nr_omitted_deals": int(len(omitted_df)),
            "nr_overdue_deals": _count_overdue(active_df),
            "nr_deals_no_next_step": _count_no_next_step(active_df),
            "avg_next_step_health": _health_stats(active_df)["avg"],
        },
        "health": _health_stats(active_df),
    }

    return management_data