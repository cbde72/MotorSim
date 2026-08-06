from __future__ import annotations

import pytest
from pydantic import ValidationError

from thermo0d.config.constants import CombDurationMode, CombStartMode
from thermo0d.config.models import VibeCombustionConfig
from thermo0d.model.free_piston.builder import _resolve_combustion_timing_for_free_piston
from thermo0d.model.free_piston.combustion_latch import expansion_distance_start_state


def _config(**overrides: object) -> VibeCombustionConfig:
    values: dict[str, object] = {
        "model": "vibe",
        "start_mode": "expansion_distance_from_tdc",
        "hign_mm": 5.0,
        "duration_mode": "time",
        "duration_ms": 10.0,
        "a": 6.9,
        "m": 2.0,
        "added_energy_per_cycle_J": 500.0,
    }
    values.update(overrides)
    return VibeCombustionConfig.model_validate(values)


def test_expansion_distance_config_resolves_mm_to_m_and_enum() -> None:
    start, duration, _reference, start_mode, duration_mode = _resolve_combustion_timing_for_free_piston(
        _config(), nominal_stroke_m=0.0911, cycle_deg=360.0
    )

    assert start == pytest.approx(0.005)
    assert duration == pytest.approx(0.010)
    assert start_mode == CombStartMode.EXPANSION_DISTANCE_FROM_TDC
    assert duration_mode == CombDurationMode.TIME


def test_expansion_distance_requires_exactly_one_length_unit() -> None:
    with pytest.raises(ValidationError, match="Use exactly one"):
        _config(hign_m=0.005)


def test_expansion_distance_only_triggers_on_outward_crossing() -> None:
    armed, trigger = expansion_distance_start_state(
        armed=False, distance_from_tdc_m=0.004, threshold_m=0.005, compression_stroke=True
    )
    assert armed
    assert not trigger

    armed, trigger = expansion_distance_start_state(
        armed=armed, distance_from_tdc_m=0.006, threshold_m=0.005, compression_stroke=False
    )
    assert armed
    assert trigger

    _armed, trigger_before_tdc = expansion_distance_start_state(
        armed=True, distance_from_tdc_m=0.006, threshold_m=0.005, compression_stroke=True
    )
    assert not trigger_before_tdc
