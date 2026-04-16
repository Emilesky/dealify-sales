from __future__ import annotations

import csv
import json
import os
from typing import Any, Dict, List

import streamlit as st

from python.app.config import load_config, load_weekly_attention_config

ALLOWED_ACTIVE_VIEWS = ("weekly", "quarterly")


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _to_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _load_ae_rows() -> List[Dict[str, Any]]:
    cfg = load_config()
    weekly_cfg = load_weekly_attention_config(cfg)
    rows: List[Dict[str, Any]] = []

    for ae_name, ae in sorted(weekly_cfg.ae_inputs.items()):
        rows.append(
            {
                "ae_name": ae_name,
                "target": ae.target,
                "verbal": ae.verbal,
                "low": ae.low,
                "high": ae.high,
                "coverage_factor": ae.coverage_factor,
                "active_view": ae.active_view or weekly_cfg.settings.fallback_active_view or "weekly",
            }
        )

    if not rows:
        rows.append(
            {
                "ae_name": "",
                "target": None,
                "verbal": None,
                "low": None,
                "high": None,
                "coverage_factor": None,
                "active_view": "weekly",
            }
        )

    return rows


def _build_settings_payload(values: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "supported_view_default": str(values["supported_view_default"]).strip(),
        "fallback_coverage_factor": _to_float_or_none(values["fallback_coverage_factor"]),
        "fallback_active_view": str(values["fallback_active_view"]).strip(),
        "next_step_health": {
            "good_min": _to_float_or_none(values["good_min"]),
            "watch_min": _to_float_or_none(values["watch_min"]),
            "poor_max": _to_float_or_none(values["poor_max"]),
        },
        "action_thresholds": {
            "monitor_min": _to_float_or_none(values["monitor_min"]),
            "ae_attention_min": _to_float_or_none(values["ae_attention_min"]),
            "manager_attention_min": _to_float_or_none(values["manager_attention_min"]),
            "urgent_manager_attention_min": _to_float_or_none(values["urgent_manager_attention_min"]),
        },
        "forecast_priority_weights": {
            "commit": _to_float_or_none(values["weight_commit"]),
            "green_upside": _to_float_or_none(values["weight_green_upside"]),
            "upside": _to_float_or_none(values["weight_upside"]),
            "other": _to_float_or_none(values["weight_other"]),
        },
        "amount_weights": {
            "small_max": _to_float_or_none(values["small_max"]),
            "medium_max": _to_float_or_none(values["medium_max"]),
            "small_weight": _to_float_or_none(values["small_weight"]),
            "medium_weight": _to_float_or_none(values["medium_weight"]),
            "large_weight": _to_float_or_none(values["large_weight"]),
        },
    }


def _save_ae_csv(path: str, rows: List[Dict[str, Any]]) -> int:
    _ensure_parent_dir(path)
    cleaned_rows: List[Dict[str, Any]] = []
    for row in rows:
        ae_name = str(row.get("ae_name", "")).strip()
        if not ae_name:
            continue
        active_view = str(row.get("active_view", "")).strip() or None
        cleaned_rows.append(
            {
                "ae_name": ae_name,
                "target": _to_float_or_none(row.get("target")),
                "verbal": _to_float_or_none(row.get("verbal")),
                "low": _to_float_or_none(row.get("low")),
                "high": _to_float_or_none(row.get("high")),
                "coverage_factor": _to_float_or_none(row.get("coverage_factor")),
                "active_view": active_view,
            }
        )

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["ae_name", "target", "verbal", "low", "high", "coverage_factor", "active_view"],
        )
        writer.writeheader()
        for row in cleaned_rows:
            writer.writerow(row)

    return len(cleaned_rows)


