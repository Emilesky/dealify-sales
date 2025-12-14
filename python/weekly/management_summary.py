import subprocess
import json
import os
from typing import Optional

from python.app.config import load_config, get_llm_config

MAX_DEBUG_CHARS = 2000

def _load_cfg():
    """Load config.json once per run (helper for scripts)."""
    return load_config()


def _get_outputs_dir(cfg: dict) -> str:
    """Resolve outputs dir via config.json."""
    paths = cfg.get("paths", {})
    outputs_dir = paths.get("outputs_dir_abs") or paths.get("outputs_dir")
    if not outputs_dir:
        raise KeyError("'paths.outputs_dir_abs' ontbreekt in config.json")
    return outputs_dir


def load_management_data(outputs_dir: str) -> dict | None:
    """
    Laad de gestructureerde managementdata uit JSON, als deze beschikbaar is.
    Verwacht: outputs/pipeline_management_data_latest.json
    """
    json_path = os.path.join(outputs_dir, "pipeline_management_data_latest.json")
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        print(f"[mgmt] Waarschuwing: management data JSON niet gevonden op pad: {json_path}")
    except json.JSONDecodeError as e:
        print(f"[mgmt] Fout bij het parsen van management data JSON: {e}")
    return None


def generate_management_summary(report_text: str, model: Optional[str] = None) -> str:
    """
    Genereer een managementsummary op basis van:
    - het tekstuele AE-pipelinerapport (report_text)
    - de gestructureerde managementdata uit JSON (targets, gaps, buckets, AE-scorecards)
    """
    cfg = _load_cfg()
    llm_cfg = get_llm_config(cfg)
    outputs_dir = _get_outputs_dir(cfg)

    # Model: expliciete parameter wint, anders config.json
    if not model:
        model = llm_cfg.model

    # Ollama binary: verplicht bij backend=ollama
    if llm_cfg.backend != "ollama":
        raise ValueError(f"Unsupported LLM backend for management_summary: {llm_cfg.backend}")
    if not llm_cfg.ollama_path:
        raise ValueError("llm.ollama_path ontbreekt in config.json terwijl backend=ollama")

    timeout_sec = llm_cfg.timeout_sec

    print(f"[mgmt] Start genereren management summary met model: {model}")

    management_data = load_management_data(outputs_dir)
    if management_data is not None:
        try:
            management_data_text = json.dumps(management_data, ensure_ascii=False, indent=2)
            top_level_keys = list(management_data.keys())
            print(f"[mgmt] Management JSON geladen. Top-level keys: {top_level_keys}")
        except Exception as e:
            print(f"[mgmt][FOUT] Kon management JSON niet serialiseren: {e}")
            management_data_text = "Niet beschikbaar (fout bij serialiseren van managementdata)."
    else:
        print("[mgmt][WAARSCHUWING] Geen management JSON beschikbaar, gebruik fallback-tekst in prompt.")
        management_data_text = "Niet beschikbaar (JSON met managementdata niet gevonden of onleesbaar)."

    prompt = f"""
JE MAG ALLEEN CONCLUSIES TREKKEN OP BASIS VAN DE JSON MANAGEMENTDATA.
ALS EEN CONCLUSIE NIET DIRECT UIT DE JSON MET CIJFERS KAN WORDEN ONDERBOUWD, DAN MAG JE DIE CONCLUSIE NIET MAKEN.

Verboden:
- Algemeen taaladvies over next steps
- Algemene opmerkingen over vaagheid, communicatie of schrijfstijl
- Beschrijvingen zonder cijfers
- Conclusies zonder expliciete verwijzing naar target, bookings, pipeline of AE-scorecards

Je bent een ervaren Regional Vice President Sales bij een IT-opleidingsbedrijf (Microsoft, AWS, Cisco, AI, security, maatwerk).
Dit rapport is een PERSOONLIJK WEEKLIJKS FOCUSOVERZICHT voor jou als RVP.

============================
PRIMAIRE DATA (JSON)
============================

{management_data_text}

============================
SECUNDAIRE CONTEXT (AE RAPPORT)
============================

{report_text}

============================
VERPLICHTE ANALYSEFOCUS
============================
Gebruik expliciet de JSON om ALTIJD:
- target vs bookings-to-date vs resterende pipeline te benoemen met BEDRAGEN
- coverage en/of gap te benoemen indien aanwezig
- concentratierisico op topdeals te kwantificeren
- per AE hygiënescore, overdue-deals, next step issues en discovery-alerts te gebruiken

ALS DEZE CIJFERS NIET WORDEN GENOEMD -> IS HET ANTWOORD ONJUIST.

============================
VERPLICHTE STRUCTUUR (GEEN AFWIJKING)
============================

1) Korte status van het team  
- MAX 2 korte alinea’s  
- MOET bevatten:
  - target
  - bookings-to-date
  - resterende gap
  - algemene betrouwbaarheid van de pipeline

2) Top 5 focuspunten voor deze week  
- Exact 5 genummerde punten  
- Elk punt MOET minimaal 1:
  - AE-naam OF
  - concreet dealbedrag bevatten

3) Kritieke risico’s die jij moet adresseren  
- Alleen risico’s met FINANCIËLE impact  
- Elk risico MOET verwijzen naar cijfers uit de JSON

4) Gesprekken en interventies voor deze week  
- 5–10 concrete gesprekken  
- Elk gesprek MOET bevatten:
  - met wie
  - over welk bedrag of welk risico
  - met welk doel

5) Operationele hygiëne-actiepunten  
- 3–5 acties  
- Gericht op:
  - overdue deals
  - missing next steps
  - discovery-deals die binnen 14 dagen sluiten

6) Per AE: belangrijkste aandachtspunten en sluitkansen  
- Max 3 bullets per AE  
- MOET bevatten:
  - grootste risico
  - grootste kansrijke deal met bedrag
  - grootste hygiëneprobleem

============================
BELANGRIJKE REGELS
============================
- Alles in correct NEDERLANDS
- GEEN aannames
- GEEN verzonnen bedragen
- GEEN algemene verkoopadviezen
- ALLEEN feiten uit de JSON en het AE-rapport
- Indien cijfers ontbreken: letterlijk schrijven "Niet beschikbaar in de JSON"

BEGIN NU MET DE MANAGEMENT SAMENVATTING.
"""

    print(f"[mgmt] Promptlengte (tekens): {len(prompt)}")

    # =========================================
    # DEBUG: Volledige payload naar LLM tonen (afgekapt)
    # =========================================

    print("\n==================== LLM PAYLOAD PREVIEW ====================")
    if len(prompt) > MAX_DEBUG_CHARS:
        print(prompt[:MAX_DEBUG_CHARS])
        print(f"\n...[AFGEKAPT | TOTALE LENGTE = {len(prompt)} tekens]...\n")
    else:
        print(prompt)
    print("================== EINDE LLM PAYLOAD PREVIEW =================\n")

    # =========================================
    # DEBUG: Volledige payload wegschrijven naar bestand
    # =========================================
    debug_path = os.path.join(outputs_dir, "last_llm_payload.txt")
    try:
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(prompt)
        print(f"[mgmt] Volledige LLM payload weggeschreven naar: {debug_path}")
    except Exception as e:
        print(f"[mgmt][FOUT] Kon LLM payload niet wegschrijven: {e}")

    cmd = [llm_cfg.ollama_path, "run", model]
    result = subprocess.run(
        cmd,
        input=prompt,
        text=True,
        capture_output=True,
        timeout=timeout_sec,
    )

    if result.returncode != 0:
        print(f"[mgmt][FOUT] Ollama proces eindigde met code {result.returncode}")
        print(result.stderr)
    else:
        print("[mgmt] Ollama proces succesvol afgerond voor management summary.")

    return result.stdout