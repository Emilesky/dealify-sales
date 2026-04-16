from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass(frozen=True)
class WeeklyAEInput:
    ae_name: str
    target: Optional[float] = None
    verbal: Optional[float] = None
    low: Optional[float] = None
    high: Optional[float] = None
    coverage_factor: Optional[float] = None
    active_view: Optional[str] = None


@dataclass(frozen=True)
class NextStepHealthThresholds:
    good_min: Optional[float] = None
    watch_min: Optional[float] = None
    poor_max: Optional[float] = None


@dataclass(frozen=True)
class ActionThresholds:
    monitor_min: Optional[float] = None
    ae_attention_min: Optional[float] = None
    manager_attention_min: Optional[float] = None
    urgent_manager_attention_min: Optional[float] = None


@dataclass(frozen=True)
class ForecastPriorityWeights:
    commit: Optional[float] = None
    green_upside: Optional[float] = None
    upside: Optional[float] = None
    other: Optional[float] = None


@dataclass(frozen=True)
class AmountWeightSettings:
    small_max: Optional[float] = None
    medium_max: Optional[float] = None
    small_weight: Optional[float] = None
    medium_weight: Optional[float] = None
    large_weight: Optional[float] = None


@dataclass(frozen=True)
class WeeklyAttentionSettings:
    supported_view_default: Optional[str] = None
    fallback_coverage_factor: Optional[float] = None
    fallback_active_view: Optional[str] = None
    next_step_health: NextStepHealthThresholds = field(default_factory=NextStepHealthThresholds)
    action_thresholds: ActionThresholds = field(default_factory=ActionThresholds)
    forecast_priority_weights: ForecastPriorityWeights = field(default_factory=ForecastPriorityWeights)
    amount_weights: AmountWeightSettings = field(default_factory=AmountWeightSettings)


@dataclass(frozen=True)
class WeeklyAttentionConfig:
    ae_inputs: Dict[str, WeeklyAEInput] = field(default_factory=dict)
    settings: WeeklyAttentionSettings = field(default_factory=WeeklyAttentionSettings)
