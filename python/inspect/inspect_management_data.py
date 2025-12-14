import json
import argparse
from pathlib import Path

from python.app.config import load_config



def _get_outputs_dir() -> Path:
    cfg = load_config()
    paths = cfg.get("paths", {})
    outputs_dir = paths.get("outputs_dir_abs") or paths.get("outputs_dir")
    if not outputs_dir:
        raise KeyError("'paths.outputs_dir_abs' ontbreekt in config.json")
    return Path(outputs_dir)


def _get_json_path(override: str | None = None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    return _get_outputs_dir() / "pipeline_management_data_latest.json"


def load_data(json_path: str | None = None):
    path = _get_json_path(json_path)
    if not path.exists():
        raise FileNotFoundError(
            f"JSON bestand niet gevonden: {path}\n"
            "Tip: draai eerst pipeline_analyse of geef --file <pad-naar-json>."
        )
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def print_team_overview(data):
    print("=== team_overview ===")
    for k, v in data["team_overview"].items():
        print(f"{k:25}: {v}")


def print_quarter(data):
    print("=== quarter_concentration ===")
    for k, v in data.get("quarter_concentration", {}).items():
        print(f"{k:25}: {v}")


def list_aes(data):
    print("=== AE's in ae_scorecards ===")
    for name in sorted(data.get("ae_scorecards", {}).keys()):
        print(f"- {name}")


def print_ae(data, ae_name):
    ae_cards = data.get("ae_scorecards", {})
    card = ae_cards.get(ae_name)
    if not card:
        print(f"[!] AE niet gevonden in ae_scorecards: {ae_name}")
        print("Beschikbare AE's:")
        for name in sorted(ae_cards.keys()):
            print(f"- {name}")
        return

    print(f"=== AE scorecard: {ae_name} ===")
    fields = [
        "total_pipeline",
        "commit",
        "upside",
        "green_upside",
        "nr_deals",
        "nr_overdue_deals",
        "nr_deals_no_next_step",
        "nr_deals_amount_zero",
        "nr_discovery_closing_14d",
        "avg_next_step_health",
        "lowest_next_step_score",
        "nr_low_health_next_steps",
        "largest_deal_amount",
        "hygiene_score",
    ]
    for f in fields:
        print(f"{f:25}: {card.get(f)}")


def print_ae_next14(data, ae_name: str) -> None:
    ae_cards = data.get("ae_scorecards", {})
    card = ae_cards.get(ae_name)
    if not card:
        print(f"[!] AE niet gevonden in ae_scorecards: {ae_name}")
        print("Beschikbare AE's:")
        for name in sorted(ae_cards.keys()):
            print(f"- {name}")
        return

    block = card.get("deals_next_14_days") or {}
    print(f"=== AE deals next 14 days: {ae_name} ===")
    print(f"nr_deals      : {block.get('nr_deals')}")
    print(f"total_amount  : {block.get('total_amount')}")

    deals = block.get("deals") or []
    if not deals:
        print("(geen deals in de komende 14 dagen)")
        return

    for idx, d in enumerate(deals, start=1):
        print(f"{idx:02d}. {d.get('account_name', '')} - {d.get('opportunity_name', '')}")
        print(f"     Amount: {d.get('amount')} | Stage: {d.get('stage')} | FC: {d.get('forecast_category')}")
        print(f"     Close date: {d.get('close_date')} | Health: {d.get('next_step_health_score')}")
        print("")


def print_top10(data):
    print("=== top10_deals (team) ===")
    for i, deal in enumerate(data.get("top10_deals", []), start=1):
        print(f"{i:02d}. {deal['account_name']} - {deal['opportunity_name']}")
        print(f"     AE: {deal['ae']} | Amount: {deal['amount']:.0f} | Stage: {deal['stage']} | FC: {deal['forecast_category']}")
        print(f"     Close date: {deal['close_date']} | Health: {deal.get('next_step_health_score')}")
        print("")


def print_time_buckets(data):
    print("=== time_buckets ===")
    buckets = data.get("time_buckets", {})
    for name, bucket in buckets.items():
        print(f"[{name}]")
        for k, v in bucket.items():
            print(f"  {k:22}: {v}")
        print("")


def main():
    parser = argparse.ArgumentParser(description="Inspecteer pipeline_management_data_latest.json")
    parser.add_argument("--team", action="store_true", help="Toon team_overview")
    parser.add_argument("--quarter", action="store_true", help="Toon quarter_concentration")
    parser.add_argument("--list-ae", action="store_true", help="Toon lijst van AE-namen")
    parser.add_argument("--ae", type=str, help="Toon details van een specifieke AE (exacte naam)")
    parser.add_argument("--ae-next14", type=str, help="Toon deals_next_14_days voor een specifieke AE (exacte naam)")
    parser.add_argument("--top10", action="store_true", help="Toon top10_deals")
    parser.add_argument("--time-buckets", action="store_true", help="Toon time_buckets")
    parser.add_argument("--file", type=str, help="Optioneel pad naar pipeline_management_data JSON (default: outputs/pipeline_management_data_latest.json)")

    args = parser.parse_args()
    data = load_data(args.file)

    if not any([args.team, args.quarter, args.list_ae, args.ae, args.ae_next14, args.top10, args.time_buckets]):
        # default: korte overview
        print_team_overview(data)
        print("")
        print_quarter(data)
        print("")
        list_aes(data)
        return

    if args.team:
        print_team_overview(data)
        print("")

    if args.quarter:
        print_quarter(data)
        print("")

    if args.list_ae:
        list_aes(data)
        print("")

    if args.ae:
        print_ae(data, args.ae)
        print("")

    if args.ae_next14:
        print_ae_next14(data, args.ae_next14)
        print("")

    if args.top10:
        print_top10(data)
        print("")

    if args.time_buckets:
        print_time_buckets(data)
        print("")


if __name__ == "__main__":
    main()