def _save_settings_json(path: str, payload: Dict[str, Any]) -> None:
    _ensure_parent_dir(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main() -> None:
    cfg = load_config()
    weekly_cfg = load_weekly_attention_config(cfg)
    ae_inputs_path = cfg["paths"]["weekly_attention_ae_inputs_abs"]
    settings_path = cfg["paths"]["weekly_attention_settings_abs"]

    st.set_page_config(page_title="Weekly AE Attention Config", layout="wide")
    st.title("Weekly AE Attention Config")
    st.caption("Outer adapter only. This UI writes config files and does not run business logic.")

    st.subheader("Resolved file paths")
    st.code(f"AE inputs CSV: {ae_inputs_path}\nGlobal settings JSON: {settings_path}")

    st.subheader("AE inputs")
    ae_rows = st.data_editor(
        _load_ae_rows(),
        num_rows="dynamic",
        use_container_width=True,
        key="weekly_attention_ae_inputs_editor",
        column_config={
            "ae_name": st.column_config.TextColumn("ae_name", required=True),
            "target": st.column_config.NumberColumn("target", format="%.2f"),
            "verbal": st.column_config.NumberColumn("verbal", format="%.2f"),
            "low": st.column_config.NumberColumn("low", format="%.2f"),
            "high": st.column_config.NumberColumn("high", format="%.2f"),
            "coverage_factor": st.column_config.NumberColumn("coverage_factor", format="%.2f"),
            "active_view": st.column_config.SelectboxColumn("active_view", options=list(ALLOWED_ACTIVE_VIEWS)),
        },
    )

    st.subheader("Global settings")
    left, right = st.columns(2)

    with left:
        supported_view_default = st.selectbox(
            "supported_view_default",
            options=list(ALLOWED_ACTIVE_VIEWS),
            index=list(ALLOWED_ACTIVE_VIEWS).index(weekly_cfg.settings.supported_view_default or "weekly"),
        )
        fallback_active_view = st.selectbox(
            "fallback_active_view",
            options=list(ALLOWED_ACTIVE_VIEWS),
            index=list(ALLOWED_ACTIVE_VIEWS).index(weekly_cfg.settings.fallback_active_view or "weekly"),
        )
        fallback_coverage_factor = st.number_input(
            "fallback_coverage_factor",
            value=float(weekly_cfg.settings.fallback_coverage_factor or 1.0),
            step=0.1,
        )

        st.markdown("**Next step health thresholds**")
        good_min = st.number_input("good_min", value=float(weekly_cfg.settings.next_step_health.good_min or 7.0), step=0.1)
        watch_min = st.number_input("watch_min", value=float(weekly_cfg.settings.next_step_health.watch_min or 5.0), step=0.1)
        poor_max = st.number_input("poor_max", value=float(weekly_cfg.settings.next_step_health.poor_max or 5.0), step=0.1)

        st.markdown("**Action thresholds**")
        monitor_min = st.number_input("monitor_min", value=float(weekly_cfg.settings.action_thresholds.monitor_min or 1.0), step=0.1)
        ae_attention_min = st.number_input("ae_attention_min", value=float(weekly_cfg.settings.action_thresholds.ae_attention_min or 2.0), step=0.1)
        manager_attention_min = st.number_input("manager_attention_min", value=float(weekly_cfg.settings.action_thresholds.manager_attention_min or 3.0), step=0.1)
        urgent_manager_attention_min = st.number_input(
            "urgent_manager_attention_min",
            value=float(weekly_cfg.settings.action_thresholds.urgent_manager_attention_min or 4.0),
            step=0.1,
        )

    with right:
        st.markdown("**Forecast priority weights**")
        weight_commit = st.number_input("commit", value=float(weekly_cfg.settings.forecast_priority_weights.commit or 1.0), step=0.1)
        weight_green_upside = st.number_input("green_upside", value=float(weekly_cfg.settings.forecast_priority_weights.green_upside or 0.8), step=0.1)
        weight_upside = st.number_input("upside", value=float(weekly_cfg.settings.forecast_priority_weights.upside or 0.6), step=0.1)
        weight_other = st.number_input("other", value=float(weekly_cfg.settings.forecast_priority_weights.other or 0.3), step=0.1)

        st.markdown("**Amount weight settings**")
        small_max = st.number_input("small_max", value=float(weekly_cfg.settings.amount_weights.small_max or 25000.0), step=1000.0)
        medium_max = st.number_input("medium_max", value=float(weekly_cfg.settings.amount_weights.medium_max or 100000.0), step=1000.0)
        small_weight = st.number_input("small_weight", value=float(weekly_cfg.settings.amount_weights.small_weight or 0.5), step=0.1)
        medium_weight = st.number_input("medium_weight", value=float(weekly_cfg.settings.amount_weights.medium_weight or 1.0), step=0.1)
        large_weight = st.number_input("large_weight", value=float(weekly_cfg.settings.amount_weights.large_weight or 1.5), step=0.1)

    if st.button("Save Weekly AE Attention Config", type="primary"):
        names = [str(row.get("ae_name", "")).strip() for row in ae_rows if str(row.get("ae_name", "")).strip()]
        if len(names) != len(set(names)):
            st.error("Duplicate ae_name values are not allowed.")
            return

        invalid_views = [
            str(row.get("active_view", "")).strip()
            for row in ae_rows
            if str(row.get("ae_name", "")).strip()
            and str(row.get("active_view", "")).strip()
            and str(row.get("active_view", "")).strip() not in ALLOWED_ACTIVE_VIEWS
        ]
        if invalid_views:
            st.error("Each active_view must be either 'weekly' or 'quarterly'.")
            return

        settings_payload = _build_settings_payload(
            {
                "supported_view_default": supported_view_default,
                "fallback_coverage_factor": fallback_coverage_factor,
                "fallback_active_view": fallback_active_view,
                "good_min": good_min,
                "watch_min": watch_min,
                "poor_max": poor_max,
                "monitor_min": monitor_min,
                "ae_attention_min": ae_attention_min,
                "manager_attention_min": manager_attention_min,
                "urgent_manager_attention_min": urgent_manager_attention_min,
                "weight_commit": weight_commit,
                "weight_green_upside": weight_green_upside,
                "weight_upside": weight_upside,
                "weight_other": weight_other,
                "small_max": small_max,
                "medium_max": medium_max,
                "small_weight": small_weight,
                "medium_weight": medium_weight,
                "large_weight": large_weight,
            }
        )

        saved_rows = _save_ae_csv(ae_inputs_path, ae_rows)
        _save_settings_json(settings_path, settings_payload)
        st.success(f"Saved {saved_rows} AE rows and global settings.")


if __name__ == "__main__":
    main()
