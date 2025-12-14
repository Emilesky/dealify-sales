from __future__ import annotations

import os
import json
import re
import argparse
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
from dataclasses import dataclass

import pandas as pd

from python.pipeline.mapping import load_mapping, map_dataframe, MappingError
from python.app.config import load_config, get_llm_config

from python.pipeline.next_step_health import evaluate_next_steps_batch
from python.pipeline.constants import (
    COL_ACCOUNT,
    COL_OPPORTUNITY,
    COL_STAGE,
    COL_FORECAST_CATEGORY,
    COL_AMOUNT,
    COL_CLOSE_DATE,
    COL_CREATED_DATE,
    COL_AE,
    COL_NEXT_STEPS,
    COL_AMOUNT_CLEAN,
    COL_CLOSE_DATE_PARSED,
    COL_STAGE_CLASS,
    SF_EXPORT_TO_CANONICAL,
)


# === Fiscal Quarter Helper ===

def get_fiscal_quarter_bounds(today: date) -> Tuple[date, date]:
    """Return fiscal quarter bounds based on config calendar (default FY start 1 Feb)."""
    cal = _get_calendar_cfg()
    fy_start_month = cal["fiscal_year_start_month"]
    fy_start_day = cal["fiscal_year_start_day"]

    this_year_start = date(today.year, fy_start_month, fy_start_day)
    if today < this_year_start:
        fy_start = date(today.year - 1, fy_start_month, fy_start_day)
    else:
        fy_start = this_year_start

    def add_months(d: date, months: int) -> date:
        y = d.year + (d.month - 1 + months) // 12
        m = (d.month - 1 + months) % 12 + 1
        from calendar import monthrange
        day = min(d.day, monthrange(y, m)[1])
        return date(y, m, day)

    month_offset = (today.year - fy_start.year) * 12 + (today.month - fy_start.month)
    q_index = month_offset // 3
    if q_index < 0:
        q_index = 0
    if q_index > 3:
        q_index = 3

    q_start = add_months(fy_start, q_index * 3)
    q_end = add_months(fy_start, q_index * 3 + 3) - timedelta(days=1)
    return q_start, q_end


# === Pad-config (via config.json) ===
# Wordt gezet in main()

# data_dir and output_dir are resolved in main() and passed via AnalysisContext
CALENDAR_CFG: Dict[str, Any] = {}
RULES_CFG: Dict[str, Any] = {}


@dataclass(frozen=True)
class AnalysisContext:
    today: date
    data_dir: str
    output_dir: str
    calendar: Dict[str, Any]
    rules: Dict[str, Any]
    team_target_current_quarter: float
    bookings_to_date_current_quarter: float
    llm_config: Any


# === Mapping (CRM-agnostic) ===
# Default mapping file relative to project root
DEFAULT_PIPELINE_MAPPING = "mappings/salesforce_pipeline.json"



# === Helpers ===
def _get_calendar_cfg() -> Dict[str, Any]:
    return {
        "fiscal_year_start_month": int(CALENDAR_CFG.get("fiscal_year_start_month", 2)),
        "fiscal_year_start_day": int(CALENDAR_CFG.get("fiscal_year_start_day", 1)),
    }


def _get_rules_cfg() -> Dict[str, Any]:
    return {
        "horizon_days_short": int(RULES_CFG.get("horizon_days_short", 14)),
        "horizon_days_medium": int(RULES_CFG.get("horizon_days_medium", 30)),
        "next_step_low_score_threshold": float(RULES_CFG.get("next_step_low_score_threshold", 5.0)),
    }


def extract_health_score(health: Any) -> Optional[float]:
    """Haal een numerieke health score uit het next_step_health veld (dict of primitive)."""
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


def parse_amount(value: Any) -> float:
    """Zorg dat het bedrag als float wordt geïnterpreteerd, inclusief valuta-tekens en EU notatie."""
    try:
        import pandas as _pd
        if _pd.isna(value):
            return 0.0
    except Exception:
        if value is None:
            return 0.0

    text = str(value).strip()
    if not text:
        return 0.0

    text = text.replace("€", "").replace("$", "")
    text = text.replace(" ", "")
    text = re.sub(r"[^0-9.,-]", "", text)

    if "." in text and "," in text:
        last_dot = text.rfind(".")
        last_comma = text.rfind(",")
        if last_dot > last_comma:
            text = text.replace(",", "")
        else:
            text = text.replace(".", "").replace(",", ".")
    elif "," in text and "." not in text:
        text = text.replace(",", ".")
    else:
        pass

    try:
        return float(text)
    except ValueError:
        return 0.0


def get_latest_csv(data_dir: str, name_contains: str = "pipeline") -> str:
    """Zoek de nieuwste CSV in /data die `name_contains` in de bestandsnaam bevat."""
    if not data_dir:
        raise RuntimeError("[pipeline] data_dir is leeg. Verwacht een geldige data directory.")

    print(f"[pipeline] Zoek nieuwste CSV in: {data_dir} met patroon: '{name_contains}'")
    files = [
        f for f in os.listdir(data_dir)
        if f.lower().endswith(".csv") and name_contains.lower() in f.lower()
    ]

    if not files:
        raise FileNotFoundError(
            f"Geen CSV-bestanden gevonden in {data_dir} met '{name_contains}' in de naam"
        )

    files_with_time = [
        (f, os.path.getmtime(os.path.join(data_dir, f)))
        for f in files
    ]
    latest_file = max(files_with_time, key=lambda x: x[1])[0]
    print(f"[pipeline] Nieuwste pipeline CSV gevonden: {latest_file}")
    return os.path.join(data_dir, latest_file)


def load_csv(path: str) -> pd.DataFrame:
    """Laad de CSV in een DataFrame."""
    print(f"[pipeline] CSV laden: {path}")
    df = pd.read_csv(path, encoding="utf-8-sig")
    print(f"[pipeline] CSV geladen met {len(df)} regels en {len(df.columns)} kolommen")
    return df


