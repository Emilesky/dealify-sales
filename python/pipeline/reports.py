from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from python.pipeline.management_builders import extract_health_score
from python.pipeline.constants import (
    COL_AE,
    COL_AMOUNT_CLEAN,
    COL_CLOSE_DATE_PARSED,
    COL_NEXT_STEPS,
    COL_OPPORTUNITY,
    COL_STAGE,
    COL_STAGE_CLASS,
)


def build_ae_reports(ctx: Any, active_df: pd.DataFrame, bookings_df: pd.DataFrame, omitted_df: pd.DataFrame) -> str:
    """
    Bouw een leesbare tekst output per AE voor coaching en management scan.
    Werkt op canonical kolommen.
    """

    def _safe_series(df: pd.DataFrame, col: str) -> pd.Series:
        if df is None or len(df) == 0:
            return pd.Series([], dtype=object)
        if col in df.columns:
            return df[col]
        return pd.Series([None] * len(df), dtype=object)

    def _sum_amount(df: pd.DataFrame) -> float:
        if df is None or len(df) == 0:
            return 0.0
        if COL_AMOUNT_CLEAN in df.columns:
            return float(df[COL_AMOUNT_CLEAN].fillna(0.0).sum())
        return 0.0

    def _ae_filter(df: pd.DataFrame, ae: str) -> pd.DataFrame:
        if df is None or len(df) == 0:
            return df.head(0) if isinstance(df, pd.DataFrame) else pd.DataFrame()
        if COL_AE not in df.columns:
            return df.head(0)
        return df[df[COL_AE].fillna("").astype(str) == ae].copy()

    today = getattr(ctx, "today", None)
    rules: Dict[str, Any] = getattr(ctx, "rules", {}) or {}
    low_score_threshold = float(rules.get("next_step_low_score_threshold", 5.0))

    # AEs in actieve pipeline (leading set)
    ae_values = sorted(set(_safe_series(active_df, COL_AE).dropna().astype(str).tolist()))

    lines: List[str] = []
    lines.append("=== AE Pipeline Summary ===")
    lines.append(f"AEs in actieve pipeline: {len(ae_values)}")
    lines.append("")

    for ae in ae_values:
        ae_active = _ae_filter(active_df, ae)
        ae_bookings = _ae_filter(bookings_df, ae)
        ae_omitted = _ae_filter(omitted_df, ae)

        total_pipeline = _sum_amount(ae_active)

        # Stage class totals
        commit_amt = 0.0
        upside_amt = 0.0
        green_upside_amt = 0.0
        if len(ae_active) and COL_STAGE_CLASS in ae_active.columns and COL_AMOUNT_CLEAN in ae_active.columns:
            commit_amt = float(ae_active[ae_active[COL_STAGE_CLASS] == "commit"][COL_AMOUNT_CLEAN].fillna(0.0).sum())
            upside_amt = float(ae_active[ae_active[COL_STAGE_CLASS] == "upside"][COL_AMOUNT_CLEAN].fillna(0.0).sum())
            green_upside_amt = float(
                ae_active[ae_active[COL_STAGE_CLASS] == "green upside"][COL_AMOUNT_CLEAN].fillna(0.0).sum()
            )

        # Hygiene metrics
        next_steps_series = _safe_series(ae_active, COL_NEXT_STEPS).fillna("").astype(str)
        nr_no_next_step = int((next_steps_series.str.strip() == "").sum())

        amount_series = _safe_series(ae_active, COL_AMOUNT_CLEAN).fillna(0.0)
        nr_amount_zero = int((amount_series <= 0.0).sum())

        # Overdue
        nr_overdue = 0
        close_series = _safe_series(ae_active, COL_CLOSE_DATE_PARSED)
        if today is not None and len(close_series):
            try:
                nr_overdue = int(((close_series.notna()) & (close_series < today)).sum())
            except Exception:
                nr_overdue = 0

        # Health scores
        avg_health: Optional[float] = None
        nr_low_health = 0
        scored_count = 0
        if len(ae_active) and "next_step_health" in ae_active.columns:
            scores: List[float] = []
            for v in ae_active["next_step_health"].tolist():
                s = extract_health_score(v)
                if s is not None:
                    scores.append(float(s))
            scored_count = len(scores)
            if scores:
                avg_health = sum(scores) / len(scores)
                nr_low_health = sum(1 for s in scores if s < low_score_threshold)

        lines.append(f"Account Executive: {ae}")
        lines.append("=" * 80)
        lines.append(f"Total active pipeline: {total_pipeline:,.2f}")
        lines.append(f"Commit: {commit_amt:,.2f} | Upside: {upside_amt:,.2f} | Green Upside: {green_upside_amt:,.2f}")
        lines.append(f"Bookings (niet in actieve pipeline): {_sum_amount(ae_bookings):,.2f}")
        lines.append(f"Omitted (closed, apart gerapporteerd): {_sum_amount(ae_omitted):,.2f}")
        lines.append("")
        lines.append(f"Deals zonder Next Steps: {nr_no_next_step}")
        lines.append(f"Overdue deals (Close Date < vandaag): {nr_overdue}")
        lines.append(f"Deals met Amount = 0: {nr_amount_zero}")

        if avg_health is None:
            lines.append("Next Step health (LLM): no scored data")
        else:
            lines.append(
                f"Next Step health (LLM): avg={avg_health:.2f} | scored={scored_count} | low(<{low_score_threshold:g})={nr_low_health}"
            )

        # Optional: list worst next steps (top 10)
        if len(ae_active) and "next_step_health" in ae_active.columns:
            bad_rows: List[Tuple[float, str, str]] = []
            for _, r in ae_active.iterrows():
                s = extract_health_score(r.get("next_step_health"))
                if s is not None and float(s) < low_score_threshold:
                    opp = str(r.get(COL_OPPORTUNITY, "") or "")
                    stg = str(r.get(COL_STAGE, "") or "")
                    bad_rows.append((float(s), opp, stg))
            bad_rows.sort(key=lambda x: x[0])

            if bad_rows:
                lines.append("")
                lines.append(f"Deals met slechte Next Steps (score <{low_score_threshold:g}): {len(bad_rows)}")
                for s, opp, stg in bad_rows[:10]:
                    lines.append(f" - score={s:.1f} | {opp} | stage={stg}")

        lines.append("")

    return "\n".join(lines)