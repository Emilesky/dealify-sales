import json
import os
from datetime import datetime
from typing import Optional, Tuple

from python.app.config import load_config


def _load_cfg() -> dict:
    """Load config.json once per run."""
    return load_config()


def _get_paths(cfg: dict) -> Tuple[str, str, str]:
    """Resolve input/output paths via config.json. Returns (outputs_dir, input_file, output_file)."""
    paths = cfg.get("paths", {})
    outputs_dir = paths.get("outputs_dir_abs") or paths.get("outputs_dir")
    if not outputs_dir:
        raise KeyError("'paths.outputs_dir_abs' ontbreekt in config.json")

    input_file = os.path.join(outputs_dir, "pipeline_management_data_latest.json")
    output_file = os.path.join(outputs_dir, "weekly_llm_input_latest.json")
    return outputs_dir, input_file, output_file

# Tuning parameters voor risico
MIN_HYGIENE_SCORE_RISK = 6.0      # lager dan dit = risico
MAX_OVERDUE_DEALS_RISK = 5        # meer dan dit = risico
MAX_NO_NEXT_STEP_RISK = 5         # meer dan dit = risico
MIN_LOW_HEALTH_DEALS_RISK = 3     # 3 of meer low health next steps = risico
MAX_RISK_AE_IN_LLM = 5          # max aantal risico-AE's in LLM-input


def truncate_text(text: Optional[str], max_len: int = 160) -> Optional[str]:
    """Kort tekst veilig af tot max_len tekens om LLM-payload klein te houden."""
    if not text:
        return text
    text = str(text).strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "…"


def load_management_data(input_file: str) -> dict | None:
    """Laad de volledige management JSON (mega file)."""
    if not os.path.exists(input_file):
        print(f"[filter] FOUT: inputbestand niet gevonden: {input_file}")
        return None

    try:
        with open(input_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"[filter] Volledige managementdata geladen uit: {input_file}")
        return data
    except Exception as e:
        print(f"[filter] FOUT bij laden van JSON: {e}")
        return None


