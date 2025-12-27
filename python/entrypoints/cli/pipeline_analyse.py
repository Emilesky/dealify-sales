"""\
CLI adapter for running the Dealify pipeline analysis.

Responsibilities:
- Parse CLI arguments
- Load runtime configuration
- Invoke the pipeline execution flow (analysis + builders)
- Persist outputs (JSON/TXT)

Non-responsibilities:
- Business rules, domain logic, and aggregations should live in dedicated modules
  (analysis.py, management_builders.py, reports.py, etc.).

Note:
This module should remain thin so it can later be replaced by an API/worker adapter
without changing the core behavior.
"""

from __future__ import annotations



import argparse
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict

from python.app.config import get_llm_config, load_config
from python.application.bootstrap_pipeline import run_pipeline_app

DEFAULT_PIPELINE_MAPPING = "mappings/salesforce_pipeline.json"


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


def _get_calendar_cfg(calendar_cfg: Dict[str, Any] | None) -> Dict[str, Any]:
    # Defaults are safe fallbacks
    cal = calendar_cfg or {}
    return {
        "fiscal_year_start_month": int(cal.get("fiscal_year_start_month", 2)),
        "fiscal_year_start_day": int(cal.get("fiscal_year_start_day", 1)),
    }


def _get_rules_cfg(rules_cfg: Dict[str, Any] | None) -> Dict[str, Any]:
    rules = rules_cfg or {}
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
        help=(
            "Sla LLM Next Step health verrijking over. Let op: analyse draait altijd zonder LLM; "
            "verrijking gebeurt expliciet in de use case."
        ),
    )
    parser.add_argument(
        "--output-scope",
        type=str,
        choices=["management", "extended", "full"],
        default="management",
        help="Bepaalt hoeveel detail in de management JSON wordt opgenomen (default: management).",
    )
    return parser.parse_args()


def main() -> None:
    print("[pipeline] === Pipeline analyse gestart ===")

    cfg = load_config()

    calendar_cfg = cfg.get("calendar", {}) or {}
    rules_cfg = cfg.get("rules", {}) or {}

    data_dir = cfg["paths"]["data_dir_abs"]
    output_dir = cfg["paths"]["outputs_dir_abs"]

    cal = _get_calendar_cfg(calendar_cfg)
    rules = _get_rules_cfg(rules_cfg)

    print(f"[pipeline] Data dir (config): {data_dir}")
    print(f"[pipeline] Output dir (config): {output_dir}")
    print(
        f"[pipeline] Calendar (config): FY start {cal['fiscal_year_start_month']:02d}-{cal['fiscal_year_start_day']:02d}"
    )
    print(
        f"[pipeline] Rules (config): horizon_short={rules['horizon_days_short']} "
        f"horizon_medium={rules['horizon_days_medium']} low_score<{rules['next_step_low_score_threshold']}"
    )
    print("[pipeline] Run tip: python3 -m python.entrypoints.cli.pipeline_analyse")

    # CLI inputs (adapter layer)
    args = parse_args()

    print(f"[pipeline] Output scope (CLI): {args.output_scope}")

    if args.no_llm:
        print("[pipeline] LLM Next Step health verrijking is uitgeschakeld (--no-llm).")
    else:
        print(
            "[pipeline] LLM Next Step health verrijking is ingeschakeld. "
            "Analyse draait zonder LLM; verrijking gebeurt expliciet in de use case."
        )

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
        calendar=cal,
        rules=rules,
        team_target_current_quarter=float(team_target_value),
        bookings_to_date_current_quarter=float(bookings_to_date_value),
        llm_config=llm_cfg,
    )

    project_root = Path(__file__).resolve().parents[3]
    mapping_path = args.mapping or str(project_root / DEFAULT_PIPELINE_MAPPING)
    print(f"[pipeline] Mapping gebruiken: {mapping_path}")

    run_pipeline_app(ctx, args, mapping_path=mapping_path)

    print("Pipeline analyse voltooid. Output geschreven naar:")
    out_dir = ctx.output_dir or "outputs"
    print(f" - {os.path.join(out_dir, 'ae_pipeline_summary_latest.txt')}")
    print(f" - {os.path.join(out_dir, 'pipeline_management_data_latest.json')}")


if __name__ == "__main__":
    main()
