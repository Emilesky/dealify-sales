import os
import time
import json
import subprocess
from typing import Any, Dict, Optional

from python.app.config import load_config


def _write_payload(cfg: Dict[str, Any], payload: str) -> str:
    """Schrijf laatste payload weg voor debug. Returnt pad."""
    project_root = cfg["paths"]["project_root"]
    rel_path = cfg.get("llm", {}).get("payload_debug_file", "outputs/llm_payload_latest.txt")
    out_path = os.path.join(project_root, rel_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(payload)
    print(f"[llm] Payload debug geschreven naar: {out_path}")
    return out_path


def _ollama_cli_available() -> bool:
    """Check of Ollama CLI werkt."""
    try:
        r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def _run_ollama(prompt: str, model: str, timeout_sec: int) -> str:
    """Run prompt via Ollama CLI."""
    cmd = ["ollama", "run", model]
    print(f"[llm][ollama] Run model={model} timeout={timeout_sec}s")
    r = subprocess.run(cmd, input=prompt, text=True, capture_output=True, timeout=timeout_sec)

    if r.returncode != 0:
        err = (r.stderr or "").strip()
        raise RuntimeError(f"Ollama call failed (exit={r.returncode}). STDERR: {err[:1200]}")
    return r.stdout


def _run_litellm(prompt: str, cfg: Dict[str, Any], model: str, timeout_sec: int) -> str:
    """
    Run prompt via LiteLLM.
    - We doen 1 user message
    - Output is plain text
    """
    from litellm import completion  # import hier zodat ollama-only users niet breken

    litellm_cfg = cfg.get("llm", {}).get("litellm", {})
    provider = (litellm_cfg.get("provider") or "openai").strip()
    api_key = (litellm_cfg.get("api_key") or "").strip()
    api_base = (litellm_cfg.get("api_base") or "").strip()

    if provider.lower() in ("openai", "azure") and not api_key:
        raise RuntimeError("LiteLLM backend gekozen maar llm.litellm.api_key is leeg in config.json")

    # Model normalisatie: als je "gpt-4o-mini" invult -> "openai/gpt-4o-mini"
    if "/" not in model:
        model = f"{provider}/{model}"

    print(f"[llm][litellm] Run provider={provider} model={model} timeout={timeout_sec}s")

    kwargs = {"timeout": timeout_sec}
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base

    resp = completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    )

    try:
        return resp["choices"][0]["message"]["content"]
    except Exception:
        return json.dumps(resp, ensure_ascii=False)


def run_llm(prompt: str, cfg: Optional[Dict[str, Any]] = None, label: str = "generic") -> str:
    """
    Centrale LLM entrypoint.
    - leest config.json
    - backend: ollama (default) of litellm
    - retries & timeout via config
    """
    if cfg is None:
        cfg = load_config()

    llm_cfg = cfg.get("llm", {})
    backend = (llm_cfg.get("backend") or "ollama").strip().lower()
    model = (llm_cfg.get("model") or "llama3.1:8b").strip()
    timeout_sec = int(llm_cfg.get("timeout_sec", 180))
    retries = int(llm_cfg.get("retries", 1))

    print(f"[llm] label={label} backend={backend} model={model} retries={retries}")
    _write_payload(cfg, prompt)

    if backend == "ollama":
        if not _ollama_cli_available():
            raise RuntimeError("Ollama lijkt niet beschikbaar. Start Ollama en check: `ollama list`.")
    elif backend == "litellm":
        pass
    else:
        raise ValueError(f"Onbekende llm.backend in config.json: {backend}")

    last_err: Optional[Exception] = None

    for attempt in range(1, retries + 1):
        try:
            t0 = time.time()
            if backend == "ollama":
                out = _run_ollama(prompt, model=model, timeout_sec=timeout_sec)
            else:
                out = _run_litellm(prompt, cfg=cfg, model=model, timeout_sec=timeout_sec)

            dt = time.time() - t0
            print(f"[llm] Klaar in {dt:.2f}s (attempt {attempt}/{retries})")
            return out

        except Exception as e:
            last_err = e
            print(f"[llm][WAARSCHUWING] attempt {attempt}/{retries} faalde: {e}")
            if attempt < retries:
                time.sleep(1.0)

    raise RuntimeError(f"LLM call gefaald na {retries} poging(en): {last_err}")