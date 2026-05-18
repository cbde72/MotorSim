from __future__ import annotations

import math
from typing import Any, MutableMapping


JsonMap = MutableMapping[str, Any]


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _volume_initial_volume_m3(vol: JsonMap, cycle_type: str) -> float:
    vtype = str(vol.get("type") or "").strip().lower()
    if vtype in {"plenum", "bounce_chamber"}:
        fixed = _as_float(vol.get("fixed_volume_m3"))
        if fixed is not None and fixed > 0.0:
            return fixed
        chamber_volume0 = _as_float(vol.get("chamber_volume0_m3"))
        if chamber_volume0 is not None and chamber_volume0 > 0.0:
            return chamber_volume0
        chamber_diameter_m = _as_float(vol.get("chamber_diameter_m"))
        chamber_length_m = _as_float(vol.get("chamber_length_m"))
        compression_ratio = _as_float(vol.get("compression_ratio"))
        if (
            chamber_diameter_m is not None
            and chamber_length_m is not None
            and chamber_diameter_m > 0.0
            and chamber_length_m > 0.0
        ):
            area_m2 = 0.25 * math.pi * chamber_diameter_m * chamber_diameter_m
            vmax_m3 = area_m2 * chamber_length_m
            if compression_ratio is not None and compression_ratio > 1.0:
                return vmax_m3
            return vmax_m3
        return 0.0

    kin = dict(vol.get("kinematics") or {})
    bore = _as_float(kin.get("bore_m"))
    stroke = _as_float(kin.get("stroke_m"))
    conrod = _as_float(kin.get("conrod_m"))
    compression_ratio = _as_float(kin.get("compression_ratio"))
    phase_deg = _as_float(kin.get("phase_deg"))
    if cycle_type == "2t" and phase_deg is None:
        phase_deg = 0.0
    if (
        bore is None
        or stroke is None
        or conrod is None
        or compression_ratio is None
        or phase_deg is None
        or bore <= 0.0
        or stroke <= 0.0
        or conrod <= 0.0
        or compression_ratio <= 1.0
    ):
        return 0.0
    theta = math.radians(phase_deg % 360.0)
    area = 0.25 * math.pi * bore * bore
    r = 0.5 * stroke
    sin_t = math.sin(theta)
    cos_t = math.cos(theta)
    under = max(conrod * conrod - (r * sin_t) * (r * sin_t), 1.0e-18)
    x = r * (1.0 - cos_t) + conrod - math.sqrt(under)
    swept_volume = area * stroke
    clearance_volume = swept_volume / max(compression_ratio - 1.0, 1.0e-18)
    return clearance_volume + area * x


def _normalize_single_volume_initial_state_inplace(vol: JsonMap, *, gas_constant: float, cycle_type: str) -> None:
    vtype = str(vol.get("type") or "").strip().lower()
    if vtype == "environment":
        return

    initial_mass = _as_float(vol.get("initial_mass_kg"))
    initial_pressure = _as_float(vol.get("initial_pressure_Pa"))
    initial_temperature = _as_float(vol.get("initial_temperature_K"))
    volume_m3 = _volume_initial_volume_m3(vol, cycle_type)
    if initial_mass is not None and initial_mass > 0.0 and gas_constant > 0.0 and volume_m3 > 0.0:
        if (initial_pressure is None or initial_pressure <= 0.0) and initial_temperature is not None and initial_temperature > 0.0:
            vol["initial_pressure_Pa"] = float(initial_mass * gas_constant * initial_temperature / volume_m3)
            initial_pressure = float(vol["initial_pressure_Pa"])
        elif (initial_temperature is None or initial_temperature <= 0.0) and initial_pressure is not None and initial_pressure > 0.0:
            vol["initial_temperature_K"] = float(initial_pressure * volume_m3 / (initial_mass * gas_constant))
            initial_temperature = float(vol["initial_temperature_K"])

    if initial_pressure is not None and initial_pressure > 0.0:
        vol.pop("initial_mass_kg", None)


