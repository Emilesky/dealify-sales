from __future__ import annotations

import os
import argparse
from datetime import datetime, date
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict

import pandas as pd

from python.app.config import load_config, get_llm_config
from python.pipeline.mapping import load_mapping, map_dataframe
from python.pipeline.analysis import run_analysis
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
    SF_EXPORT_TO_CANONICAL,
)
from python.pipeline.io import (
    get_latest_csv,
    load_csv,
    write_reports,
    write_management_data,
)
from python.pipeline.reports import build_ae_reports
from python.pipeline.management import build_management_data


DEFAULT_PIPELINE_MAPPING = "mappings/salesforce_pipeline.json"

CALENDAR_CFG: Dict[str, Any] = {}
RULES_CFG: Dict[str, Any] = {}


@dataclass
class AnalysisContext:
    today: date
    data_dir: str
    output_dir: str
    calendar: Dict[str, Any]
    rules: Dict[str, Any]
    team_target_current_quarter: float
    bookings_to_date_current_quarter: float
    llm_config: Any


def _get_calendar_cfg() -> Dict[str, Any]:
    # Defaults are safe fallbacks
    cal = CALENDAR_CFG or {}
    return {
        "fiscal_year_start_month": int(cal.get("fiscal_year_start_month", 2)),
        "fiscal_year_start_day": int(cal.get("fiscal_year_start_day", 1)),
    }


def _get_rules_cfg() -> Dict[str, Any]:
    rules = RULES_CFG or {}
    return {
        "next_step_low_score_threshold": float(rules.get("next_step_low_score_threshold", 5.0)),
        "horizon_days_short": int(rules.get("horizon_days_short", 14)),
        "horizon_days_medium": int(rules.get("horizon_days_medium", 30)),
    }


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
        help=f"Pad naar mapping JSON voor pipeline (default: {DEFAULT_PIPELINE_MAPPING}).",
    )
    parser.add_argument(
        "--today",
        type=str,
        default=None,
        help="Override de 'vandaag' datum voor reproduceerbare runs. Formaat: YYYY-MM-DD",
    )
    parser.add_argument(
        "--no-llm",
        "--skip-llm",
        action="store_true",
        help="Sla de LLM Next Step health verrijking over (sneller, geen Ollama/SaaS nodig).",
    )
    return parser.parse_args()


def main() -> None:
    print("[pipeline] === Pipeline analyse gestart ===")

    cfg = load_config()

    # Keep global config for helper functions (compatible with current setup)
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

    csv_path = get_latest_csv(ctx.data_dir, name_contains="pipeline")
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
        required = (COL_ACCOUNT, COL_OPPORTUNITY, COL_STAGE, COL_FORECAST_CATEGORY, COL_AMOUNT, COL_CLOSE_DATE, COL_CREATED_DATE, COL_AE, COL_NEXT_STEPS)
        missing = [c for c in required if c not in df.columns]
        if missing:
            print(f"[pipeline][WAARSCHUWING] Niet alle canonical kolommen aanwezig na fallback canonicalize: {missing}")

    active_df, bookings_df, omitted_df = run_analysis(ctx, df, enable_llm=not args.no_llm)

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