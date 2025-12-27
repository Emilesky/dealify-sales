"""Single module for management aggregations (extended + full scopes).

No logging/printing here; return JSON-serializable structures only.
"""

from datetime import timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

from python.domain.pipeline_intel.constants import (
    COL_ACCOUNT,
    COL_OPPORTUNITY,
    COL_AE,
    COL_AMOUNT_CLEAN,
    COL_CLOSE_DATE_PARSED,
    COL_STAGE,
    COL_FORECAST_CATEGORY,
    COL_NEXT_STEPS,
)




# === Helpers ===

def extract_health_score(health: Any) -> float | None:
    """Extract a numeric health score from a next_step_health value (dict, str, int, float)."""

    if isinstance(health, (int, float)):
        return float(health)

    if isinstance(health, str):
        try:
            return float(health.strip())
        except ValueError:
            return None

    if isinstance(health, dict):
        score_raw = health.get("score")
        if isinstance(score_raw, (int, float)):
            return float(score_raw)
        if isinstance(score_raw, str):
            try:
                return float(score_raw.strip())
            except ValueError:
                return None

    return None

def _safe_sum_amount(df: pd.DataFrame) -> float:
    if df is None or len(df) == 0 or COL_AMOUNT_CLEAN not in df.columns:
        return 0.0
    return float(df[COL_AMOUNT_CLEAN].fillna(0.0).sum())


