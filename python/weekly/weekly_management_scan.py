import os
import json
import argparse
from datetime import datetime
from typing import Optional

from python.app.config import load_config, get_llm_config
from python.llm.client import run_llm as run_llm_core

# Paden worden in main() gezet op basis van config.json.
OUTPUTS_DIR = None
LLM_INPUT_FILE = None
PAYLOAD_DEBUG_FILE = None
SCAN_LATEST_FILE = None


def _load_cfg() -> dict:
    """Load config.json once per run."""
    return load_config()


def _get_outputs_dir(cfg: dict) -> str:
    paths = cfg.get("paths", {})
    outputs_dir = paths.get("outputs_dir_abs") or paths.get("outputs_dir")
    if not outputs_dir:
        raise KeyError("'paths.outputs_dir_abs' ontbreekt in config.json")
    return outputs_dir


def load_llm_input() -> dict:
    """Laad de compacte LLM-input JSON voor de wekelijkse managementscan."""
    if not LLM_INPUT_FILE:
        raise RuntimeError("[weekly-scan] LLM_INPUT_FILE is niet gezet. Draai via main() zodat config geladen wordt.")

    if not os.path.exists(LLM_INPUT_FILE):
        raise FileNotFoundError(
            f"LLM-inputbestand niet gevonden: {LLM_INPUT_FILE}\n"
            "Draai eerst: python -m python.weekly.weekly_filter"
        )

    with open(LLM_INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data


def load_extra_context(path: Optional[str]) -> str:
    """Laad optionele extra context van de RVP uit een tekstbestand."""
    if not path:
        return ""

    if not os.path.exists(path):
        raise FileNotFoundError(f"Contextbestand niet gevonden: {path}")

    with open(path, "r", encoding="utf-8") as f:
        text = f.read().strip()

    return text


def build_prompt(json_text: str, extra_context: str) -> str:
    """
    Bouw de volledige prompt voor de wekelijkse RVP-managementscan
    op basis van:
    - compacte JSON (weekly_llm_input_latest.json)
    - optionele extra context van de RVP
    """

    if extra_context:
        context_block = f"""
============================
AANVULLENDE CONTEXT VAN RVP
============================

{extra_context}
"""
    else:
        context_block = "\n(Geen aanvullende RVP-context deze week aangeleverd.)\n"

    prompt = f"""
Je bent mijn kritische, datagedreven management-analist op RVP-niveau in een IT-opleidingsbedrijf 
(enterprise, publieke sector, Microsoft, AWS, Cisco, AI, security, maatwerk).

Je analyseert uitsluitend op basis van:
- de aangeleverde JSON-data (team, AE's, topdeals, risico-indicatoren)
- optioneel een kort contextblok van mij als RVP

Je taak is NIET om algemeen verkoopadvies te geven, maar om:
- gedrag
- risico
- realistische weekverwachting
- en veiligheid richting het kwartaaldoel

te duiden.

BELANGRIJKE REGELS:
- Alles in helder NEDERLANDS
- GEEN generieke salescoaching of open deuren
- GEEN aannames buiten de data
- GEEN verzonnen bedragen of feiten
- Benoem onzekerheid expliciet waar die bestaat
- Als iets niet uit de data blijkt: schrijf letterlijk
  "Dit is op basis van deze data niet vast te stellen."

{context_block}

============================
PRIMAIRE DATA BRON (JSON)
============================
Dit is de compacte, gefilterde managementdata. 
Gebruik deze als enige feitelijke bron voor je analyse:

{json_text}

============================
JOUW OPDRACHT (WEKELIJKSE RVP MANAGEMENT SCAN)
============================

Beantwoord exact deze onderdelen, in deze volgorde en met duidelijke kopjes:

1) DEAL DISCIPLINE - GEDRAG VAN HET TEAM
- Wat zegt de manier waarop deals worden bijgehouden (next steps, overdue, hygiënescores) over:
  - discipline in opvolging
  - eigenaarschap per AE
  - afwachtend versus besluitgericht gedrag
  - schijnzekerheid in commit?
- Waar zie je structureel afwachtende of vage next steps, vooral op grote of kritieke deals?
- Welke AE's laten consistent beter gedrag zien, en welke juist niet?

2) VERWACHTING - WAT IS REALISTISCH VOOR DEZE WEEK EN KOMENDE 14 DAGEN
- Op basis van commit, sterke upside, next step kwaliteit, leeftijd en stage van deals:
  - Wat is een realistische bandbreedte van nieuwe bookings voor deze week?
  - Welke concrete voorwaarden moeten vervuld worden om de bovenkant van die bandbreedte te halen?
  - Waar zit het grootste afhankelijksheidsrisico (bijvoorbeeld 1-2 deals of 1-2 AE's)?
- Maak daarnaast een KORTE, APARTE opsomming:
  - Gebruik expliciet de JSON-sectie `deals_closing_next_14_days` als die aanwezig is.
  - Voeg maximaal 10 deals toe in een lijst onder het kopje: "Deals met geplande close binnen 14 dagen".
  - Per deal: noem accountnaam, opportunitynaam, bedrag, stage, forecast category en geplande close date.
  - Voeg waar mogelijk de next step health score per deal toe (indien in de JSON aanwezig).
  - Als de JSON geen individuele deals met close date binnen 14 dagen bevat, zeg dat expliciet en maak géén eigen lijst op basis van aannames.

3) TARGETVEILIGHEID - BEWEEG IK VEILIG RICHTING MIJN KWARTAALDOEL
- Kijk naar target, bookings-to-date, gap, coverage en de kwaliteit van de pipeline.
  - Loop ik op schema, op dun ijs, of structureel achter?
  - Is de huidige pipeline kwalitatief sterk genoeg om de gap realistisch te dichten?
  - Met hoeveel weken vertraging of versnelling moet ik rekening houden, op basis van de data?

4) MANAGEMENTFOCUS - WAAR MOET IK DEZE WEEK OP INGRIJPEN
- Geef maximaal 5 concrete managementinterventies, gericht op:
  - specifieke AE's
  - specifieke deals
  - specifiek gedragsprobleem
  - specifiek targetrisico
- Formuleer als directe acties voor mij als RVP, bijvoorbeeld:
  - "Grijp in bij …"
  - "Verifieer realiteit bij …"
  - "Forceer besluitvorming op …"

5) ONCOMFORTABELE REALITEIT - WAT WIL IK WAARSCHIJNLIJK NIET HOREN
- Sluit af met 3 ongemakkelijke waarheden die ik als RVP liever zou negeren,
  maar die wél logisch volgen uit de data.
- Geen nuance, geen verzachting, geen diplomatie. Alleen wat schuurt.

BEGIN NU MET DE MANAGEMENT SCAN.
"""
    return prompt


def run_llm(prompt: str, cfg: dict, model_override: Optional[str] = None) -> str:
    """Roep de LLM aan via de centrale LLM client (Ollama default, LiteLLM optioneel)."""

    if not OUTPUTS_DIR or not PAYLOAD_DEBUG_FILE:
        raise RuntimeError("[weekly-scan] OUTPUTS_DIR/PAYLOAD_DEBUG_FILE zijn niet gezet. Draai via main().")

    os.makedirs(OUTPUTS_DIR, exist_ok=True)

    # Debug: promptlengte en payload wegschrijven (weekly specifieke debug file)
    model_in_use = model_override or cfg.get("llm", {}).get("model")
    if not model_in_use:
        model_in_use = "(onbekend)"
    print(f"[weekly-scan] Model (in use): {model_in_use}")
    print(f"[weekly-scan] Promptlengte (tekens): {len(prompt)}")

    try:
        with open(PAYLOAD_DEBUG_FILE, "w", encoding="utf-8") as f:
            f.write(prompt)
        print(f"[weekly-scan] Volledige LLM-payload weggeschreven naar: {PAYLOAD_DEBUG_FILE}")
    except Exception as e:
        print(f"[weekly-scan][FOUT] Kon LLM-payload niet wegschrijven: {e}")

    # Override model voor deze run (zonder config.json blijvend te wijzigen)
    if model_override:
        cfg = dict(cfg)
        cfg_llm = dict(cfg.get("llm", {}))
        cfg_llm["model"] = model_override
        cfg["llm"] = cfg_llm

    # Centrale call (schrijft óók payload naar cfg['llm']['payload_debug_file'])
    result_text = run_llm_core(prompt, cfg=cfg, label="weekly_management_scan")

    print("[weekly-scan] LLM call succesvol afgerond.")
    return result_text


def save_scan_output(text: str) -> None:
    """Sla de managementscan op als 'latest' en met timestamp."""
    if not OUTPUTS_DIR or not SCAN_LATEST_FILE:
        raise RuntimeError("[weekly-scan] OUTPUTS_DIR/SCAN_LATEST_FILE zijn niet gezet. Draai via main().")

    os.makedirs(OUTPUTS_DIR, exist_ok=True)

    # Latest
    with open(SCAN_LATEST_FILE, "w", encoding="utf-8") as f:
        f.write(text)

    # Timestamped
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    ts_file = os.path.join(OUTPUTS_DIR, f"weekly_management_scan_{ts}.txt")
    with open(ts_file, "w", encoding="utf-8") as f:
        f.write(text)

    print("[weekly-scan] Managementscan opgeslagen naar:")
    print(f" - {SCAN_LATEST_FILE}")
    print(f" - {ts_file}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Draai de wekelijkse RVP-managementscan op basis van weekly_llm_input_latest.json"
    )
    parser.add_argument(
        "-c",
        "--context-file",
        help="Pad naar een tekstbestand met extra context van de RVP (optioneel).",
        default=None,
    )
    parser.add_argument(
        "-m",
        "--model",
        help="Naam van het model voor de managementscan (laat leeg om config.json te gebruiken).",
        default=None,
    )
    return parser.parse_args()


def main():
    args = parse_args()

    cfg = _load_cfg()
    llm_cfg = get_llm_config(cfg)
    global OUTPUTS_DIR, LLM_INPUT_FILE, PAYLOAD_DEBUG_FILE, SCAN_LATEST_FILE
    OUTPUTS_DIR = _get_outputs_dir(cfg)
    LLM_INPUT_FILE = os.path.join(OUTPUTS_DIR, "weekly_llm_input_latest.json")
    PAYLOAD_DEBUG_FILE = os.path.join(OUTPUTS_DIR, "weekly_llm_payload_latest.txt")
    SCAN_LATEST_FILE = os.path.join(OUTPUTS_DIR, "weekly_management_scan_latest.txt")

    print("[weekly-scan] Start wekelijkse managementscan...")
    print(f"[weekly-scan] LLM-inputbestand: {LLM_INPUT_FILE}")
    print(f"[weekly-scan] Backend: {llm_cfg.backend}")
    print(f"[weekly-scan] Model (config): {llm_cfg.model}")
    print(f"[weekly-scan] Model override (cli): {args.model or '(geen)'}")

    data = load_llm_input()
    extra_context = load_extra_context(args.context_file)

    json_text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    prompt = build_prompt(json_text, extra_context)

    model_override = args.model or None
    scan_text = run_llm(prompt, cfg=cfg, model_override=model_override)
    save_scan_output(scan_text)

    print("[weekly-scan] Klaar.")


if __name__ == "__main__":
    main()