def build_llm_input(data: dict, source_file: str) -> dict:
    """
    Bouw een compacte JSON speciaal voor de wekelijkse LLM-managementscan.
    Focus op:
    - team overview
    - risico-AE's
    - topdeals overall
    """
    team_src = data.get("team_overview", {}) or {}
    quarter_src = data.get("quarter_concentration", {}) or {}
    ae_src = data.get("ae_scorecards", {}) or {}
    top_deals_src = data.get("top_10_deals", []) or []
    if not top_deals_src:
        # Fallback to quarter concentration top deals if overall top_10_deals is not present
        top_deals_src = quarter_src.get("top5_in_quarter", []) or []

    hygiene_src = data.get("discovery_hygiene_alerts", {}) or {}

    llm_team = {
        # New pipeline JSON (team_overview builder)
        "team_target_current_quarter": team_src.get("target"),
        "bookings_to_date_current_quarter": team_src.get("bookings_to_date"),
        "gap_to_target": team_src.get("gap_to_target"),
        "coverage_ratio": team_src.get("coverage_ratio"),
        # Backwards/optional fields (not available in new core yet)
        "pipeline_covering_gap_ratio": None,
        "total_pipeline": team_src.get("active_pipeline"),
        "commit": None,
        "upside": None,
        "green_upside": None,
        "nr_active_deals": (team_src.get("counts") or {}).get("nr_active_deals"),
        "nr_overdue_deals": hygiene_src.get("nr_overdue_deals"),
        "nr_deals_no_next_step": hygiene_src.get("nr_deals_no_next_step"),
    }

    def _derive_hygiene_score(ae_payload: dict) -> Optional[float]:
        """Derive a lightweight hygiene score for risk triage.

        New ae_scorecards provide hygiene counts + next_step_health stats, but not a single hygiene_score.
        We compute a conservative score in [0, 10] so existing weekly_filter thresholds keep working.
        """
        hygiene = ae_payload.get("hygiene") or {}
        nr_overdue = hygiene.get("nr_overdue_deals", 0) or 0
        nr_no_next_step = hygiene.get("nr_deals_no_next_step", 0) or 0
        nsh = hygiene.get("next_step_health") or {}
        avg_nsh = nsh.get("avg")
        low_nsh = nsh.get("low_count", 0) or 0

        # Base score: if we have an avg next_step_health, start there; else start at 10.
        base = float(avg_nsh) if avg_nsh is not None else 10.0
        # Penalties: keep simple and monotonic (no magic)
        score = base - (0.5 * nr_overdue) - (0.5 * nr_no_next_step) - (1.0 * low_nsh)
        # Clamp
        if score < 0:
            score = 0.0
        if score > 10:
            score = 10.0
        return score

    # Per AE: alleen de AE's die echt aandacht vragen (risico-AE's)
    llm_ae_risk: dict[str, dict] = {}

    for ae_name, ae in ae_src.items():
        # Support old ae_scorecards format (flat fields) and new format (nested hygiene + top_deals)
        hygiene = ae.get("hygiene") or {}
        nsh = hygiene.get("next_step_health") or {}

        hygiene_score = ae.get("hygiene_score")
        if hygiene_score is None:
            hygiene_score = _derive_hygiene_score(ae)

        nr_overdue = ae.get("nr_overdue_deals")
        if nr_overdue is None:
            nr_overdue = hygiene.get("nr_overdue_deals", 0) or 0

        nr_no_next_step = ae.get("nr_deals_no_next_step")
        if nr_no_next_step is None:
            nr_no_next_step = hygiene.get("nr_deals_no_next_step", 0) or 0

        # Not provided by the new builder yet; keep for backward compat
        nr_discovery_14d = ae.get("nr_discovery_closing_14d", 0) or 0

        avg_next_step_health = ae.get("avg_next_step_health")
        if avg_next_step_health is None:
            avg_next_step_health = nsh.get("avg")

        nr_low_health_next_steps = ae.get("nr_low_health_next_steps")
        if nr_low_health_next_steps is None:
            nr_low_health_next_steps = nsh.get("low_count", 0) or 0

        # Bepaal of deze AE in de "risico" view moet komen
        is_risky = False

        if hygiene_score is not None and hygiene_score < MIN_HYGIENE_SCORE_RISK:
            is_risky = True
        if nr_overdue > MAX_OVERDUE_DEALS_RISK:
            is_risky = True
        if nr_no_next_step > MAX_NO_NEXT_STEP_RISK:
            is_risky = True
        if nr_discovery_14d > 0:
            is_risky = True
        if avg_next_step_health is not None and avg_next_step_health < MIN_HYGIENE_SCORE_RISK:
            is_risky = True
        if nr_low_health_next_steps >= MIN_LOW_HEALTH_DEALS_RISK:
            is_risky = True

        # Als we al genoeg risico-AE's hebben opgenomen, skip de rest
        if len(llm_ae_risk) >= MAX_RISK_AE_IN_LLM and ae_name not in llm_ae_risk:
            # We hebben al genoeg risico-AE's geregistreerd
            continue

        if not is_risky:
            continue  # deze AE is relatief gezond, hoeft niet in de LLM-input

        # Basismetrics per AE
        base = {
            "total_pipeline": ae.get("total_pipeline") if ae.get("total_pipeline") is not None else ae.get("pipeline_amount"),
            "commit": ae.get("commit"),
            "upside": ae.get("upside"),
            "green_upside": ae.get("green_upside"),
            "hygiene_score": hygiene_score,
            "nr_deals": ae.get("nr_deals"),
            "nr_overdue_deals": nr_overdue,
            "nr_deals_no_next_step": nr_no_next_step,
            "nr_discovery_closing_14d": nr_discovery_14d,
            "avg_next_step_health": avg_next_step_health,
            "nr_low_health_next_steps": nr_low_health_next_steps,
        }

        # Topdeals per AE (max 2 om payload klein te houden)
        top_block = ae.get("top_5_deals") or {}
        if isinstance(top_block, dict):
            top_deals = (top_block.get("deals") or [])[:2]
        else:
            top_deals = []

        if not top_deals:
            # New format: top_deals is a list
            top_deals = (ae.get("top_deals") or [])[:2]

        stripped_top_deals = []
        for d in top_deals:
            stripped_top_deals.append({
                "account_name": d.get("account_name"),
                "opportunity_name": d.get("opportunity_name"),
                "amount": d.get("amount"),
                "stage": d.get("stage"),
                "forecast_category": d.get("forecast_category"),
                "close_date": d.get("close_date"),
                "age_in_days": d.get("age_in_days"),
            })

        base["top_deals"] = stripped_top_deals

        # Next-step issues (max 2 deals als sample)
        issues_block = ae.get("next_step_issues") or {}
        if not isinstance(issues_block, dict):
            issues_block = {}
        issue_deals = (issues_block.get("deals") or [])[:2]

        stripped_issues = []
        for d in issue_deals:
            stripped_issues.append({
                "account_name": d.get("account_name"),
                "opportunity_name": truncate_text(d.get("opportunity_name"), 160),
                "amount": d.get("amount"),
                "stage": d.get("stage"),
                "close_date": d.get("close_date"),
                "next_step_present": d.get("next_step_present"),
                "next_step_health_score": d.get("next_step_health_score"),
                # Indien in de toekomst beschikbaar: originele next step tekst, hard afgekapt
                "next_step_original_short": truncate_text(d.get("next_step_original"), 160),
                # Eventuele vrije tekst/flags ook inkorten
                "flags": truncate_text(d.get("flags"), 160),
            })

        base["next_step_issues"] = {
            "summary": truncate_text(issues_block.get("summary"), 160),
            "sample_deals": stripped_issues,
        }

        llm_ae_risk[ae_name] = base

    # Topdeals overall (max 5 om context kort te houden)
    llm_top_deals = []
    for d in top_deals_src[:5]:
        llm_top_deals.append({
            "account_name": d.get("account_name"),
            "opportunity_name": d.get("opportunity_name"),
            "amount": d.get("amount"),
            "stage": d.get("stage"),
            "forecast_category": d.get("forecast_category"),
            "close_date": d.get("close_date"),
        })

    # Deals met close date binnen 14 dagen (max 10, voor week- en 14-dagen-focus)
    llm_deals_14d = []
    deals_14d_src = (
        data.get("deals_closing_next_14_days")
        or data.get("deals_closing_14d")
        or []
    ) or []
    for d in deals_14d_src[:10]:
        llm_deals_14d.append({
            "account_name": d.get("account_name"),
            "opportunity_name": d.get("opportunity_name"),
            "amount": d.get("amount"),
            "stage": d.get("stage"),
            "forecast_category": d.get("forecast_category"),
            "close_date": d.get("close_date"),
            # indien aanwezig in de bron: next step health score
            "next_step_health_score": d.get("next_step_health_score"),
        })

    llm_data = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source_file": os.path.basename(source_file),
        },
        "team_overview": llm_team,
        "ae_risk": llm_ae_risk,
        "top_deals_overall": llm_top_deals,
        "deals_closing_next_14_days": llm_deals_14d,
    }

    return llm_data


def save_llm_input(llm_data: dict, outputs_dir: str, output_file: str) -> None:
    os.makedirs(outputs_dir, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(llm_data, f, ensure_ascii=False, indent=2)
    print(f"[filter] Compacte LLM-input geschreven naar: {output_file}")


def main():
    cfg = _load_cfg()
    outputs_dir, input_file, output_file = _get_paths(cfg)

    data = load_management_data(input_file)
    if data is None:
        return

    llm_data = build_llm_input(data, source_file=input_file)

    nr_ae_risk = len(llm_data.get("ae_risk", {}))
    print(f"[filter] Aantal risico-AE's in LLM-input: {nr_ae_risk}")

    save_llm_input(llm_data, outputs_dir=outputs_dir, output_file=output_file)
    print("[filter] Weekly filter run voltooid.")


if __name__ == "__main__":
    main()