import json
import subprocess
from typing import Dict, List, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from python.app.config import LLMConfig

"""
Helpers voor LLM-based Next Step health-evaluatie.

Standaard draaien we nu op een lichtere Ollama-variant om performance te verbeteren.
Als je een ander model wilt gebruiken, pas dan DEFAULT_MODEL hieronder aan.

Tip: run eerst in je terminal:
    ollama pull llama3:8b
of een andere variant die je hier invult.
"""

# Default key name for Next Steps in deal dicts.
# In the pipeline we canonicalize to `next_steps`, but some raw exports still use `Next Steps`.
NEXT_STEP_FIELD = "next_steps"

# Default prompt template path.
# NOTE: this file now lives under `python/infrastructure/llm/`, so we need one extra `..`
# to reach the repo root.
PROJECT_ROOT = Path(__file__).resolve().parents[3]  # .../DealifyEngine
DEFAULT_PROMPT_PATH = str(PROJECT_ROOT / "models" / "prompt_next_step_health.txt")


def load_prompt_template(path: str = DEFAULT_PROMPT_PATH) -> str:
    """Laad de prompt-template vanaf disk."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def build_prompt(next_step: Any, template: Optional[str] = None) -> str:
    """Vervang de placeholder in de template door de echte Next Step tekst."""
    if template is None:
        template = load_prompt_template()

    # Zorg dat we geen .strip() op een float/NaN/etc. doen
    if next_step is None:
        raw_text = ""
    else:
        try:
            raw_text = str(next_step)
        except Exception:
            raw_text = ""

    safe_text = raw_text.strip() or "(empty)"
    return template.replace("[NEXT_STEP]", safe_text)


def call_ollama(prompt: str, llm_config: LLMConfig) -> str:
    """Roep Ollama aan via subprocess en geef de raw text-output terug.

    Extra guards:
    - Controleer of `ollama` op PATH staat (veelvoorkomende fout na venv/VSCode)
    - Log welk `ollama` binary-pad gebruikt wordt
    - Geef een heldere foutmelding als de executable ontbreekt
    """
    if llm_config.backend != "ollama":
        raise ValueError(f"Unsupported LLM backend: {llm_config.backend}")

    ollama_path = llm_config.ollama_path
    if not ollama_path:
        raise ValueError("llm.ollama_path ontbreekt in config.json terwijl backend=ollama")

    model = llm_config.model
    timeout_sec = llm_config.timeout_sec

    print(f"[llm][ollama] binary={ollama_path} model={model} timeout={timeout_sec}s")

    cmd = [ollama_path, "run", model]
    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout_sec,
        )
    except FileNotFoundError as e:
        raise FileNotFoundError(
            "Failed to execute Ollama. The `ollama` binary was not found or could not be executed. "
            "Check: `which ollama`, `ollama --version`, en je PATH in deze shell/venv."
        ) from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"Ollama call timed out after {timeout_sec}s (model={model})."
        ) from e

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    if result.returncode != 0:
        raise RuntimeError(f"Ollama call failed (code {result.returncode}): {stderr or 'unknown error'}")

    return stdout


def parse_json_response(raw_text: str) -> Dict[str, Any]:
    """Parse de JSON-response van het model; vang rommel eromheen af."""
    raw_text = (raw_text or "").strip()

    # simpele poging: direct JSON
    try:
        return json.loads(raw_text)
    except Exception:
        pass

    # fallback: probeer het eerste {...} blok eruit te halen
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = raw_text[start : end + 1]
        try:
            return json.loads(snippet)
        except Exception:
            pass

    # als alles faalt, geef een veilige fallback terug
    return {
        "score": None,
        "reason": "Failed to parse JSON from model output.",
        "improved": None,
        "raw": raw_text,
    }


def parse_json_array_response(raw_text: str) -> List[Dict[str, Any]]:
    """Parse een JSON-array response van het model; vang rommel eromheen af.

    Verwacht een lijst van objecten. Geeft altijd een lijst terug (kan leeg zijn).
    """
    raw_text = (raw_text or "").strip()

    # Eerste poging: direct JSON
    try:
        data = json.loads(raw_text)
        if isinstance(data, list):
            return data
    except Exception:
        pass

    # Fallback: probeer het eerste [...] blok eruit te halen
    start = raw_text.find("[")
    end = raw_text.rfind("]")
    if start != -1 and end != -1 and end > start:
        snippet = raw_text[start : end + 1]
        try:
            data = json.loads(snippet)
            if isinstance(data, list):
                return data
        except Exception:
            pass

    # Als alles faalt, geef een lege lijst
    return []


def evaluate_next_step(
    next_step: Any,
    llm_config: LLMConfig,
    template: Optional[str] = None,
) -> Dict[str, Any]:
    """Hoofdfunctie: Next Step string -> LLM-evaluatie dict met fallback."""
    prompt = build_prompt(next_step, template=template)
    try:
        raw = call_ollama(prompt, llm_config=llm_config)
    except Exception as e:
        return {
            "score": None,
            "reason": f"LLM unavailable: {str(e)}",
            "improved": None,
            "original": next_step,
        }

    parsed = parse_json_response(raw)
    parsed.setdefault("original", next_step)
    return parsed


def evaluate_next_steps_batch(
    deals: List[Dict[str, Any]],
    next_step_field: str = NEXT_STEP_FIELD,
    llm_config: Optional[LLMConfig] = None,
    template: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Batch-evaluatie: voegt per deal een 'next_step_health' dict toe met batching + parallelisatie.

    In plaats van per deal een aparte LLM-call te doen, sturen we batches van meerdere Next Steps
    tegelijk naar het model. Elke batch wordt parallel verwerkt met een beperkt aantal workers.
    """
    if llm_config is None:
        raise ValueError("llm_config is verplicht (pipeline moet config injecteren)")

    if template is None:
        template = load_prompt_template()

    total = len(deals)
    print(f"[llm] Start Next Step batch-evaluatie voor {total} deals (backend={llm_config.backend}, model={llm_config.model})")

    if total == 0:
        print("[llm] Geen deals om te evalueren.")
        return []

    # Resultatenlijst met vaste lengte zodat de originele volgorde behouden blijft
    enriched: List[Optional[Dict[str, Any]]] = [None] * total

    # Bepaal batchgrootte en aantal workers (lichtgewicht, maar parallel)
    BATCH_SIZE = 6
    batches: List[List[int]] = [
        list(range(i, min(i + BATCH_SIZE, total)))
        for i in range(0, total, BATCH_SIZE)
    ]
    num_batches = len(batches)
    max_workers = min(3, num_batches)

    print(f"[llm] Batch-configuratie: {num_batches} batches, batchgrootte={BATCH_SIZE}, workers={max_workers}")

    def _build_batch_prompt(indices: List[int]) -> str:
        """Bouw een prompt voor een batch Next Steps."""
        items = []
        for idx in indices:
            deal = deals[idx]
            text = (
                deal.get(next_step_field)
                or deal.get("next_steps")
                or deal.get("Next Steps")
                or deal.get("Next Step")
                or ""
            )
            try:
                text_str = str(text)
            except Exception:
                text_str = ""
            items.append({"id": idx, "next_step": text_str})

        instructions = (
            "You are a strict but constructive sales coach. You will receive a list of 'Next Step' texts "
            "for sales opportunities. For each input, you must evaluate the quality of the Next Step and "
            "respond ONLY with a JSON array.\n\n"
            "Your job is to CRITICIZE the Next Step, not to rewrite it.\n\n"
            "Each element in the JSON array MUST have:\n"
            "  - \"id\": the numeric id we provide for the input\n"
            "  - \"score\": a number from 0 to 10 (higher = more concrete, specific, and actionable)\n"
            "  - \"reason\": a short explanation in English of what is good or missing in this Next Step\n"
            "  - \"improved\": ALWAYS an empty string \"\" (this field is kept only for compatibility; do NOT rewrite or propose new text)\n\n"
            "Rules:\n"
            "  - Do NOT add any extra keys.\n"
            "  - Do NOT include any text before or after the JSON.\n"
            "  - Do NOT rewrite or suggest a new Next Step. Only critique.\n"
            "  - The JSON MUST be a valid JSON array.\n\n"
            "Here are the inputs:\n"
        )

        lines = [instructions]
        for item in items:
            lines.append(f"- id: {item['id']}, next_step: \"{item['next_step']}\"")

        lines.append("\nNow respond with the JSON array only.")
        return "\n".join(lines)

    def _process_batch(indices: List[int]) -> List[tuple[int, Dict[str, Any]]]:
        """Verwerk één batch indices -> lijst van (idx, verrijkte_deal)."""
        prompt = _build_batch_prompt(indices)
        try:
            raw = call_ollama(prompt, llm_config=llm_config)
            parsed_list = parse_json_array_response(raw)
        except Exception as e:
            # Fallback: geen model-antwoord, markeer alle deals in deze batch met LLM unavailable
            error_msg = f"LLM unavailable in batch: {str(e)}"
            result: List[tuple[int, Dict[str, Any]]] = []
            for idx in indices:
                deal = deals[idx]
                d = dict(deal)
                d["next_step_health"] = {
                    "score": None,
                    "reason": error_msg,
                    "improved": None,
                    "original": deal.get(next_step_field, ""),
                }
                result.append((idx, d))
            return result

        # Map id -> parsed object
        parsed_by_id: Dict[int, Dict[str, Any]] = {}
        for obj in parsed_list:
            if not isinstance(obj, dict):
                continue
            if "id" not in obj:
                continue
            try:
                obj_id = int(obj["id"])
            except Exception:
                continue
            parsed_by_id[obj_id] = obj

        result: List[tuple[int, Dict[str, Any]]] = []
        for idx in indices:
            deal = deals[idx]
            d = dict(deal)
            raw_text = deal.get(next_step_field, "")

            if idx in parsed_by_id:
                health = dict(parsed_by_id[idx])
                # Zorg dat verplichte velden aanwezig zijn
                health.setdefault("score", None)
                health.setdefault("reason", "")
                health.setdefault("improved", "")
                health.setdefault("original", raw_text)
            else:
                # Fallback als deze id niet in de JSON terugkomt
                health = {
                    "score": None,
                    "reason": "No evaluation returned for this item in batch JSON.",
                    "improved": "",
                    "original": raw_text,
                }

            d["next_step_health"] = health
            result.append((idx, d))

        return result

    processed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_batch_idx = {
            executor.submit(_process_batch, b): b
            for b in batches
        }

        for future in as_completed(future_to_batch_idx):
            batch_result = future.result()
            for idx, d in batch_result:
                enriched[idx] = d
                processed += 1
            print(f"[llm] Evaluatie voortgang: {processed}/{total} deals verwerkt")

    # Filter eventuele None eruit (zou niet mogen gebeuren, maar voor de zekerheid)
    final_enriched: List[Dict[str, Any]] = [d for d in enriched if d is not None]
    print("[llm] Next Step batch-evaluatie voltooid")
    return final_enriched