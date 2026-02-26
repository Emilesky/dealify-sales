import json
import os
import math
from datetime import datetime
from typing import Any, Dict

import pandas as pd


def sanitize_for_json(obj: Any) -> Any:
    """Recursively sanitize objects for strict JSON.

    Python's json module can write NaN/Infinity, which breaks strict JSON parsers (e.g., JSON.parse in JS).
    Convert NaN/Infinity to None so the output is valid JSON.
    """
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj

    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}

    if isinstance(obj, list):
        return [sanitize_for_json(v) for v in obj]

    if isinstance(obj, tuple):
        return [sanitize_for_json(v) for v in obj]

    return obj


def get_latest_csv(data_dir: str, name_contains: str = "pipeline") -> str:
    if not data_dir:
        raise RuntimeError("[pipeline] data_dir is leeg. Verwacht een geldige data directory.")

    print(f"[pipeline] Zoek nieuwste CSV in: {data_dir} met patroon: '{name_contains}'")

    candidates = []
    for fn in os.listdir(data_dir):
        if not fn.lower().endswith(".csv"):
            continue
        if name_contains.lower() not in fn.lower():
            continue
        candidates.append(fn)

    if not candidates:
        raise FileNotFoundError(f"Geen CSV gevonden in {data_dir} met patroon '{name_contains}'.")

    candidates.sort(key=lambda f: os.path.getmtime(os.path.join(data_dir, f)), reverse=True)
    latest = candidates[0]
    latest_path = os.path.join(data_dir, latest)
    print(f"[pipeline] Nieuwste pipeline CSV gevonden: {latest}")
    return latest_path


def load_csv(csv_path: str) -> pd.DataFrame:
    print(f"[pipeline] CSV laden: {csv_path}")
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    print(f"[pipeline] CSV geladen met {len(df)} regels en {len(df.columns)} kolommen")
    return df


def ensure_output_dir(output_dir: str) -> None:
    if not output_dir:
        raise RuntimeError("[pipeline] output_dir is leeg. Verwacht een geldige output directory.")
    print(f"[pipeline] Zorg dat output directory bestaat: {output_dir}")
    os.makedirs(output_dir, exist_ok=True)


def _write_text_latest_and_timestamped(text: str, output_dir: str, latest_filename: str, prefix: str) -> None:
    ensure_output_dir(output_dir)
    latest_path = os.path.join(output_dir, latest_filename)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_path = os.path.join(output_dir, f"{prefix}_{ts}.txt")

    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(text)
    with open(ts_path, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"[pipeline] Output geschreven: {latest_path}")
    print(f"[pipeline] Output geschreven: {ts_path}")


def _write_json_latest_and_timestamped(data: Dict[str, Any], output_dir: str, latest_filename: str, prefix: str) -> None:
    ensure_output_dir(output_dir)
    latest_path = os.path.join(output_dir, latest_filename)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_path = os.path.join(output_dir, f"{prefix}_{ts}.json")
    safe_data = sanitize_for_json(data)

    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(safe_data, f, indent=2, ensure_ascii=False, allow_nan=False)
    with open(ts_path, "w", encoding="utf-8") as f:
        json.dump(safe_data, f, indent=2, ensure_ascii=False, allow_nan=False)

    print(f"[pipeline] Output geschreven: {latest_path}")
    print(f"[pipeline] Output geschreven: {ts_path}")


def write_reports(text: str, output_dir: str) -> None:
    if not output_dir:
        raise RuntimeError("[pipeline] output_dir is leeg. Verwacht een geldige output directory.")

    _write_text_latest_and_timestamped(
        text=text,
        output_dir=output_dir,
        latest_filename="ae_pipeline_summary_latest.txt",
        prefix="ae_pipeline_summary",
    )


def write_management_data(data: Dict[str, Any], output_dir: str) -> None:
    if not output_dir:
        raise RuntimeError("[pipeline] output_dir is leeg. Verwacht een geldige output directory.")

    _write_json_latest_and_timestamped(
        data=data,
        output_dir=output_dir,
        latest_filename="pipeline_management_data_latest.json",
        prefix="pipeline_management_data",
    )


def write_management_summary(text: str, output_dir: str) -> None:
    if not output_dir:
        raise RuntimeError("[pipeline] output_dir is leeg. Verwacht een geldige output directory.")

    _write_text_latest_and_timestamped(
        text=text,
        output_dir=output_dir,
        latest_filename="management_summary_latest.txt",
        prefix="management_summary",
    )