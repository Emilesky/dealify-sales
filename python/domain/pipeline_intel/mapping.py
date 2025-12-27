import json
from pathlib import Path
from typing import Dict, List, Any, Optional

import pandas as pd


class MappingError(RuntimeError):
    pass


def load_mapping(mapping_path: str) -> Dict[str, Any]:
    path = Path(mapping_path).expanduser().resolve()
    if not path.exists():
        raise MappingError(f"Mapping file niet gevonden: {path}")

    with open(path, "r", encoding="utf-8") as f:
        mapping = json.load(f)

    if "columns" not in mapping or not isinstance(mapping["columns"], dict):
        raise MappingError("Mapping mist 'columns' dict")

    mapping.setdefault("required", [])
    return mapping


def _pick_existing_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    existing = set(df.columns)
    for c in candidates:
        if c in existing:
            return c
    return None


def map_dataframe(df_raw: pd.DataFrame, mapping: Dict[str, Any]) -> pd.DataFrame:
    """
    Map raw dataframe columns to canonical columns based on mapping JSON.

    mapping format:
      columns: { canonical_name: [raw_col_1, raw_col_2, ...] }
      required: [canonical_name, ...]
    """
    columns_map: Dict[str, List[str]] = mapping["columns"]
    required: List[str] = mapping.get("required", [])

    rename: Dict[str, str] = {}
    missing_required: List[str] = []

    for canonical, candidates in columns_map.items():
        raw_col = _pick_existing_column(df_raw, candidates)
        if raw_col:
            rename[raw_col] = canonical
        else:
            if canonical in required:
                missing_required.append(canonical)

    if missing_required:
        # Helpful debug info: show what columns we did get
        found = sorted(set(rename.values()))
        raise MappingError(
            "Required canonical kolommen ontbreken na mapping: "
            + ", ".join(missing_required)
            + f"\nGevonden canonical kolommen: {found}"
            + f"\nBeschikbare raw kolommen: {list(df_raw.columns)[:30]} ..."
        )

    df = df_raw.rename(columns=rename).copy()
    return df