def _first_cylinder_volume(state: JsonMap) -> JsonMap | None:
    preprocessing = state.get("preprocessing")
    if not isinstance(preprocessing, MutableMapping):
        return None
    volumes = preprocessing.get("volumes")
    if not isinstance(volumes, list):
        return None
    for vol in volumes:
        if isinstance(vol, MutableMapping) and str(vol.get("type") or "").strip().lower() == "cylinder":
            return vol
    return None


def _sync_free_piston_cylinder_inplace(state: JsonMap, *, update_values: bool = True) -> None:
    modeling = state.get("modeling")
    if not isinstance(modeling, MutableMapping):
        return
    if str(modeling.get("architecture") or "").strip().lower() != "free_piston":
        return

    free_piston = state.get("free_piston")
    if not isinstance(free_piston, MutableMapping):
        return
    init = free_piston.get("initial_conditions")
    if not isinstance(init, MutableMapping):
        return

    cylinder_state = init.get("cylinder")
    if cylinder_state is not None and not isinstance(cylinder_state, MutableMapping):
        cylinder_state = None

    cylinder_vol = _first_cylinder_volume(state)
    if cylinder_vol is None and cylinder_state is None:
        return

    if cylinder_vol is None and isinstance(cylinder_state, MutableMapping):
        return

    if cylinder_vol is not None and cylinder_state is None:
        return

    assert cylinder_vol is not None
    assert isinstance(cylinder_state, MutableMapping)

    if not update_values:
        init.pop("cylinder", None)
        return

    fp_pressure = _as_float(cylinder_state.get("pressure_Pa"))
    fp_temperature = _as_float(cylinder_state.get("temperature_K"))
    vol_pressure = _as_float(cylinder_vol.get("initial_pressure_Pa"))
    vol_temperature = _as_float(cylinder_vol.get("initial_temperature_K"))

    if (vol_pressure is None or vol_pressure <= 0.0) and fp_pressure is not None and fp_pressure > 0.0:
        cylinder_vol["initial_pressure_Pa"] = float(fp_pressure)
        vol_pressure = float(fp_pressure)
    if (vol_temperature is None or vol_temperature <= 0.0) and fp_temperature is not None and fp_temperature > 0.0:
        cylinder_vol["initial_temperature_K"] = float(fp_temperature)
        vol_temperature = float(fp_temperature)

    if vol_pressure is not None and vol_pressure > 0.0:
        cylinder_state["pressure_Pa"] = float(vol_pressure)
    if vol_temperature is not None and vol_temperature > 0.0:
        cylinder_state["temperature_K"] = float(vol_temperature)
    init.pop("cylinder", None)


def sync_initial_states_inplace(state: JsonMap) -> None:
    postprocessing = state.get("postprocessing")
    if isinstance(postprocessing, MutableMapping):
        enabled = postprocessing.get("auto_update_initial_conditions")
        if enabled is False:
            _sync_free_piston_cylinder_inplace(state, update_values=False)
            return

    preprocessing = state.setdefault("preprocessing", {})
    if not isinstance(preprocessing, MutableMapping):
        return

    gas = preprocessing.setdefault("gas_properties", {"cp_J_per_kgK": 1005.0, "cv_J_per_kgK": 718.0, "R_J_per_kgK": 287.0, "thermo_model": "constant"})
    engine = preprocessing.setdefault("engine", {"cycle_type": "4t", "speed_rpm": 3000.0})
    cycle_type = str(engine.get("cycle_type") or "4t")
    gas_constant = _as_float((gas or {}).get("R_J_per_kgK")) or 287.0

    for vol in preprocessing.setdefault("volumes", []):
        if isinstance(vol, MutableMapping):
            _normalize_single_volume_initial_state_inplace(vol, gas_constant=gas_constant, cycle_type=cycle_type)

    _sync_free_piston_cylinder_inplace(state)
