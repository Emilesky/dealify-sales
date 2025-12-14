import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class LLMConfig:
    backend: str
    model: str
    timeout_sec: int
    retries: int = 0
    ollama_path: Optional[str] = None


def _find_project_root(start_dir: str) -> str:
    """
    Vind project root door vanaf start_dir omhoog te lopen totdat we config.json vinden.
    Werkt op laptop/VM zonder absolute paden.
    """
    cur = os.path.abspath(start_dir)
    while True:
        candidate = os.path.join(cur, "config.json")
        if os.path.exists(candidate):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            raise FileNotFoundError(
                "config.json niet gevonden. Plaats config.json in je project root "
                "(naast data/ en outputs/)."
            )
        cur = parent


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Laad config.json.
    - Als config_path None is: zoek config.json automatisch vanuit deze file locatie.
    """
    if config_path is None:
        project_root = _find_project_root(os.path.dirname(__file__))
        config_path = os.path.join(project_root, "config.json")
    else:
        project_root = os.path.dirname(os.path.abspath(config_path))

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Vul dynamische paden in
    cfg.setdefault("paths", {})
    cfg["paths"]["project_root"] = project_root

    # Resolve data/outputs naar absolute paden
    data_dir = cfg["paths"].get("data_dir", "data")
    outputs_dir = cfg["paths"].get("outputs_dir", "outputs")

    cfg["paths"]["data_dir_abs"] = os.path.join(project_root, data_dir)
    cfg["paths"]["outputs_dir_abs"] = os.path.join(project_root, outputs_dir)

    return cfg


def get_llm_config(cfg: Dict[str, Any]) -> LLMConfig:
    llm = cfg.get("llm")
    if not llm:
        raise KeyError("'llm' section ontbreekt in config.json")

    backend = llm.get("backend")
    model = llm.get("model")
    timeout_sec = llm.get("timeout_sec")

    if not backend or not model or timeout_sec is None:
        raise KeyError("'llm.backend', 'llm.model' en 'llm.timeout_sec' zijn verplicht in config.json")

    return LLMConfig(
        backend=backend,
        model=model,
        timeout_sec=int(timeout_sec),
        retries=int(llm.get("retries", 0)),
        ollama_path=llm.get("ollama_path"),
    )


def get_path(cfg: Dict[str, Any], key: str) -> str:
    """
    Handige helper om paden op te vragen.
    keys:
    - data_dir_abs
    - outputs_dir_abs
    """
    paths = cfg.get("paths", {})
    if key not in paths:
        raise KeyError(f"Pad '{key}' niet gevonden in config paths.")
    return paths[key]