def classify_stage(stage: Any) -> str:
    """Vertaal stage naar commit/upside/green/other."""
    s = (str(stage) if stage is not None else "").strip()
    if s == "Negotiation":
        return "commit"
    if s in ("Discovery", "Qualification"):
        return "upside"
    if s == "Evaluation":
        return "green upside"
    return "other"


# === Analyse-fase ===

def run_analysis(ctx: AnalysisContext, df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Bereid de data voor:
    - Amount opschonen
    - Close Date parsen
    - Actieve pipeline, bookings, omitted splitsen
    - LLM Next Step health verrijken op actieve pipeline
    """
    df = df.copy()
    print("[pipeline] Start run_analysis()")
    print(f"[pipeline] Kolommen in dataframe: {list(df.columns)}")

    # Amount opschonen naar float (canonical: COL_AMOUNT)
    if COL_AMOUNT in df.columns:
        amount_source_col = COL_AMOUNT
    else:
        amount_source_col = None
        for col in df.columns:
            if str(col).strip().lower() in ("amount", "amount\ufeff") or "amount" in str(col).lower():
                amount_source_col = col
                break
        if amount_source_col is None:
            raise KeyError(
                f"Geen geschikte amount-kolom gevonden. Verwacht '{COL_AMOUNT}' (canonical) of iets met 'Amount'. "
                f"Beschikbare kolommen: {list(df.columns)}"
            )

    print(f"[pipeline] Amount kolom gevonden: {amount_source_col} -> wordt opgeschoond naar '{COL_AMOUNT_CLEAN}'")
    df[COL_AMOUNT_CLEAN] = df[amount_source_col].apply(parse_amount)
    print(f"[pipeline] Amount opschonen gereed (min={df[COL_AMOUNT_CLEAN].min():.2f}, max={df[COL_AMOUNT_CLEAN].max():.2f})")

    if COL_CLOSE_DATE in df.columns:
        df[COL_CLOSE_DATE_PARSED] = pd.to_datetime(df[COL_CLOSE_DATE], errors="coerce").dt.date
    else:
        print(f"[pipeline] Waarschuwing: kolom '{COL_CLOSE_DATE}' niet gevonden, {COL_CLOSE_DATE_PARSED} wordt None")
        df[COL_CLOSE_DATE_PARSED] = None

    if COL_STAGE not in df.columns:
        raise KeyError(f"Verwachte kolom '{COL_STAGE}' niet gevonden in CSV.")
    df[COL_STAGE_CLASS] = df[COL_STAGE].apply(classify_stage)

    if COL_FORECAST_CATEGORY not in df.columns:
        raise KeyError(f"Verwachte kolom '{COL_FORECAST_CATEGORY}' niet gevonden in CSV.")

    bookings_df = df[
        df[COL_FORECAST_CATEGORY].str.contains("Bookings", case=False, na=False)
    ].copy()
    omitted_df = df[
        df[COL_FORECAST_CATEGORY].str.contains("Omitted", case=False, na=False)
    ].copy()
    print(f"[pipeline] Bookings deals: {len(bookings_df)} | Omitted deals: {len(omitted_df)}")

    active_df = df[
        ~df[COL_FORECAST_CATEGORY].str.contains("Bookings", case=False, na=False)
        & ~df[COL_FORECAST_CATEGORY].str.contains("Omitted", case=False, na=False)
    ].copy()
    print(f"[pipeline] Actieve pipeline deals (excl. Bookings/Omitted): {len(active_df)}")
    print("[pipeline] Start LLM Next Step health verrijking op actieve pipeline...")
    llm_cfg = ctx.llm_config
    scoring_model = getattr(llm_cfg, "model", None)
    print(f"[pipeline] Next step scoring model (config): {scoring_model}")

    records = active_df.to_dict(orient="records")
    from time import perf_counter
    t0 = perf_counter()
    try:
        enriched_records = evaluate_next_steps_batch(
            records,
            next_step_field=COL_NEXT_STEPS,
            llm_config=llm_cfg,
        )
    except FileNotFoundError as e:
        print("[pipeline][ERROR] LLM Next Step health verrijking faalde: Ollama executable niet gevonden.")
        print("[pipeline][ERROR] Check: `which ollama` en `ollama --version` in dezelfde shell/venv.")
        print(f"[pipeline][ERROR] Exception: {repr(e)}")
        enriched_records = records
    except Exception as e:
        print("[pipeline][ERROR] LLM Next Step health verrijking is gefaald. Er wordt verder gegaan zonder health scores.")
        print(f"[pipeline][ERROR] Exception: {repr(e)}")
        enriched_records = records
    t1 = perf_counter()
    print(f"[pipeline] LLM-call evaluate_next_steps_batch duurde {t1 - t0:.2f} seconden voor {len(records)} deals.")

    active_df = pd.DataFrame(enriched_records)

    print("[pipeline] LLM verrijking voltooid. Kolommen nu:", list(active_df.columns))
    if "next_step_health" not in active_df.columns:
        print("[pipeline][WAARSCHUWING] Kolom 'next_step_health' ontbreekt na LLM-verrijking.")
    else:
        total_deals = len(active_df)
        non_null_health = active_df["next_step_health"].notna().sum()
        valid_score_count = 0
        for _, deal in active_df.iterrows():
            score_val = extract_health_score(deal.get("next_step_health"))
            if score_val is not None:
                valid_score_count += 1

        print(
            f"[pipeline] next_step_health aanwezig voor {non_null_health}/{total_deals} deals; "
            f"waarvan {valid_score_count} met een bruikbare numerieke score."
        )

        if non_null_health == 0 or valid_score_count == 0:
            print("[pipeline][WAARSCHUWING] LLM lijkt geen bruikbare health scores te hebben geleverd.")

        sample_health = active_df["next_step_health"].head(5).tolist()
        print("[pipeline] Voorbeeld next_step_health (eerste 5 deals):")
        for idx, h in enumerate(sample_health, start=1):
            print(f"  Deal {idx}: {h}")

    return active_df, bookings_df, omitted_df


# === Rapportage per AE ===

def build_ae_reports(
    ctx: AnalysisContext,
    active_df: pd.DataFrame,
    bookings_df: pd.DataFrame,
    omitted_df: pd.DataFrame,
) -> str:
    """
    Bouw een tekstuele summary per AE.
    Geeft de volledige tekst terug (voor schrijven naar file).
    """
    print("[pipeline] Start build_ae_reports()")
    lines: List[str] = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append("AE Pipeline Rapport")
    lines.append(f"Gegenereerd op: {timestamp}")
    lines.append("")

    team_total_pipeline = active_df[COL_AMOUNT_CLEAN].sum()
    team_commit = active_df.loc[active_df[COL_STAGE_CLASS] == "commit", COL_AMOUNT_CLEAN].sum()
    team_upside = active_df.loc[active_df[COL_STAGE_CLASS] == "upside", COL_AMOUNT_CLEAN].sum()
    team_green = active_df.loc[active_df[COL_STAGE_CLASS] == "green upside", COL_AMOUNT_CLEAN].sum()

    team_bookings_total = bookings_df[COL_AMOUNT_CLEAN].sum() if not bookings_df.empty else 0.0
    team_omitted_total = omitted_df[COL_AMOUNT_CLEAN].sum() if not omitted_df.empty else 0.0

    lines.append("=" * 80)
    lines.append("Teamoverzicht (alle AE's)")
    lines.append("=" * 80)
    lines.append(f"Total active pipeline (team): {team_total_pipeline:,.0f}")
    lines.append(
        f"Commit (team): {team_commit:,.0f} | Upside (team): {team_upside:,.0f} | Green Upside (team): {team_green:,.0f}"
    )
    lines.append(f"Bookings (team, niet in actieve pipeline): {team_bookings_total:,.0f}")
    lines.append(f"Omitted (team, closed, apart gerapporteerd): {team_omitted_total:,.0f}")
    lines.append("")

    if COL_AE not in active_df.columns:
        raise KeyError(f"Verwachte kolom '{COL_AE}' niet gevonden in actieve pipeline.")

    all_aes = sorted(active_df[COL_AE].dropna().unique().tolist())
    print(f"[pipeline] Aantal AE's in actieve pipeline: {len(all_aes)}")

    for ae in all_aes:
        sub = active_df[active_df[COL_AE] == ae].copy()
        if sub.empty:
            continue

        lines.append("=" * 80)
        lines.append(f"Account Executive: {ae}")
        lines.append("=" * 80)

        total_pipeline = sub[COL_AMOUNT_CLEAN].sum()
        commit = sub.loc[sub[COL_STAGE_CLASS] == "commit", COL_AMOUNT_CLEAN].sum()
        upside = sub.loc[sub[COL_STAGE_CLASS] == "upside", COL_AMOUNT_CLEAN].sum()
        green = sub.loc[sub[COL_STAGE_CLASS] == "green upside", COL_AMOUNT_CLEAN].sum()

        ae_bookings = bookings_df[bookings_df.get(COL_AE, "") == ae]
        ae_omitted = omitted_df[omitted_df.get(COL_AE, "") == ae]
        bookings_total = ae_bookings[COL_AMOUNT_CLEAN].sum() if not ae_bookings.empty else 0.0
        omitted_total = ae_omitted[COL_AMOUNT_CLEAN].sum() if not ae_omitted.empty else 0.0

        lines.append(f"Total active pipeline: {total_pipeline:,.0f}")
        lines.append(f"Commit: {commit:,.0f} | Upside: {upside:,.0f} | Green Upside: {green:,.0f}")
        lines.append(f"Bookings (niet in actieve pipeline): {bookings_total:,.0f}")
        lines.append(f"Omitted (closed, apart gerapporteerd): {omitted_total:,.0f}")
        lines.append("")

        missing_next_steps = sub[
            sub[COL_NEXT_STEPS].isna()
            | (sub[COL_NEXT_STEPS].astype(str).str.strip() == "")
        ]
        lines.append(f"Deals zonder Next Steps: {len(missing_next_steps)}")

        overdue = sub[
            sub[COL_CLOSE_DATE_PARSED].notna()
            & (sub[COL_CLOSE_DATE_PARSED] < ctx.today)
        ]
        lines.append(f"Overdue deals (Close Date < vandaag): {len(overdue)}")

        zero_amount = sub[sub[COL_AMOUNT_CLEAN] <= 0]
        lines.append(f"Deals met Amount = 0: {len(zero_amount)}")
        lines.append("")

        if "next_step_health" in sub.columns:
            rules = ctx.rules
            threshold_score = float(rules["next_step_low_score_threshold"])

            scores: List[float] = []
            low_quality: List[Tuple[float, Any, Dict[str, Any]]] = []

            for _, deal in sub.iterrows():
                health = deal.get("next_step_health")
                if not isinstance(health, dict):
                    continue

                score_raw = health.get("score")
                score_val: Optional[float] = None

                if isinstance(score_raw, (int, float)):
                    score_val = float(score_raw)
                elif isinstance(score_raw, str):
                    try:
                        score_val = float(score_raw.strip())
                    except ValueError:
                        score_val = None

                if score_val is not None:
                    scores.append(score_val)
                    if score_val < threshold_score:
                        low_quality.append((score_val, deal, health))

            if scores:
                avg_score = sum(scores) / len(scores)
                lines.append(f"Next Step health (avg LLM score): {avg_score:.1f}/10")
            else:
                lines.append("Next Step health (LLM): no scored data")

            lines.append(f"Deals met slechte Next Steps (score <{threshold_score:g}): {len(low_quality)}")

            if low_quality:
                lines.append("Worst Next Steps (LLM):")
                for score, deal, health in sorted(low_quality, key=lambda x: x[0])[:3]:
                    opp_name = deal.get(COL_OPPORTUNITY, "Unknown opportunity")
                    lines.append(f"  - {opp_name} (score {score}):")
                    lines.append(f"    Original:  {health.get('original')}")

            if low_quality:
                lines.append("")
                lines.append(f"Detail voor deals met slechte Next Steps (score <{threshold_score:g}):")
                for score, deal, health in sorted(low_quality, key=lambda x: x[0]):
                    opp_name = deal.get(COL_OPPORTUNITY, "Unknown opportunity")
                    stage = deal.get(COL_STAGE, "")
                    amount = deal.get(COL_AMOUNT_CLEAN, 0.0)

                    original = health.get("original") or ""
                    reason = health.get("reason") or ""

                    lines.append(f"  - {opp_name} | {amount:,.0f} | Stage: {stage} | Score: {score:.1f}")
                    lines.append(f"    Original Next Step (AE): {original}")
                    lines.append(f"    LLM feedback: {reason}")
                    lines.append("")
        else:
            lines.append("Next Step health (LLM): niet beschikbaar (kolom ontbreekt)")

        lines.append("")

        if not sub.empty:
            top_idx = sub[COL_AMOUNT_CLEAN].idxmax()
            top_deal = sub.loc[top_idx]
            top_name = top_deal.get(COL_OPPORTUNITY, "Unknown opportunity")
            top_amount = top_deal.get(COL_AMOUNT_CLEAN, 0.0)
            top_stage = top_deal.get(COL_STAGE, "")
            lines.append("Grootste deal in actieve pipeline:")
            lines.append(f"  - {top_name} | {top_amount:,.0f} | Stage: {top_stage}")
            lines.append("")

    return "\n".join(lines)


# === Management data JSON output ===

def build_management_data(
    ctx: AnalysisContext,
    active_df: pd.DataFrame,
    bookings_df: pd.DataFrame,
    omitted_df: pd.DataFrame,
) -> Dict[str, Any]:
    """Bouw een gestructureerde management dataset (voor LLM en dashboards)."""
    print("[pipeline] Start build_management_data()")
    data: Dict[str, Any] = {}

    team_total_pipeline = active_df[COL_AMOUNT_CLEAN].sum()
    team_commit = active_df.loc[active_df[COL_STAGE_CLASS] == "commit", COL_AMOUNT_CLEAN].sum()
    team_upside = active_df.loc[active_df[COL_STAGE_CLASS] == "upside", COL_AMOUNT_CLEAN].sum()
    team_green = active_df.loc[active_df[COL_STAGE_CLASS] == "green upside", COL_AMOUNT_CLEAN].sum()

    nr_active_deals = len(active_df)
    overdue_mask = active_df[COL_CLOSE_DATE_PARSED].notna() & (active_df[COL_CLOSE_DATE_PARSED] < ctx.today)
    nr_overdue_deals = int(overdue_mask.sum())

    no_next_step_mask = active_df[COL_NEXT_STEPS].isna() | (active_df[COL_NEXT_STEPS].astype(str).str.strip() == "")
    nr_deals_no_next_step = int(no_next_step_mask.sum())

    nr_deals_amount_zero = int((active_df[COL_AMOUNT_CLEAN] <= 0).sum())

    health_scores: List[float] = []
    for _, deal in active_df.iterrows():
        score_val = extract_health_score(deal.get("next_step_health"))
        if score_val is not None:
            health_scores.append(score_val)
    avg_next_step_health = sum(health_scores) / len(health_scores) if health_scores else None

    data["team_overview"] = {
        "total_pipeline": float(team_total_pipeline),
        "commit": float(team_commit),
        "upside": float(team_upside),
        "green_upside": float(team_green),
        "nr_active_deals": int(nr_active_deals),
        "nr_overdue_deals": int(nr_overdue_deals),
        "nr_deals_no_next_step": int(nr_deals_no_next_step),
        "nr_deals_amount_zero": int(nr_deals_amount_zero),
        "avg_next_step_health": float(avg_next_step_health) if avg_next_step_health is not None else None,
    }

    time_buckets: Dict[str, Any] = {}
    if COL_CLOSE_DATE_PARSED in active_df.columns:
        rules = ctx.rules
        horizon_14 = ctx.today + timedelta(days=rules["horizon_days_short"])
        horizon_30 = ctx.today + timedelta(days=rules["horizon_days_medium"])

        def bucket_stats(mask: pd.Series) -> Dict[str, Any]:
            subset = active_df[mask].copy()
            if subset.empty:
                return {
                    "nr_deals": 0,
                    "total_amount": 0.0,
                    "commit_amount": 0.0,
                    "upside_amount": 0.0,
                    "avg_next_step_health": None,
                    "nr_discovery_deals": 0,
                }
            total_amount = subset[COL_AMOUNT_CLEAN].sum()
            commit_amount = subset.loc[subset[COL_STAGE_CLASS] == "commit", COL_AMOUNT_CLEAN].sum()
            upside_amount = subset.loc[subset[COL_STAGE_CLASS] == "upside", COL_AMOUNT_CLEAN].sum()
            scores: List[float] = []
            for _, d in subset.iterrows():
                score_val = extract_health_score(d.get("next_step_health"))
                if score_val is not None:
                    scores.append(score_val)
            avg_health = sum(scores) / len(scores) if scores else None

            nr_discovery = int(subset[COL_STAGE].isin(["Discovery", "Qualification"]).sum())

            return {
                "nr_deals": int(len(subset)),
                "total_amount": float(total_amount),
                "commit_amount": float(commit_amount),
                "upside_amount": float(upside_amount),
                "avg_next_step_health": float(avg_health) if avg_health is not None else None,
                "nr_discovery_deals": nr_discovery,
            }

        close_notna = active_df[COL_CLOSE_DATE_PARSED].notna()
        mask_14 = close_notna & (active_df[COL_CLOSE_DATE_PARSED] >= ctx.today) & (active_df[COL_CLOSE_DATE_PARSED] <= horizon_14)
        mask_30 = close_notna & (active_df[COL_CLOSE_DATE_PARSED] >= ctx.today) & (active_df[COL_CLOSE_DATE_PARSED] <= horizon_30)

        time_buckets["next_14_days"] = bucket_stats(mask_14)
        time_buckets["next_30_days"] = bucket_stats(mask_30)

        q_start, q_end = get_fiscal_quarter_bounds(ctx.today)
        mask_q = close_notna & (active_df[COL_CLOSE_DATE_PARSED] >= q_start) & (active_df[COL_CLOSE_DATE_PARSED] <= q_end)
        mask_rest_q = mask_q & (~mask_30)
        time_buckets["rest_of_quarter"] = bucket_stats(mask_rest_q)

    data["time_buckets"] = time_buckets

    quarter_data: Dict[str, Any] = {}
    if COL_CLOSE_DATE_PARSED in active_df.columns:
        q_start, q_end = get_fiscal_quarter_bounds(ctx.today)

        mask_q = (
            active_df[COL_CLOSE_DATE_PARSED].notna()
            & (active_df[COL_CLOSE_DATE_PARSED] >= q_start)
            & (active_df[COL_CLOSE_DATE_PARSED] <= q_end)
        )
        q_df = active_df[mask_q].copy()

        total_pipeline_q = q_df[COL_AMOUNT_CLEAN].sum()
        total_commit_q = q_df.loc[q_df[COL_STAGE_CLASS] == "commit", COL_AMOUNT_CLEAN].sum()

        q_sorted = q_df.sort_values(COL_AMOUNT_CLEAN, ascending=False)
        top10 = q_sorted.head(10)
        top3 = q_sorted.head(3)

        top10_sum = top10[COL_AMOUNT_CLEAN].sum()
        top3_sum = top3[COL_AMOUNT_CLEAN].sum()

        quarter_data["total_pipeline_this_quarter"] = float(total_pipeline_q)
        quarter_data["total_commit_this_quarter"] = float(total_commit_q)
        quarter_data["top10_sum_amount"] = float(top10_sum)
        quarter_data["top10_share_of_total"] = float(top10_sum / total_pipeline_q) if total_pipeline_q > 0 else None
        quarter_data["top3_share_of_total"] = float(top3_sum / total_pipeline_q) if total_pipeline_q > 0 else None

        bookings_in_q = bookings_df.copy()
        if COL_CLOSE_DATE_PARSED in bookings_in_q.columns:
            bmask_q = (
                bookings_in_q[COL_CLOSE_DATE_PARSED].notna()
                & (bookings_in_q[COL_CLOSE_DATE_PARSED] >= q_start)
                & (bookings_in_q[COL_CLOSE_DATE_PARSED] <= q_end)
            )
            bookings_in_q = bookings_in_q[bmask_q]
        bookings_amount_q = bookings_in_q[COL_AMOUNT_CLEAN].sum() if not bookings_in_q.empty else 0.0

        if ctx.bookings_to_date_current_quarter > 0:
            bookings_effective = ctx.bookings_to_date_current_quarter
            bookings_source = "env_or_cli"
        else:
            bookings_effective = bookings_amount_q
            bookings_source = "calculated_from_bookings_df"

        quarter_data["team_target_current_quarter"] = float(ctx.team_target_current_quarter)
        quarter_data["bookings_this_quarter"] = float(bookings_effective)
        quarter_data["bookings_this_quarter_source"] = bookings_source

        gap = ctx.team_target_current_quarter - bookings_effective
        quarter_data["gap_to_target_vs_booked"] = float(gap)

        coverage = (bookings_effective + total_pipeline_q) / ctx.team_target_current_quarter if ctx.team_target_current_quarter > 0 else None
        quarter_data["coverage_vs_target"] = float(coverage) if coverage is not None else None
        quarter_data["pipeline_covering_gap_ratio"] = float(total_pipeline_q / gap) if gap > 0 else None

    data["quarter_concentration"] = quarter_data

    discovery_alerts: Dict[str, Any] = {}
    if COL_CLOSE_DATE_PARSED in active_df.columns:
        rules = ctx.rules
        horizon_14 = ctx.today + timedelta(days=rules["horizon_days_short"])
        mask_discovery = (
            active_df[COL_CLOSE_DATE_PARSED].notna()
            & (active_df[COL_CLOSE_DATE_PARSED] >= ctx.today)
            & (active_df[COL_CLOSE_DATE_PARSED] <= horizon_14)
            & (active_df[COL_STAGE].isin(["Discovery", "Qualification"]))
        )
        disc_df = active_df[mask_discovery].copy()
        total_disc_amount = disc_df[COL_AMOUNT_CLEAN].sum() if not disc_df.empty else 0.0

        per_ae: Dict[str, Any] = {}
        if not disc_df.empty and COL_AE in disc_df.columns:
            for ae, sub in disc_df.groupby(COL_AE):
                per_ae[str(ae)] = {
                    "nr_deals": int(len(sub)),
                    "total_amount": float(sub[COL_AMOUNT_CLEAN].sum()),
                }

        discovery_alerts["nr_team_deals"] = int(len(disc_df))
        discovery_alerts["total_team_amount"] = float(total_disc_amount)
        discovery_alerts["per_ae"] = per_ae

    data["discovery_hygiene_alerts"] = discovery_alerts

    ae_scorecards: Dict[str, Any] = {}
    if COL_AE in active_df.columns:
        rules = ctx.rules
        horizon_14 = ctx.today + timedelta(days=rules["horizon_days_short"])
        threshold_score = float(rules["next_step_low_score_threshold"])

        for ae, sub in active_df.groupby(COL_AE):
            sub = sub.copy()
            total_pipeline = sub[COL_AMOUNT_CLEAN].sum()
            commit = sub.loc[sub[COL_STAGE_CLASS] == "commit", COL_AMOUNT_CLEAN].sum()
            upside = sub.loc[sub[COL_STAGE_CLASS] == "upside", COL_AMOUNT_CLEAN].sum()
            green = sub.loc[sub[COL_STAGE_CLASS] == "green upside", COL_AMOUNT_CLEAN].sum()

            nr_deals = len(sub)
            overdue_mask_ae = sub[COL_CLOSE_DATE_PARSED].notna() & (sub[COL_CLOSE_DATE_PARSED] < ctx.today)
            nr_overdue = int(overdue_mask_ae.sum())

            no_next_step_mask_ae = sub[COL_NEXT_STEPS].isna() | (sub[COL_NEXT_STEPS].astype(str).str.strip() == "")
            nr_no_next_step = int(no_next_step_mask_ae.sum())

            nr_amount_zero = int((sub[COL_AMOUNT_CLEAN] <= 0).sum())

            disc_soon_mask = (
                sub[COL_CLOSE_DATE_PARSED].notna()
                & (sub[COL_CLOSE_DATE_PARSED] >= ctx.today)
                & (sub[COL_CLOSE_DATE_PARSED] <= horizon_14)
                & (sub[COL_STAGE].isin(["Discovery", "Qualification"]))
            )
            nr_disc_soon = int(disc_soon_mask.sum())

            deals_14_mask = (
                sub[COL_CLOSE_DATE_PARSED].notna()
                & (sub[COL_CLOSE_DATE_PARSED] >= ctx.today)
                & (sub[COL_CLOSE_DATE_PARSED] <= horizon_14)
            )
            deals_14 = sub[deals_14_mask].copy()

            deals_14_list: List[Dict[str, Any]] = []
            if not deals_14.empty:
                deals_14 = deals_14.sort_values(
                    by=[COL_CLOSE_DATE_PARSED, COL_AMOUNT_CLEAN],
                    ascending=[True, False],
                )
                for _, d14 in deals_14.iterrows():
                    score_14 = extract_health_score(d14.get("next_step_health"))
                    deals_14_list.append({
                        "account_name": str(d14.get(COL_ACCOUNT, "")),
                        "opportunity_name": str(d14.get(COL_OPPORTUNITY, "")),
                        "amount": float(d14.get(COL_AMOUNT_CLEAN, 0.0)),
                        "stage": str(d14.get(COL_STAGE, "")),
                        "forecast_category": str(d14.get(COL_FORECAST_CATEGORY, "")),
                        "close_date": str(d14.get(COL_CLOSE_DATE_PARSED) or ""),
                        "next_step_health_score": float(score_14) if score_14 is not None else None,
                    })

            deals_next_14_block = {
                "nr_deals": int(len(deals_14_list)),
                "total_amount": float(sum(d["amount"] for d in deals_14_list)),
                "deals": deals_14_list,
            }

            scores_ae: List[float] = []
            lowest_score: Optional[float] = None
            nr_low_health_next_steps = 0
            for _, d in sub.iterrows():
                score_val = extract_health_score(d.get("next_step_health"))
                if score_val is not None:
                    scores_ae.append(score_val)
                    if lowest_score is None or score_val < lowest_score:
                        lowest_score = score_val
                    if score_val < threshold_score:
                        nr_low_health_next_steps += 1
            avg_health_ae = sum(scores_ae) / len(scores_ae) if scores_ae else None

            largest_deal_amount = float(sub[COL_AMOUNT_CLEAN].max()) if not sub.empty else 0.0

            hygiene_score = 100
            hygiene_score -= 2 * nr_overdue
            hygiene_score -= 3 * nr_no_next_step
            hygiene_score -= 1 * nr_amount_zero
            hygiene_score -= 2 * nr_disc_soon
            if avg_health_ae is not None and avg_health_ae < 7:
                hygiene_score -= int((7 - avg_health_ae) * 3)
            if hygiene_score < 0:
                hygiene_score = 0

            sub_sorted = sub.sort_values(COL_AMOUNT_CLEAN, ascending=False).head(5)
            top5_list: List[Dict[str, Any]] = []
            for rank, (_, dtop) in enumerate(sub_sorted.iterrows(), start=1):
                created_raw = dtop.get(COL_CREATED_DATE)
                created_parsed = None
                try:
                    created_parsed = pd.to_datetime(created_raw, errors="coerce").date()
                except Exception:
                    created_parsed = None

                age_days = (ctx.today - created_parsed).days if created_parsed else None

                top5_list.append({
                    "rank": int(rank),
                    "account_name": str(dtop.get(COL_ACCOUNT, "")),
                    "opportunity_name": str(dtop.get(COL_OPPORTUNITY, "")),
                    "amount": float(dtop.get(COL_AMOUNT_CLEAN, 0.0)),
                    "stage": str(dtop.get(COL_STAGE, "")),
                    "forecast_category": str(dtop.get(COL_FORECAST_CATEGORY, "")),
                    "close_date": str(dtop.get(COL_CLOSE_DATE_PARSED) or ""),
                    "created_date": str(created_parsed) if created_parsed else None,
                    "age_in_days": int(age_days) if age_days is not None else None,
                })

            top_5_deals_block = {
                "nr_deals": int(len(top5_list)),
                "total_amount": float(sum(d["amount"] for d in top5_list)),
                "deals": top5_list,
            }

            issue_deals: List[Dict[str, Any]] = []

            nr_missing_next_step = 0
            nr_low_health_issues = 0
            nr_both = 0

            for _, d in sub.iterrows():
                next_step_text = str(d.get(COL_NEXT_STEPS) or "").strip()
                has_next_step = bool(next_step_text)

                health_raw = d.get("next_step_health")
                health_score = extract_health_score(health_raw)
                health_reason = None
                if isinstance(health_raw, dict):
                    health_reason = health_raw.get("reason")

                is_missing = not has_next_step
                is_low = health_score is not None and health_score < threshold_score

                if is_missing:
                    nr_missing_next_step += 1
                if is_low:
                    nr_low_health_issues += 1
                if is_missing and is_low:
                    nr_both += 1

                if is_missing or is_low:
                    issue_deals.append({
                        "account_name": str(d.get(COL_ACCOUNT, "")),
                        "opportunity_name": str(d.get(COL_OPPORTUNITY, "")),
                        "amount": float(d.get(COL_AMOUNT_CLEAN, 0.0)),
                        "stage": str(d.get(COL_STAGE, "")),
                        "forecast_category": str(d.get(COL_FORECAST_CATEGORY, "")),
                        "close_date": str(d.get(COL_CLOSE_DATE_PARSED) or ""),
                        "next_step_present": bool(has_next_step),
                        "next_step_text": next_step_text if has_next_step else None,
                        "next_step_health_score": float(health_score) if health_score is not None else None,
                        "next_step_health_reason": str(health_reason) if health_reason else None,
                        "flags": {
                            "missing_next_step": bool(is_missing),
                            "low_health": bool(is_low),
                        }
                    })

            next_step_issues_block = {
                "summary": {
                    "threshold_score": float(threshold_score),
                    "nr_deals_missing_next_step": int(nr_missing_next_step),
                    "nr_deals_low_health": int(nr_low_health_issues),
                    "nr_deals_both": int(nr_both),
                },
                "deals": issue_deals,
            }

            ae_scorecards[str(ae)] = {
                "total_pipeline": float(total_pipeline),
                "commit": float(commit),
                "upside": float(upside),
                "green_upside": float(green),
                "nr_deals": int(nr_deals),
                "nr_overdue_deals": int(nr_overdue),
                "nr_deals_no_next_step": int(nr_no_next_step),
                "nr_deals_amount_zero": int(nr_amount_zero),
                "nr_discovery_closing_14d": int(nr_disc_soon),
                "avg_next_step_health": float(avg_health_ae) if avg_health_ae is not None else None,
                "lowest_next_step_score": float(lowest_score) if lowest_score is not None else None,
                "nr_low_health_next_steps": int(nr_low_health_next_steps),
                "largest_deal_amount": float(largest_deal_amount),
                "hygiene_score": int(hygiene_score),
                "top_5_deals": top_5_deals_block,
                "next_step_issues": next_step_issues_block,
                "deals_next_14_days": deals_next_14_block,
            }

    data["ae_scorecards"] = ae_scorecards

    sorted_all = active_df.sort_values(COL_AMOUNT_CLEAN, ascending=False)
    top10 = sorted_all.head(10)
    top10_list: List[Dict[str, Any]] = []
    for _, d in top10.iterrows():
        top10_list.append(
            {
                "ae": str(d.get(COL_AE, "")),
                "account_name": str(d.get(COL_ACCOUNT, "")),
                "opportunity_name": str(d.get(COL_OPPORTUNITY, "")),
                "amount": float(d.get(COL_AMOUNT_CLEAN, 0.0)),
                "stage": str(d.get(COL_STAGE, "")),
                "forecast_category": str(d.get(COL_FORECAST_CATEGORY, "")),
                "close_date": str(d.get(COL_CLOSE_DATE_PARSED) or ""),
                "next_step_health_score": float(extract_health_score(d.get("next_step_health")) or 0.0),
            }
        )

    data["top10_deals"] = top10_list

    print("[pipeline] build_management_data() voltooid")
    return data


# === Output schrijven ===

def ensure_output_dir(output_dir: str) -> None:
    if not output_dir:
        raise RuntimeError("[pipeline] output_dir is leeg. Verwacht een geldige output directory.")
    print(f"[pipeline] Zorg dat output directory bestaat: {output_dir}")
    os.makedirs(output_dir, exist_ok=True)


def write_management_data(data: Dict[str, Any], output_dir: str) -> None:
    """Schrijf de gestructureerde management data naar JSON (timestamped en latest)."""
    if not output_dir:
        raise RuntimeError("[pipeline] output_dir is leeg. Verwacht een geldige output directory.")

    print("[pipeline] Schrijf management data naar JSON")
    ensure_output_dir(output_dir)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    ts_file = os.path.join(output_dir, f"pipeline_management_data_{ts}.json")
    latest_file = os.path.join(output_dir, "pipeline_management_data_latest.json")

    with open(ts_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_reports(text: str, output_dir: str) -> None:
    if not output_dir:
        raise RuntimeError("[pipeline] output_dir is leeg. Verwacht een geldige output directory.")

    print("[pipeline] Schrijf rapporten naar bestanden (timestamped en latest)")
    ensure_output_dir(output_dir)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    ts_file = os.path.join(output_dir, f"ae_pipeline_summary_{ts}.txt")
    latest_file = os.path.join(output_dir, "ae_pipeline_summary_latest.txt")

    with open(ts_file, "w", encoding="utf-8") as f:
        f.write(text)

    with open(latest_file, "w", encoding="utf-8") as f:
        f.write(text)


def write_management_summary(text: str, output_dir: str) -> None:
    if not output_dir:
        raise RuntimeError("[pipeline] output_dir is leeg. Verwacht een geldige output directory.")

    print("[pipeline] Schrijf management summary naar bestanden (timestamped en latest)")
    ensure_output_dir(output_dir)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    ts_file = os.path.join(output_dir, f"management_summary_{ts}.txt")
    latest_file = os.path.join(output_dir, "management_summary_latest.txt")

    with open(ts_file, "w", encoding="utf-8") as f:
        f.write(text)

    with open(latest_file, "w", encoding="utf-8") as f:
        f.write(text)


# === main ===

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pipeline analyse voor AE-team")
    parser.add_argument(
        "--team-target",
        type=float,
        default=None,
        help="Team target voor het huidige kwartaal (override van env TEAM_TARGET_CURRENT_QUARTER).",
    )
    parser.add_argument(
        "--bookings-to-date",
        type=float,
        default=None,
        help="Bookings-to-date voor het huidige kwartaal (override van env BOOKINGS_TO_DATE_CURRENT_QUARTER).",
    )
    parser.add_argument(
        "--mapping",
        type=str,
        default=None,
        help="Pad naar mapping JSON voor pipeline (default: mappings/salesforce_pipeline.json).",
    )
    parser.add_argument(
        "--today",
        type=str,
        default=None,
        help="Override de 'vandaag' datum voor reproduceerbare runs. Formaat: YYYY-MM-DD",
    )
    return parser.parse_args()


def main() -> None:
    print("[pipeline] === Pipeline analyse gestart ===")

    cfg = load_config()
    global CALENDAR_CFG, RULES_CFG
    CALENDAR_CFG = cfg.get("calendar", {}) or {}
    RULES_CFG = cfg.get("rules", {}) or {}

    data_dir = cfg["paths"]["data_dir_abs"]
    output_dir = cfg["paths"]["outputs_dir_abs"]

    cal = _get_calendar_cfg()
    rules = _get_rules_cfg()

    print(f"[pipeline] Data dir (config): {data_dir}")
    print(f"[pipeline] Output dir (config): {output_dir}")
    print(f"[pipeline] Calendar (config): FY start {cal['fiscal_year_start_month']:02d}-{cal['fiscal_year_start_day']:02d}")
    print(
        f"[pipeline] Rules (config): horizon_short={rules['horizon_days_short']} "
        f"horizon_medium={rules['horizon_days_medium']} low_score<{rules['next_step_low_score_threshold']}"
    )
    print("[pipeline] Run tip: python3 -m python.pipeline.pipeline_analyse")

    args = parse_args()
    # Determine today_value, optionally overridden via --today
    today_value = date.today()
    if args.today:
        try:
            today_value = datetime.strptime(args.today.strip(), "%Y-%m-%d").date()
            print(f"[pipeline] Override TODAY via CLI: {today_value}")
        except ValueError:
            raise ValueError("Ongeldig formaat voor --today. Gebruik YYYY-MM-DD, bijv. 2025-12-14")

    team_target_value = float(os.getenv("TEAM_TARGET_CURRENT_QUARTER", "0") or 0)
    bookings_to_date_value = float(os.getenv("BOOKINGS_TO_DATE_CURRENT_QUARTER", "0") or 0)

    if args.team_target is not None:
        team_target_value = float(args.team_target)
        print(f"[pipeline] Override TEAM_TARGET_CURRENT_QUARTER via CLI: {team_target_value:,.0f}")

    if args.bookings_to_date is not None:
        bookings_to_date_value = float(args.bookings_to_date)
        print(f"[pipeline] Override BOOKINGS_TO_DATE_CURRENT_QUARTER via CLI: {bookings_to_date_value:,.0f}")

    llm_cfg = get_llm_config(cfg)
    ctx = AnalysisContext(
        today=today_value,
        data_dir=data_dir or "",
        output_dir=output_dir or "",
        calendar=_get_calendar_cfg(),
        rules=_get_rules_cfg(),
        team_target_current_quarter=float(team_target_value),
        bookings_to_date_current_quarter=float(bookings_to_date_value),
        llm_config=llm_cfg,
    )

    csv_path = get_latest_csv(ctx.data_dir)
    df = load_csv(csv_path)

    project_root = Path(__file__).resolve().parents[2]
    mapping_path = args.mapping or str(project_root / DEFAULT_PIPELINE_MAPPING)
    print(f"[pipeline] Mapping gebruiken: {mapping_path}")

    mapping_applied = False
    try:
        mapping = load_mapping(mapping_path)
        df = map_dataframe(df, mapping)
        mapping_applied = True
        print("[pipeline] Mapping toegepast. Verwacht canonical kolommen.")
    except Exception as e:
        print("[pipeline][ERROR] Mapping stap faalde. Probeer Salesforce export te canonicalizen via fallback mapping.")
        print(f"[pipeline][ERROR] Exception: {repr(e)}")

    if not mapping_applied:
        # Fallback: Salesforce export kolommen -> canonical kolommen
        df = df.rename(columns={k: v for k, v in SF_EXPORT_TO_CANONICAL.items() if k in df.columns})
        missing = [c for c in (COL_ACCOUNT, COL_OPPORTUNITY, COL_STAGE, COL_FORECAST_CATEGORY, COL_AMOUNT, COL_CLOSE_DATE, COL_CREATED_DATE, COL_AE, COL_NEXT_STEPS) if c not in df.columns]
        if missing:
            print(f"[pipeline][WAARSCHUWING] Niet alle canonical kolommen aanwezig na fallback canonicalize: {missing}")

    active_df, bookings_df, omitted_df = run_analysis(ctx, df)
    management_data = build_management_data(ctx, active_df, bookings_df, omitted_df)

    report_text = build_ae_reports(ctx, active_df, bookings_df, omitted_df)
    print("[pipeline] AE-rapport klaar, start schrijven naar files...")
    write_reports(report_text, ctx.output_dir)
    write_management_data(management_data, ctx.output_dir)

    print("Pipeline analyse voltooid. Output geschreven naar:")
    out_dir = ctx.output_dir or "outputs"
    print(f" - {os.path.join(out_dir, 'ae_pipeline_summary_latest.txt')}")
    print(f" - {os.path.join(out_dir, 'pipeline_management_data_latest.json')}")


if __name__ == "__main__":
    main()