def _safe_iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        ts = pd.to_datetime(value, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.date().isoformat()
    except Exception:
        return None


# === TEAM / TOTALS (EXTENDED) ===

def build_team_overview(ctx: Any, active_df: pd.DataFrame, bookings_df: pd.DataFrame, omitted_df: pd.DataFrame) -> Dict[str, Any]:
    target = getattr(ctx, "team_target", None)
    if target is None:
        target = getattr(ctx, "team_target_current_quarter", None)
    try:
        target_value = float(target) if target is not None else None
    except Exception:
        target_value = None

    bookings_amount = _safe_sum_amount(bookings_df)
    active_amount = _safe_sum_amount(active_df)
    omitted_amount = _safe_sum_amount(omitted_df)

    gap_to_target = None
    if target_value is not None:
        gap_to_target = max(0.0, target_value - bookings_amount)

    coverage_ratio = None
    if gap_to_target is not None and gap_to_target > 0:
        coverage_ratio = active_amount / gap_to_target if gap_to_target != 0 else None

    return {
        "target": target_value,
        "bookings_to_date": bookings_amount,
        "active_pipeline": active_amount,
        "omitted": omitted_amount,
        "gap_to_target": gap_to_target,
        "coverage_ratio": coverage_ratio,
        "counts": {
            "nr_active_deals": int(len(active_df)) if active_df is not None else 0,
            "nr_bookings_deals": int(len(bookings_df)) if bookings_df is not None else 0,
            "nr_omitted_deals": int(len(omitted_df)) if omitted_df is not None else 0,
        },
    }


# === TIME / HORIZON (EXTENDED) ===

def build_deals_closing_next_14_days(ctx: Any, active_df: pd.DataFrame, horizon_days: int = 14) -> List[Dict[str, Any]]:
    if active_df is None or COL_CLOSE_DATE_PARSED not in active_df.columns:
        return []

    today = getattr(ctx, "today", None)
    if today is None:
        return []

    dates = pd.to_datetime(active_df[COL_CLOSE_DATE_PARSED], errors="coerce")
    mask = dates.notna()
    mask &= dates.dt.date >= today
    mask &= dates.dt.date <= today + timedelta(days=horizon_days)

    subset = active_df[mask].copy()
    subset["_sort_close_date"] = dates[mask]
    amount_series = subset[COL_AMOUNT_CLEAN] if COL_AMOUNT_CLEAN in subset else pd.Series(0.0, index=subset.index)
    subset["_sort_amount"] = amount_series.fillna(0.0)

    subset = subset.sort_values(by=["_sort_close_date", "_sort_amount"], ascending=[True, False]).head(50)

    deals: List[Dict[str, Any]] = []
    for _, row in subset.iterrows():
        deals.append({
            "account_name": row.get(COL_ACCOUNT),
            "opportunity_name": row.get(COL_OPPORTUNITY),
            "ae_name": row.get(COL_AE),
            "close_date": _safe_iso(row.get(COL_CLOSE_DATE_PARSED)),
            "amount": float(row.get(COL_AMOUNT_CLEAN) or 0.0),
            "stage": row.get(COL_STAGE),
            "forecast_category": row.get(COL_FORECAST_CATEGORY),
            "next_steps": row.get(COL_NEXT_STEPS),
        })

    return deals


# === CONCENTRATION (EXTENDED) ===

def build_quarter_concentration(ctx: Any, active_df: pd.DataFrame, fiscal_start, fiscal_end) -> Dict[str, Any]:
    if active_df is None or COL_CLOSE_DATE_PARSED not in active_df.columns:
        return {
            "in_quarter_amount": 0.0,
            "total_active_amount": _safe_sum_amount(active_df),
            "in_quarter_share": None,
            "top5_in_quarter": [],
        }

    dates = pd.to_datetime(active_df[COL_CLOSE_DATE_PARSED], errors="coerce")
    mask = dates.notna() & (dates.dt.date >= fiscal_start) & (dates.dt.date <= fiscal_end)
    in_quarter_df = active_df[mask].copy()

    total_active_amount = _safe_sum_amount(active_df)
    in_quarter_amount = _safe_sum_amount(in_quarter_df)
    in_quarter_share = None
    if total_active_amount > 0:
        in_quarter_share = in_quarter_amount / total_active_amount

    if len(in_quarter_df) and COL_AMOUNT_CLEAN in in_quarter_df:
        top5_df = (
            in_quarter_df.assign(_sort_amount=in_quarter_df[COL_AMOUNT_CLEAN].fillna(0.0))
            .sort_values(by="_sort_amount", ascending=False)
            .head(5)
        )
    else:
        top5_df = in_quarter_df.head(5)

    top5_payload = []
    for _, row in top5_df.iterrows():
        top5_payload.append({
            "account_name": row.get(COL_ACCOUNT),
            "opportunity_name": row.get(COL_OPPORTUNITY),
            "ae_name": row.get(COL_AE),
            "amount": float(row.get(COL_AMOUNT_CLEAN) or 0.0),
            "close_date": _safe_iso(row.get(COL_CLOSE_DATE_PARSED)),
        })

    return {
        "in_quarter_amount": in_quarter_amount,
        "total_active_amount": total_active_amount,
        "in_quarter_share": in_quarter_share,
        "top5_in_quarter": top5_payload,
    }


# === HYGIENE (EXTENDED) ===

def build_discovery_hygiene_alerts(ctx: Any, active_df: pd.DataFrame, rules_cfg: Dict[str, Any]) -> Dict[str, Any]:
    if active_df is None:
        return {
            "nr_deals_no_next_step": 0,
            "nr_overdue_deals": 0,
            "nr_missing_close_date": 0,
            "next_step_health": {"avg": None, "count": 0, "low_count": 0},
        }

    df = active_df
    if COL_STAGE in df.columns:
        discovery_mask = df[COL_STAGE].str.contains("Discovery", case=False, na=False)
        df = df[discovery_mask]

    # counts
    nr_deals_no_next_step = int((df[COL_NEXT_STEPS].fillna("").astype(str).str.strip() == "").sum()) if COL_NEXT_STEPS in df else 0

    today_value = getattr(ctx, "today", None)
    if today_value is None:
        today_value = pd.Timestamp.utcnow().date()

    if COL_CLOSE_DATE_PARSED in df.columns:
        dates = pd.to_datetime(df[COL_CLOSE_DATE_PARSED], errors="coerce")
        nr_overdue_deals = int((dates.notna() & (dates.dt.date < today_value)).sum())
        nr_missing_close_date = int((dates.isna()).sum())
    else:
        nr_overdue_deals = 0
        nr_missing_close_date = len(df)

    scores = []
    if "next_step_health" in df.columns:
        for v in df["next_step_health"].tolist():
            s = extract_health_score(v)
            if s is not None:
                scores.append(float(s))

    low_threshold = float(rules_cfg.get("next_step_low_score_threshold", 5.0)) if rules_cfg else 5.0
    next_step_health = {
        "avg": (sum(scores) / len(scores)) if scores else None,
        "count": len(scores),
        "low_count": sum(1 for s in scores if s < low_threshold),
    }

    return {
        "nr_deals_no_next_step": nr_deals_no_next_step,
        "nr_overdue_deals": nr_overdue_deals,
        "nr_missing_close_date": nr_missing_close_date,
        "next_step_health": next_step_health,
    }


# =========================
# AE SCORECARDS (FULL)
# =========================

def build_ae_scorecards(
    ctx: Any,
    active_df: pd.DataFrame,
    rules_cfg: Dict[str, Any],
    top_n: int = 5,
) -> Dict[str, Any]:
    """Build per-AE scorecards (compact) for FULL scope.

    Returns a dict keyed by AE name, each containing pipeline totals, hygiene counts, and top deals.
    """
    if active_df is None or active_df.empty:
        return {}

    if COL_AE not in active_df.columns:
        return {}

    low_threshold = float(rules_cfg.get("next_step_low_score_threshold", 5.0)) if rules_cfg else 5.0
    today = getattr(ctx, "today", None)

    scorecards: Dict[str, Any] = {}

    for ae_name, g in active_df.groupby(COL_AE, dropna=False):
        ae_key = str(ae_name).strip() if ae_name is not None else "(unknown)"

        pipeline_amount = _safe_sum_amount(g)
        nr_deals = int(len(g))

        # Hygiene counts
        nr_overdue = 0
        nr_missing_close_date = 0
        if COL_CLOSE_DATE_PARSED in g.columns and today is not None:
            cd = pd.to_datetime(g[COL_CLOSE_DATE_PARSED], errors="coerce")
            nr_missing_close_date = int(cd.isna().sum())
            try:
                nr_overdue = int((cd.notna() & (cd.dt.date < today)).sum())
            except Exception:
                nr_overdue = 0

        nr_no_next_step = 0
        if COL_NEXT_STEPS in g.columns:
            ns = g[COL_NEXT_STEPS].fillna("").astype(str).str.strip()
            nr_no_next_step = int((ns == "").sum())

        # Next-step health stats (optional; may be absent when --no-llm)
        avg_nsh: Optional[float] = None
        nsh_count = 0
        nsh_low = 0
        if "next_step_health" in g.columns:
            scores: List[float] = []
            for v in g["next_step_health"].tolist():
                s = extract_health_score(v)
                if s is None:
                    continue
                scores.append(float(s))
            nsh_count = len(scores)
            if nsh_count > 0:
                avg_nsh = float(sum(scores) / nsh_count)
                nsh_low = int(sum(1 for s in scores if s < low_threshold))

        hygiene = {
            "nr_overdue_deals": nr_overdue,
            "nr_missing_close_date": nr_missing_close_date,
            "nr_deals_no_next_step": nr_no_next_step,
            "next_step_health": {
                "avg": avg_nsh,
                "count": nsh_count,
                "low_count": nsh_low,
            },
        }

        # Top deals (compact)
        sort_cols = []
        ascending = []
        if COL_AMOUNT_CLEAN in g.columns:
            sort_cols.append(COL_AMOUNT_CLEAN)
            ascending.append(False)
        if COL_OPPORTUNITY in g.columns:
            sort_cols.append(COL_OPPORTUNITY)
            ascending.append(True)

        if sort_cols:
            g2 = g.sort_values(by=sort_cols, ascending=ascending)
        else:
            g2 = g

        top_deals_rows = g2.head(int(top_n))
        top_deals: List[Dict[str, Any]] = []
        for _, row in top_deals_rows.iterrows():
            top_deals.append(
                {
                    "account_name": row.get(COL_ACCOUNT),
                    "opportunity_name": row.get(COL_OPPORTUNITY),
                    "amount": float(row.get(COL_AMOUNT_CLEAN) or 0.0) if COL_AMOUNT_CLEAN in top_deals_rows.columns else 0.0,
                    "close_date": _safe_iso(row.get(COL_CLOSE_DATE_PARSED)) if COL_CLOSE_DATE_PARSED in top_deals_rows.columns else None,
                    "stage": row.get(COL_STAGE) if COL_STAGE in top_deals_rows.columns else None,
                    "forecast_category": row.get(COL_FORECAST_CATEGORY) if COL_FORECAST_CATEGORY in top_deals_rows.columns else None,
                    "next_steps": row.get(COL_NEXT_STEPS) if COL_NEXT_STEPS in top_deals_rows.columns else None,
                }
            )

        scorecards[ae_key] = {
            "pipeline_amount": float(pipeline_amount),
            "nr_deals": nr_deals,
            "hygiene": hygiene,
            "top_deals": top_deals,
        }

    return scorecards
