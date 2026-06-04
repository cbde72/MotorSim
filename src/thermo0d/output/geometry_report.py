from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import re

import numpy as np

from thermo0d.config.constants import ConnCol, ConnectionType, FeatureCol, FlowCoeffMode, KinCol, VolumeCol, VolumeType, WallTemperatureZone
from thermo0d.model.free_piston.cycle_metrics import count_ut_ot_ut_cycles, find_last_ut_ot_ut_turning_points


@dataclass(slots=True)
class LastCycleEntry:
    metric_name: str
    value: float | str
    unit: str


def _find_primary_prefix(rows: list[dict[str, float | int]]) -> str | None:
    if not rows:
        return None
    last_row = rows[-1]
    prefixes: list[str] = []
    for key in last_row:
        if key.endswith("_p_Pa"):
            prefixes.append(key[:-len("_p_Pa")])
    if not prefixes:
        return None
    for prefix in prefixes:
        if prefix.startswith("cyl") or "cylinder" in prefix:
            return prefix
    return prefixes[0]


def _finite_float(value: object) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    if not math.isfinite(out):
        return None
    return out


def _row_values(rows: list[dict[str, float | int]], key: str) -> np.ndarray:
    values = [_finite_float(row.get(key)) for row in rows]
    filtered = [value for value in values if value is not None]
    return np.asarray(filtered, dtype=np.float64)


def _window_values(rows: list[dict[str, float | int]], key: str) -> tuple[np.ndarray, np.ndarray]:
    pairs: list[tuple[float, float]] = []
    for row in rows:
        t_val = _finite_float(row.get("t_s"))
        y_val = _finite_float(row.get(key))
        if t_val is None or y_val is None:
            continue
        pairs.append((t_val, y_val))
    if not pairs:
        return np.zeros(0, dtype=np.float64), np.zeros(0, dtype=np.float64)
    return np.asarray([p[0] for p in pairs], dtype=np.float64), np.asarray([p[1] for p in pairs], dtype=np.float64)


def _integrate_window(rows: list[dict[str, float | int]], key: str) -> float:
    t_arr, y_arr = _window_values(rows, key)
    if t_arr.size < 2 or y_arr.size < 2:
        return 0.0
    return float(np.trapezoid(y_arr, t_arr))


def _integrate_abs_window(rows: list[dict[str, float | int]], key: str) -> float | None:
    t_arr, y_arr = _window_values(rows, key)
    if t_arr.size < 2 or y_arr.size < 2:
        return None
    return float(np.trapezoid(np.abs(y_arr), t_arr))


def _integrate_zone_abs_wall_window(rows: list[dict[str, float | int]], prefix: str | None) -> float | None:
    if not prefix:
        return None
    t_ref: np.ndarray | None = None
    summed: np.ndarray | None = None
    for zone in ("cylinder", "head", "piston"):
        t_arr, y_arr = _window_values(rows, f"{prefix}_wall_{zone}_heat_W")
        if t_arr.size < 2 or y_arr.size < 2:
            continue
        if t_ref is None:
            t_ref = t_arr
            summed = y_arr.astype(np.float64, copy=True)
            continue
        if t_arr.size == t_ref.size and np.allclose(t_arr, t_ref):
            summed = summed + y_arr if summed is not None else y_arr.astype(np.float64, copy=True)
    if t_ref is None or summed is None or t_ref.size < 2:
        return None
    return float(np.trapezoid(np.abs(summed), t_ref))


def _integrate_series(t_arr: np.ndarray, y_arr: np.ndarray) -> float:
    if t_arr.size < 2 or y_arr.size < 2 or t_arr.size != y_arr.size:
        return 0.0
    return float(np.trapezoid(y_arr, t_arr))

def _geometric_compression_ratio_data(bundle) -> tuple[float, float, float] | None:
    if getattr(bundle, "architecture", "classic") == "free_piston" and getattr(bundle, "free_piston", None) is not None:
        fp = bundle.free_piston
        vmin_m3 = max(float(fp.clearance_volume_m3), 0.0)
        swept_m3 = max(float(fp.piston_area_m2), 0.0) * max(float(fp.x_max_m) - float(fp.x_min_m), 0.0)
        vmax_m3 = vmin_m3 + swept_m3
        if vmin_m3 > 1.0e-18 and vmax_m3 >= vmin_m3:
            return float(vmax_m3 / vmin_m3), float(vmax_m3 * 1.0e6), float(vmin_m3 * 1.0e6)

    for vol_idx in getattr(bundle, 'cylinder_indices', []) or []:
        kin_idx = int(bundle.vol_matrix[int(vol_idx), VolumeCol.KIN_ROW])
        if kin_idx < 0:
            continue
        bore_m = max(float(bundle.kin_matrix[kin_idx, KinCol.BORE]), 0.0)
        stroke_m = max(float(bundle.kin_matrix[kin_idx, KinCol.STROKE]), 0.0)
        compression_ratio = max(float(bundle.kin_matrix[kin_idx, KinCol.COMPRESSION_RATIO]), 1.0)
        bore_area_m2 = 0.25 * math.pi * bore_m * bore_m
        swept_m3 = bore_area_m2 * stroke_m
        vmin_m3 = swept_m3 / (compression_ratio - 1.0) if compression_ratio > 1.0 else 0.0
        vmax_m3 = vmin_m3 + swept_m3
        if vmin_m3 > 1.0e-18 and vmax_m3 >= vmin_m3:
            return float(vmax_m3 / vmin_m3), float(vmax_m3 * 1.0e6), float(vmin_m3 * 1.0e6)
    return None


def _slot_closure_effective_compression_ratio_data(bundle) -> tuple[float, float, float, float] | None:
    if getattr(bundle, "architecture", "classic") != "free_piston" or getattr(bundle, "free_piston", None) is None:
        return None
    fp = bundle.free_piston
    cylinder_indices = list(getattr(bundle, "cylinder_indices", []) or [])
    if not cylinder_indices:
        return None
    cylinder_idx = int(cylinder_indices[0])
    slot_open_distances: list[float] = []
    for conn_idx in range(int(bundle.conn_matrix.shape[0])):
        conn = bundle.conn_matrix[conn_idx]
        if int(conn[ConnCol.TYPE]) != int(ConnectionType.SLOT):
            continue
        left = int(conn[ConnCol.FROM_VOL])
        right = int(conn[ConnCol.TO_VOL])
        if left != cylinder_idx and right != cylinder_idx:
            continue
        slot_open_distances.append(float(conn[ConnCol.OPEN_VALUE]))
    if not slot_open_distances:
        return None
    all_slots_closed_distance_m = min(slot_open_distances)
    stroke_window_m = max(float(fp.x_max_m) - float(fp.x_min_m), 0.0)
    all_slots_closed_distance_m = max(0.0, min(float(all_slots_closed_distance_m), stroke_window_m))
    vmin_m3 = max(float(fp.clearance_volume_m3), 0.0)
    vmax_closed_m3 = vmin_m3 + max(float(fp.piston_area_m2), 0.0) * all_slots_closed_distance_m
    if vmin_m3 <= 1.0e-18 or vmax_closed_m3 < vmin_m3:
        return None
    return (
        float(vmax_closed_m3 / vmin_m3),
        float(vmax_closed_m3 * 1.0e6),
        float(vmin_m3 * 1.0e6),
        float(all_slots_closed_distance_m * 1.0e3),
    )


def _value_at_keys(row: dict[str, float | int], keys: list[str]) -> float | None:
    for key in keys:
        if not key:
            continue
        value = _finite_float(row.get(key))
        if value is not None:
            return float(value)
    return None


def _slot_area_keys(rows: list[dict[str, float | int]]) -> list[str]:
    if not rows:
        return []
    keys: set[str] = set()
    for row in rows:
        for key in row.keys():
            if '_slot_A_eff_' in key and key.endswith('_m2'):
                keys.add(str(key))
    return sorted(keys)


def _slot_area_sum_m2(row: dict[str, float | int], keys: list[str]) -> float:
    total = 0.0
    for key in keys:
        value = _finite_float(row.get(key))
        if value is not None and value > 0.0:
            total += float(value)
    return total


def _available_prefixes(rows: list[dict[str, float | int]]) -> list[str]:
    if not rows:
        return []
    prefixes: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key.endswith('_p_Pa'):
                prefixes.add(str(key[:-len('_p_Pa')]))
    return sorted(prefixes)


def _find_named_prefix(rows: list[dict[str, float | int]], preferred_names: list[str]) -> str | None:
    prefixes = _available_prefixes(rows)
    if not prefixes:
        return None
    preferred_lc = [name.strip().lower() for name in preferred_names if name and name.strip()]
    for preferred in preferred_lc:
        for prefix in prefixes:
            if prefix.lower() == preferred:
                return prefix
    for preferred in preferred_lc:
        for prefix in prefixes:
            if preferred in prefix.lower():
                return prefix
    return None


def _append_volume_state_entries(
    entries: list[LastCycleEntry],
    state_name: str,
    state_row: dict[str, float | int] | None,
    prefix: str | None,
    label: str,
) -> None:
    if state_row is None or not prefix:
        return
    pressure_Pa = _value_at_keys(state_row, [f"{prefix}_p_Pa"])
    temperature_K = _value_at_keys(state_row, [f"{prefix}_T_K"])
    mass_kg = _value_at_keys(state_row, [f"{prefix}_m_kg"])
    volume_m3 = _value_at_keys(state_row, [f"{prefix}_V_m3"])
    if pressure_Pa is not None:
        entries.append(LastCycleEntry(f"{label}_{state_name}_pressure_bar", float(pressure_Pa) * 1.0e-5, 'bar'))
    if temperature_K is not None:
        entries.append(LastCycleEntry(f"{label}_{state_name}_temperature_K", float(temperature_K), 'K'))
    if mass_kg is not None:
        entries.append(LastCycleEntry(f"{label}_{state_name}_mass_mg", float(mass_kg) * 1.0e6, 'mg'))
    if volume_m3 is not None:
        entries.append(LastCycleEntry(f"{label}_{state_name}_volume_cm3", float(volume_m3) * 1.0e6, 'cm³'))


def _first_slots_closed_row(bundle, rows: list[dict[str, float | int]]) -> dict[str, float | int] | None:
    if not rows:
        return None
    slot_keys = _slot_area_keys(rows)
    if not slot_keys:
        return None
    fp = getattr(bundle, 'free_piston', None)
    threshold = max(float(getattr(fp, 'combustion_slot_closed_threshold_m2', 1.0e-9) or 1.0e-9), 0.0)
    for row in rows:
        if _slot_area_sum_m2(row, slot_keys) <= threshold:
            return row
    return None


def _first_combustion_start_row(bundle, rows: list[dict[str, float | int]], prefix: str | None) -> dict[str, float | int] | None:
    if not rows or not _bundle_combustion_enabled(bundle):
        return None
    active_keys = [f"{prefix}_combustion_active_0to1"] if prefix else []
    energy_keys = [f"{prefix}_added_energy_W"] if prefix else []
    for row in rows:
        active = _value_at_keys(row, active_keys)
        if active is not None and active > 0.5:
            return row
        added = _value_at_keys(row, energy_keys)
        if added is not None and added > 1.0e-12:
            return row
    return None


def _burned_residual_percent_from_row(row: dict[str, float | int] | None, prefix: str | None) -> float | None:
    if row is None or not prefix:
        return None
    total_mass = _value_at_keys(row, [f"{prefix}_m_kg", "cylinder_m_kg"])
    burned_mass = _value_at_keys(row, [f"{prefix}_m_burned_kg", "cylinder_m_burned_kg"])
    if total_mass is None or burned_mass is None or total_mass <= 1.0e-18:
        return None
    frac = max(0.0, min(1.0, float(burned_mass) / float(total_mass)))
    return 100.0 * frac


F_COMB = int(FeatureCol.COMBUSTION)


def _bundle_combustion_enabled(bundle) -> bool:
    feature_flags = getattr(bundle, 'feature_flags', None)
    return bool(feature_flags is not None and feature_flags.size > F_COMB and int(feature_flags[F_COMB]) == 1)


def _last_positive_value(rows: list[dict[str, float | int]], keys: list[str]) -> float | None:
    for row in reversed(rows):
        for key in keys:
            value = _finite_float(row.get(key))
            if value is not None and value > 0.0:
                return float(value)
    return None


def _last_finite_value(rows: list[dict[str, float | int]], keys: list[str]) -> float | None:
    for row in reversed(rows):
        for key in keys:
            value = _finite_float(row.get(key))
            if value is not None:
                return float(value)
    return None


def _last_cycle_rows_from_cycle_index(rows: list[dict[str, float | int]]) -> list[dict[str, float | int]]:
    if not rows:
        return []
    last_cycle = int(rows[-1].get("cycle_index", 0))
    return [row for row in rows if int(row.get("cycle_index", 0)) == last_cycle]


def _complete_cycle_markdown(bundle, rows: list[dict[str, float | int]] | None) -> str:
    duration_s = _finite_float(getattr(getattr(bundle, "simulation", None), "simulationtime_s", None))
    cycle_count = int(getattr(getattr(bundle, "simulation", None), "total_cycles", 0) or 0)

    if rows:
        t_vals: list[float] = []
        cycle_values: set[int] = set()
        x_vals: list[float] = []
        v_vals: list[float] = []
        for row in rows:
            t_val = _finite_float(row.get("t_s"))
            if t_val is not None:
                t_vals.append(t_val)
            cycle_raw = _finite_float(row.get("cycle_index"))
            if cycle_raw is not None:
                cycle_values.add(int(cycle_raw))
            x_val = _finite_float(row.get("free_piston_x_m"))
            v_val = _finite_float(row.get("free_piston_v_m_per_s"))
            if x_val is not None and v_val is not None and t_val is not None:
                x_vals.append(x_val)
                v_vals.append(v_val)
        if duration_s is None and len(t_vals) >= 2:
            duration_s = max(float(t_vals[-1] - t_vals[0]), 0.0)
        if getattr(bundle, "architecture", "classic") == "free_piston" and len(t_vals) == len(x_vals) == len(v_vals) and len(t_vals) >= 3:
            v_arr = np.asarray(v_vals, dtype=np.float64)
            max_v = float(np.max(np.abs(v_arr))) if v_arr.size else 0.0
            turning_count = count_ut_ot_ut_cycles(
                np.asarray(t_vals, dtype=np.float64),
                np.asarray(x_vals, dtype=np.float64),
                v_arr,
                eps=max(1.0e-10, 1.0e-6 * max_v),
            )
            if turning_count > cycle_count:
                cycle_count = turning_count
        elif cycle_values and len(cycle_values) > cycle_count:
            cycle_count = len(cycle_values)

    duration_text = "n/a" if duration_s is None else f"{duration_s:.12g}s"
    return "\n".join(
        [
            "# Complete Cycle",
            f"    Simulationdauer: {duration_text}",
            f"    Anzahl Zyklen: {cycle_count}",
        ]
    )


def _last_free_piston_cycle_rows(rows: list[dict[str, float | int]]) -> list[dict[str, float | int]]:
    if not rows:
        return []
    valid_rows: list[dict[str, float | int]] = []
    t_vals: list[float] = []
    x_vals: list[float] = []
    v_vals: list[float] = []
    row_indices: list[int] = []
    for idx, row in enumerate(rows):
        t_val = _finite_float(row.get("t_s"))
        x_val = _finite_float(row.get("free_piston_x_m"))
        v_val = _finite_float(row.get("free_piston_v_m_per_s"))
        if t_val is None or x_val is None or v_val is None:
            continue
        valid_rows.append(row)
        t_vals.append(t_val)
        x_vals.append(x_val)
        v_vals.append(v_val)
        row_indices.append(idx)
    if len(valid_rows) < 3:
        return []

    triplet = find_last_ut_ot_ut_turning_points(
        np.asarray(t_vals, dtype=np.float64),
        np.asarray(x_vals, dtype=np.float64),
        np.asarray(v_vals, dtype=np.float64),
    )
    if triplet is None:
        return []
    tp0, _tp1, tp2 = triplet
    start_row = row_indices[tp0.sample_index]
    end_row = row_indices[tp2.sample_index]
    if end_row <= start_row:
        return []
    return rows[start_row:end_row + 1]


def build_last_cycle_entries(bundle, rows: list[dict[str, float | int]] | None) -> list[LastCycleEntry]:
    if not rows:
        return []

    if getattr(bundle, "architecture", "classic") == "free_piston":
        cycle_rows = _last_free_piston_cycle_rows(list(rows))
        if not cycle_rows:
            cycle_rows = _last_cycle_rows_from_cycle_index(list(rows))
    else:
        cycle_rows = _last_cycle_rows_from_cycle_index(list(rows))
    if not cycle_rows:
        return []

    prefix = _find_primary_prefix(cycle_rows)
    t_arr = _row_values(cycle_rows, "t_s")
    if t_arr.size == 0:
        return []

    t_start_s = float(t_arr[0])
    t_end_s = float(t_arr[-1])
    duration_s = max(t_end_s - t_start_s, 0.0)
    frequency_hz = float(1.0 / duration_s) if duration_s > 1.0e-15 else 0.0

    v_arr = _row_values(cycle_rows, "free_piston_v_m_per_s")
    if v_arr.size == 0 and prefix and getattr(bundle, "architecture", "classic") == "free_piston" and getattr(bundle, "free_piston", None) is not None:
        dvdt_arr = _row_values(cycle_rows, f"{prefix}_dVdt_m3_per_s")
        if dvdt_arr.size:
            area = max(float(bundle.free_piston.piston_area_m2), 1.0e-30)
            v_arr = dvdt_arr / area

    mass_arr = _row_values(cycle_rows, f"{prefix}_m_kg") if prefix else np.zeros(0, dtype=np.float64)
    volume_arr = _row_values(cycle_rows, f"{prefix}_V_m3") if prefix else np.zeros(0, dtype=np.float64)
    x_arr = _row_values(cycle_rows, "free_piston_x_m")

    piston_work_J = _integrate_window(cycle_rows, f"{prefix}_piston_work_W") if prefix else 0.0
    wall_heat_net_J = _integrate_window(cycle_rows, f"{prefix}_wall_heat_W") if prefix else 0.0
    wall_heat_loss_J = _integrate_abs_window(cycle_rows, f"{prefix}_wall_heat_W") if prefix else None
    if wall_heat_loss_J is None:
        wall_heat_loss_J = _integrate_zone_abs_wall_window(cycle_rows, prefix)
    if wall_heat_loss_J is None:
        wall_heat_loss_J = abs(wall_heat_net_J)
    added_energy_J = _integrate_window(cycle_rows, f"{prefix}_added_energy_W") if prefix else 0.0
    htc_arr = _row_values(cycle_rows, f"{prefix}_htc_W_per_m2K") if prefix else np.zeros(0, dtype=np.float64)
    htc_mean = float(np.mean(htc_arr)) if htc_arr.size else 0.0
    htc_max = float(np.max(htc_arr)) if htc_arr.size else 0.0
    generator_work_J = _integrate_window(cycle_rows, "free_piston_generator_power_W") if getattr(bundle, "architecture", "classic") == "free_piston" else 0.0
    generator_work_J = max(0.0, generator_work_J)
    friction_force_t, friction_force_arr = _window_values(cycle_rows, "free_piston_F_friction_N")
    friction_speed_t, friction_speed_arr = _window_values(cycle_rows, "free_piston_v_m_per_s")
    friction_work_J = 0.0
    if friction_force_t.size >= 2 and friction_speed_t.size >= 2 and friction_force_t.size == friction_speed_t.size and np.allclose(friction_force_t, friction_speed_t):
        friction_power_arr = -(friction_force_arr * friction_speed_arr)
        friction_work_J = max(0.0, _integrate_series(friction_force_t, friction_power_arr))
    latched_air_mass_kg = _last_positive_value(cycle_rows, [
        f"{prefix}_combustion_air_mass_latched_kg" if prefix else '',
        'free_piston_combustion_mass_latched_kg',
    ])
    latched_fuel_mass_kg = _last_positive_value(cycle_rows, [
        f"{prefix}_combustion_fuel_mass_latched_kg" if prefix else '',
        'free_piston_combustion_fuel_mass_latched_kg',
    ])
    latched_energy_J = _last_positive_value(cycle_rows, [
        f"{prefix}_combustion_energy_latched_J" if prefix else '',
        'free_piston_combustion_energy_latched_J',
    ])
    lambda_value = _last_positive_value(cycle_rows, [
        f"{prefix}_lambda" if prefix else '',
        'free_piston_combustion_lambda',
    ])

    swept_volume_m3 = float(np.max(volume_arr) - np.min(volume_arr)) if volume_arr.size else 0.0
    imep_bar = float(piston_work_J / swept_volume_m3 / 1.0e5) if swept_volume_m3 > 1.0e-18 else 0.0

    entries: list[LastCycleEntry] = [
        LastCycleEntry("time_start_s", t_start_s, "s"),
        LastCycleEntry("time_end_s", t_end_s, "s"),
        LastCycleEntry("time_duration_s", duration_s, "s"),
        LastCycleEntry("time_duration_ms", duration_s * 1.0e3, "ms"),
        LastCycleEntry("frequency_Hz", frequency_hz, "Hz"),
        LastCycleEntry("imep_bar", imep_bar, "bar"),
        LastCycleEntry("piston_work_Nm", piston_work_J, "Nm"),
        LastCycleEntry("wall_heat_loss_J", wall_heat_loss_J, "J"),
        LastCycleEntry("added_energy_J", added_energy_J, "J"),
        LastCycleEntry("heat_transfer_coeff_mean_W_per_m2K", htc_mean, "W/m²K"),
        LastCycleEntry("heat_transfer_coeff_max_W_per_m2K", htc_max, "W/m²K"),
        LastCycleEntry("generator_work_J", generator_work_J, "J"),
        LastCycleEntry("friction_work_J", friction_work_J, "J"),
    ]

    indicated_power_total_W = 0.0
    indicated_power_count = 0
    last_row = cycle_rows[-1]
    cylinder_power_prefixes = sorted(
        {
            key[:-len("_piston_work_W")]
            for key in last_row
            if key.endswith("_piston_work_W") and key[:-len("_piston_work_W")].startswith("cylinder_")
        }
    )
    for cyl_prefix in cylinder_power_prefixes:
        cyl_work_J = _integrate_window(cycle_rows, f"{cyl_prefix}_piston_work_W")
        cyl_power_W = cyl_work_J / duration_s if duration_s > 1.0e-15 else 0.0
        entries.append(LastCycleEntry(f"{cyl_prefix}_indicated_power_W", cyl_power_W, "W"))
        cyl_volume_arr = _row_values(cycle_rows, f"{cyl_prefix}_V_m3")
        cyl_swept_m3 = float(np.max(cyl_volume_arr) - np.min(cyl_volume_arr)) if cyl_volume_arr.size else 0.0
        cyl_imep_bar = float(cyl_work_J / cyl_swept_m3 / 1.0e5) if cyl_swept_m3 > 1.0e-18 else 0.0
        entries.append(LastCycleEntry(f"{cyl_prefix}_imep_bar", cyl_imep_bar, "bar"))
        entries.append(LastCycleEntry(f"{cyl_prefix}_piston_work_Nm", cyl_work_J, "Nm"))
        cyl_added_J = _integrate_window(cycle_rows, f"{cyl_prefix}_added_energy_W")
        entries.append(LastCycleEntry(f"{cyl_prefix}_added_energy_J", cyl_added_J, "J"))
        cyl_wall_loss_J = _integrate_abs_window(cycle_rows, f"{cyl_prefix}_wall_heat_W")
        if cyl_wall_loss_J is None:
            cyl_wall_loss_J = _integrate_zone_abs_wall_window(cycle_rows, cyl_prefix)
        if cyl_wall_loss_J is not None:
            entries.append(LastCycleEntry(f"{cyl_prefix}_wall_heat_loss_J", cyl_wall_loss_J, "J"))
        for zone_name, label in (
            ("piston", "piston"),
            ("head", "head"),
            ("cylinder", "cylinder"),
        ):
            zone_loss_J = _integrate_abs_window(cycle_rows, f"{cyl_prefix}_wall_{zone_name}_heat_W")
            if zone_loss_J is not None:
                entries.append(LastCycleEntry(f"{cyl_prefix}_wall_{label}_heat_loss_J", zone_loss_J, "J"))
        cyl_lambda = _last_positive_value(cycle_rows, [f"{cyl_prefix}_lambda"])
        if cyl_lambda is not None:
            entries.append(LastCycleEntry(f"{cyl_prefix}_lambda", float(cyl_lambda), "-"))
        cyl_combustion_start_row = _first_combustion_start_row(bundle, cycle_rows, cyl_prefix)
        if cyl_combustion_start_row is not None:
            cyl_burned = _value_at_keys(cyl_combustion_start_row, [f"{cyl_prefix}_share_burned_0to1"])
            if cyl_burned is not None:
                entries.append(LastCycleEntry(f"{cyl_prefix}_restgas_anteil_brennbeginn_percent", float(cyl_burned) * 100.0, "%"))
        indicated_power_total_W += cyl_power_W
        indicated_power_count += 1
    if indicated_power_count > 1:
        entries.append(LastCycleEntry("indicated_power_total_W", indicated_power_total_W, "W"))

    cycle_start_row = cycle_rows[0]
    slots_closed_row = _first_slots_closed_row(bundle, cycle_rows) if getattr(bundle, "architecture", "classic") == "free_piston" else None
    combustion_start_row = _first_combustion_start_row(bundle, cycle_rows, prefix)
    state_rows: list[tuple[str, dict[str, float | int] | None]] = [
        ("cycle_start", cycle_start_row),
        ("all_slots_closed", slots_closed_row),
        ("combustion_start", combustion_start_row),
    ]
    for state_name, state_row in state_rows:
        if state_row is None:
            continue
        pressure_bar = _value_at_keys(state_row, [f"{prefix}_p_Pa" if prefix else "", "cylinder_p_Pa"])
        temperature_K = _value_at_keys(state_row, [f"{prefix}_T_K" if prefix else "", "cylinder_T_K"])
        hub_m = _value_at_keys(state_row, ["free_piston_distance_from_tdc_m", "free_piston_x_m"])
        speed_m_per_s = _value_at_keys(state_row, ["free_piston_v_m_per_s"])
        mass_kg = _value_at_keys(state_row, [f"{prefix}_m_kg" if prefix else "", "cylinder_m_kg"])
        time_s = _value_at_keys(state_row, ["t_s"])
        if time_s is not None:
            entries.append(LastCycleEntry(f"{state_name}_time_s", float(time_s), "s"))
        if pressure_bar is not None:
            entries.append(LastCycleEntry(f"{state_name}_pressure_bar", float(pressure_bar) * 1.0e-5, "bar"))
        if temperature_K is not None:
            entries.append(LastCycleEntry(f"{state_name}_temperature_K", float(temperature_K), "K"))
        if hub_m is not None:
            entries.append(LastCycleEntry(f"{state_name}_hub_mm", float(hub_m) * 1.0e3, "mm"))
        if speed_m_per_s is not None:
            entries.append(LastCycleEntry(f"{state_name}_speed_m_per_s", float(speed_m_per_s), "m/s"))
        if mass_kg is not None:
            entries.append(LastCycleEntry(f"{state_name}_mass_mg", float(mass_kg) * 1.0e6, "mg"))

    bounce_prefix = _find_named_prefix(cycle_rows, ['bounce', 'bounce_chamber'])
    receiver_prefix = _find_named_prefix(cycle_rows, ['receiver', 'intake_plenum'])
    plenum_prefix = _find_named_prefix(cycle_rows, ['exhaust_plenum', 'plenum', 'exhaust'])
    for state_name, state_row in state_rows:
        _append_volume_state_entries(entries, state_name, state_row, bounce_prefix, 'bounce')
        _append_volume_state_entries(entries, state_name, state_row, receiver_prefix, 'receiver')
        _append_volume_state_entries(entries, state_name, state_row, plenum_prefix, 'plenum')

    if mass_arr.size:
        entries.extend([
            LastCycleEntry("cylinder_mass_min_mg", float(np.min(mass_arr) * 1.0e6), "mg"),
            LastCycleEntry("cylinder_mass_max_mg", float(np.max(mass_arr) * 1.0e6), "mg"),
            LastCycleEntry("cylinder_mass_mean_mg", float(np.mean(mass_arr) * 1.0e6), "mg"),
        ])

    slot_closure_cr = _slot_closure_effective_compression_ratio_data(bundle)
    if slot_closure_cr is not None:
        slot_cr, slot_vmax_cm3, slot_vmin_cm3, slot_closed_hub_mm = slot_closure_cr
        entries.extend([
            LastCycleEntry("slot_closure_effective_compression_ratio", slot_cr, "-"),
            LastCycleEntry("slot_closure_effective_compression_ratio_Vmax_cm3", slot_vmax_cm3, "cm³"),
            LastCycleEntry("slot_closure_effective_compression_ratio_Vmin_cm3", slot_vmin_cm3, "cm³"),
            LastCycleEntry("slot_closure_all_slots_closed_hub_mm", slot_closed_hub_mm, "mm"),
        ])

    if volume_arr.size:
        v_min_m3 = float(np.min(volume_arr))
        v_max_m3 = float(np.max(volume_arr))
        if v_min_m3 > 1.0e-18 and v_max_m3 >= v_min_m3:
            entries.extend([
                LastCycleEntry("effective_compression_ratio", v_max_m3 / v_min_m3, "-"),
                LastCycleEntry("effective_compression_ratio_Vmax_cm3", v_max_m3 * 1.0e6, "cm³"),
                LastCycleEntry("effective_compression_ratio_Vmin_cm3", v_min_m3 * 1.0e6, "cm³"),
            ])

    if lambda_value is not None:
        entries.append(LastCycleEntry("lambda", float(lambda_value), "-"))
    burned_residual_percent = _burned_residual_percent_from_row(combustion_start_row, prefix)
    if burned_residual_percent is not None:
        entries.append(LastCycleEntry("verbrannter_restgasanteil_brennbeginn_percent", float(burned_residual_percent), "%"))
        entries.append(LastCycleEntry("restgas_anteil_brennbeginn_percent", float(burned_residual_percent), "%"))
    if latched_air_mass_kg is not None:
        entries.append(LastCycleEntry("air_mass_mg", float(latched_air_mass_kg) * 1.0e6, "mg"))
    if latched_fuel_mass_kg is not None:
        entries.append(LastCycleEntry("fuel_mass_mg", float(latched_fuel_mass_kg) * 1.0e6, "mg"))

    if x_arr.size:
        x_min_m = float(np.min(x_arr))
        x_max_m = float(np.max(x_arr))
        stroke_mm = (x_max_m - x_min_m) * 1.0e3
        x_center_m = 0.5 * (x_min_m + x_max_m)
        half_plus_mm = (x_max_m - x_center_m) * 1.0e3
        half_minus_mm = (x_min_m - x_center_m) * 1.0e3
        entries.extend([
            LastCycleEntry("last_stroke_mm", stroke_mm, "mm"),
            LastCycleEntry("last_half_stroke_plus_mm", half_plus_mm, "mm"),
            LastCycleEntry("last_half_stroke_minus_mm", half_minus_mm, "mm"),
        ])

    if v_arr.size:
        entries.extend([
            LastCycleEntry("piston_speed_max_m_per_s", float(np.max(v_arr)), "m/s"),
            LastCycleEntry("piston_speed_min_m_per_s", float(np.min(v_arr)), "m/s"),
            LastCycleEntry("piston_speed_mean_m_per_s", float(np.mean(v_arr)), "m/s"),
        ])

    return entries


def _format_last_cycle_value(entry: LastCycleEntry) -> str:
    if isinstance(entry.value, float):
        if not math.isfinite(entry.value):
            return str(entry.value)
        if entry.unit == "s":
            return f"{entry.value:.12g}"
        return f"{entry.value:.1f}"
    return str(entry.value)


def build_last_cycle_markdown(bundle, rows: list[dict[str, float | int]] | None, title: str = "Last-Cycle") -> str:
    entries = build_last_cycle_entries(bundle, rows)
    if not entries:
        return ""
    entry_map = {entry.metric_name: entry for entry in entries}

    lines = [
        f"# {title}",
        "",
        "Zyklusdefinition: letztes vollständiges Kolbenfenster UT → OT → UT, direkt aus den exportierten CSV-rows bestimmt.",
    ]
    geom_cr = _geometric_compression_ratio_data(bundle)
    if geom_cr is not None:
        geom_cr_value, geom_vmax_cm3, geom_vmin_cm3 = geom_cr
        lines.extend([
            "",
            f"Geometrisches Verdichtungsverhältnis: **{geom_cr_value:.6g}** (-)",
            f"Formel: ε_geom = V_max,geom / V_min,geom = {geom_vmax_cm3:.6g} cm³ / {geom_vmin_cm3:.6g} cm³ = {geom_cr_value:.6g}",
        ])

    slot_cr_entry = entry_map.get("slot_closure_effective_compression_ratio")
    slot_vmax_entry = entry_map.get("slot_closure_effective_compression_ratio_Vmax_cm3")
    slot_vmin_entry = entry_map.get("slot_closure_effective_compression_ratio_Vmin_cm3")
    slot_hub_entry = entry_map.get("slot_closure_all_slots_closed_hub_mm")
    if slot_cr_entry is not None and slot_vmax_entry is not None and slot_vmin_entry is not None and slot_hub_entry is not None:
        slot_cr_value = _format_last_cycle_value(slot_cr_entry)
        slot_vmax_value = _format_last_cycle_value(slot_vmax_entry)
        slot_vmin_value = _format_last_cycle_value(slot_vmin_entry)
        slot_hub_value = _format_last_cycle_value(slot_hub_entry)
        lines.extend([
            "",
            f"Effektives Verdichtungsverhältnis ab Slot-Schluss: **{slot_cr_value}** (-)",
            f"Formel: ε_slot_zu = V_max,Slots_geschlossen / V_min = {slot_vmax_value} cm³ / {slot_vmin_value} cm³ = {slot_cr_value}",
            f"Alle Slots sind im Kompressionshub ab Hub <= {slot_hub_value} mm geschlossen; dieses Volumen wird als V_max,Slots_geschlossen verwendet.",
        ])

    cr_entry = entry_map.get("effective_compression_ratio")
    vmax_entry = entry_map.get("effective_compression_ratio_Vmax_cm3")
    vmin_entry = entry_map.get("effective_compression_ratio_Vmin_cm3")
    if cr_entry is not None and vmax_entry is not None and vmin_entry is not None:
        cr_value = _format_last_cycle_value(cr_entry)
        vmax_value = _format_last_cycle_value(vmax_entry)
        vmin_value = _format_last_cycle_value(vmin_entry)
        lines.extend([
            "",
            f"Letztes effektives Verdichtungsverhältnis: **{cr_value}** (-)",
            f"Formel: ε_eff = V_max / V_min = {vmax_value} cm³ / {vmin_value} cm³ = {cr_value}",
        ])

    htc_mean_entry = entry_map.get("heat_transfer_coeff_mean_W_per_m2K")
    htc_max_entry = entry_map.get("heat_transfer_coeff_max_W_per_m2K")
    if htc_mean_entry is not None:
        lines.extend([
            "",
            f"Mittlerer Wärmeübergangskoeffizient: **{_format_last_cycle_value(htc_mean_entry)}** ({htc_mean_entry.unit})",
        ])
    if htc_max_entry is not None:
        lines.extend([
            f"Maximaler Wärmeübergangskoeffizient: **{_format_last_cycle_value(htc_max_entry)}** ({htc_max_entry.unit})",
        ])

    lines.extend([
        "",
        "| Größe | Wert | Einheit |",
        "|---|---:|---|",
    ])
    for entry in entries:
        value = _format_last_cycle_value(entry)
        lines.append(f"| {entry.metric_name} | {value} | {entry.unit} |")
    return "\n".join(lines)


def _fmt_energy(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "n/a"
    return f"{value:.6g} J"


def _fmt_pct(value: float | None, ref: float | None) -> str:
    if value is None or ref is None or abs(ref) <= 1.0e-18 or not math.isfinite(value) or not math.isfinite(ref):
        return "n/a"
    return f"{100.0 * value / ref:.2f} %"


def _energy_balance_for_prefix(
    rows: list[dict[str, float | int]],
    prefix: str,
    *,
    include_global_loads: bool,
) -> dict[str, float | None]:
    added_energy_J = _integrate_window(rows, f"{prefix}_added_energy_W")
    piston_work_J = _integrate_window(rows, f"{prefix}_piston_work_W")
    wall_heat_loss_J = _integrate_abs_window(rows, f"{prefix}_wall_heat_W")
    zone_wall_heat_loss_J = _integrate_zone_abs_wall_window(rows, prefix)
    if zone_wall_heat_loss_J is not None:
        wall_heat_loss_J = zone_wall_heat_loss_J

    friction_work_J: float | None = None
    generator_work_J: float | None = None
    if include_global_loads:
        friction_pairs: list[tuple[float, float]] = []
        for row in rows:
            t_val = _finite_float(row.get("t_s"))
            force_val = _finite_float(row.get("free_piston_F_friction_N"))
            v_val = _finite_float(row.get("free_piston_v_m_per_s"))
            if t_val is None or force_val is None or v_val is None:
                continue
            friction_pairs.append((t_val, abs(force_val * v_val)))
        if len(friction_pairs) >= 2:
            friction_work_J = float(
                np.trapezoid(
                    np.asarray([value for _time, value in friction_pairs], dtype=np.float64),
                    np.asarray([time for time, _value in friction_pairs], dtype=np.float64),
                )
            )
        generator_work_J = _integrate_abs_window(rows, "free_piston_generator_power_W")

    known_out_J = sum(
        value
        for value in (piston_work_J, wall_heat_loss_J, friction_work_J, generator_work_J)
        if value is not None
    )
    rest_J = added_energy_J - known_out_J
    return {
        "added_energy_J": added_energy_J,
        "piston_work_J": piston_work_J,
        "wall_heat_loss_J": wall_heat_loss_J,
        "friction_work_J": friction_work_J,
        "generator_work_J": generator_work_J,
        "rest_J": rest_J,
    }


def _cycle_rows_for_energy_balance(bundle, rows: list[dict[str, float | int]] | None) -> list[dict[str, float | int]]:
    if not rows:
        return []
    if getattr(bundle, "architecture", "classic") == "free_piston":
        cycle_rows = _last_free_piston_cycle_rows(list(rows))
        if cycle_rows:
            return cycle_rows
    return _last_cycle_rows_from_cycle_index(list(rows))


def _cylinder_label(prefix: str) -> str:
    match = re.fullmatch(r"cylinder_(\d+)", prefix)
    if match:
        return f"Cylinder {match.group(1)}"
    match = re.fullmatch(r"compressor_(\d+)", prefix)
    if match:
        return f"compressor_{match.group(1)}"
    return prefix


def _append_energy_balance_lines(lines: list[str], label: str, balance: dict[str, float | None]) -> None:
    added_energy_J = balance["added_energy_J"]
    lines.extend(
        [
            f"{label}: ",
            f"- Zugeführte Energie: {_fmt_energy(added_energy_J)} ({_fmt_pct(added_energy_J, added_energy_J)})",
            f"- Kolbenarbeit: {_fmt_energy(balance['piston_work_J'])} ({_fmt_pct(balance['piston_work_J'], added_energy_J)})",
            f"- Wandwärmeverluste: {_fmt_energy(balance['wall_heat_loss_J'])} ({_fmt_pct(balance['wall_heat_loss_J'], added_energy_J)})",
            f"- Reibarbeit: {_fmt_energy(balance['friction_work_J'])} ({_fmt_pct(balance['friction_work_J'], added_energy_J)})",
            f"- Generatorarbeit: {_fmt_energy(balance['generator_work_J'])} ({_fmt_pct(balance['generator_work_J'], added_energy_J)})",
            f"- Rest: {_fmt_energy(balance['rest_J'])} ({_fmt_pct(balance['rest_J'], added_energy_J)})",
            "",
        ]
    )


def _build_energy_balance_markdown(bundle, rows: list[dict[str, float | int]] | None) -> str:
    cycle_rows = _cycle_rows_for_energy_balance(bundle, rows)
    if not cycle_rows:
        return ""
    sample = cycle_rows[-1]
    cylinder_prefixes = sorted(
        {
            str(key)[:-len("_added_energy_W")]
            for key in sample
            if str(key).startswith("cylinder_") and str(key).endswith("_added_energy_W")
        },
        key=lambda item: [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", item)],
    )
    if not cylinder_prefixes:
        primary_prefix = _find_primary_prefix(cycle_rows)
        if primary_prefix is None:
            return ""
        cylinder_prefixes = [primary_prefix]

    balances: list[dict[str, float | None]] = []
    lines = ["## Energiebilanz vom letzten Zyklus"]
    for prefix in cylinder_prefixes:
        balance = _energy_balance_for_prefix(cycle_rows, prefix, include_global_loads=False)
        balances.append(balance)
        _append_energy_balance_lines(lines, _cylinder_label(prefix), balance)

    if len(balances) > 1:
        global_loads = _energy_balance_for_prefix(cycle_rows, cylinder_prefixes[0], include_global_loads=True)
        total_balance = {
            key: sum(value for value in (balance.get(key) for balance in balances) if value is not None)
            for key in ("added_energy_J", "piston_work_J", "wall_heat_loss_J", "friction_work_J", "generator_work_J", "rest_J")
        }
        total_balance["friction_work_J"] = global_loads.get("friction_work_J")
        total_balance["generator_work_J"] = global_loads.get("generator_work_J")
        known_out_J = sum(
            value
            for value in (
                total_balance.get("piston_work_J"),
                total_balance.get("wall_heat_loss_J"),
                total_balance.get("friction_work_J"),
                total_balance.get("generator_work_J"),
            )
            if value is not None
        )
        total_balance["rest_J"] = total_balance["added_energy_J"] - known_out_J
        _append_energy_balance_lines(lines, "Gesamt", total_balance)
    return "\n".join(lines).rstrip()


def _wall_temperature_groups_from_bundle(bundle) -> dict[str, dict[str, float]]:
    state_by_vol = getattr(bundle, "wall_temperature_state_index_by_vol", None)
    y_init = getattr(bundle, "y_init", None)
    volume_names = list(getattr(bundle, "volume_names", []) or [])
    if state_by_vol is None or y_init is None or not volume_names:
        return {}
    state_arr = np.asarray(state_by_vol, dtype=np.int64)
    y_arr = np.asarray(y_init, dtype=np.float64)
    zone_indices = {
        "piston": int(WallTemperatureZone.PISTON),
        "cylinder": int(WallTemperatureZone.CYLINDER),
        "head": int(WallTemperatureZone.HEAD),
    }
    grouped: dict[str, dict[str, float]] = {}
    for vol_i, prefix in enumerate(volume_names):
        if vol_i >= state_arr.shape[0]:
            continue
        for zone_name, zone_idx in zone_indices.items():
            if zone_idx >= state_arr.shape[1]:
                continue
            state_idx = int(state_arr[vol_i, zone_idx])
            if state_idx < 0 or state_idx >= y_arr.size:
                continue
            temp_K = _finite_float(y_arr[state_idx])
            if temp_K is None:
                continue
            grouped.setdefault(str(prefix), {})[zone_name] = temp_K - 273.15
    return grouped


def _wall_temperature_groups_from_rows(rows: list[dict[str, float | int]] | None) -> dict[str, dict[str, float]]:
    if not rows:
        return {}
    sample = rows[-1]
    grouped: dict[str, dict[str, float]] = {}
    zone_names = {
        "piston": "Piston",
        "cylinder": "Lineer",
        "head": "Head",
    }
    for key, value in sample.items():
        if "_wall_" not in str(key) or not str(key).endswith("_temperature_K"):
            continue
        prefix, rest = str(key).split("_wall_", 1)
        zone = rest[:-len("_temperature_K")]
        if zone not in zone_names:
            continue
        temp_K = _finite_float(value)
        if temp_K is None:
            continue
        grouped.setdefault(prefix, {})[zone] = temp_K - 273.15
    return grouped


def _build_wall_temperature_markdown(bundle, rows: list[dict[str, float | int]] | None) -> str:
    zone_names = {
        "piston": "Piston",
        "cylinder": "Lineer",
        "head": "Head",
    }
    grouped = _wall_temperature_groups_from_bundle(bundle)
    if not grouped:
        grouped = _wall_temperature_groups_from_rows(rows)
    if not grouped:
        return ""
    lines = ["##  Wandtemperatturen ", ""]
    for prefix in sorted(grouped):
        zones = grouped[prefix]
        lines.append(f"    {_cylinder_label(prefix)} : ")
        for zone, label in zone_names.items():
            if zone in zones:
                spacer = " " if label == "Piston" else ""
                lines.append(f"        {label}:{spacer}{zones[zone]:.1f} °C")
        lines.append("")
    cylinder_groups = [zones for prefix, zones in grouped.items() if re.fullmatch(r"cylinder_\d+", prefix)]
    if len(cylinder_groups) > 1 and all(cylinder_groups[0] == zones for zones in cylinder_groups[1:]):
        lines.extend([
            "Hinweis: Die Wandtemperaturen der Arbeitszylinder sind identisch, weil die Zylinder dasselbe Wandtemperatur-Submodell referenzieren.",
            "Fuer unterschiedliche Wandtemperaturen je Zylinder muessen getrennte Wandtemperatur-Submodelle konfiguriert werden.",
        ])
    return "\n".join(lines).rstrip()


@dataclass(slots=True)
class GeometryEntry:
    category: str
    entity_name: str
    metric_name: str
    value: float
    unit: str
    details: str

    @property
    def key(self) -> str:
        prefix = re.sub(r"[^0-9A-Za-z_]+", "_", str(self.entity_name).strip()).strip("_") or self.category
        return f"{prefix}_{self.metric_name}"


def _interp_piecewise(x: float, xs: np.ndarray, ys: np.ndarray) -> float:
    if xs.size == 0 or ys.size == 0:
        return 0.0
    if xs.size == 1:
        return float(ys[0])
    if x <= float(xs[0]):
        return float(ys[0])
    if x >= float(xs[-1]):
        return float(ys[-1])
    idx = int(np.searchsorted(xs, x, side='right'))
    x0 = float(xs[idx - 1])
    x1 = float(xs[idx])
    y0 = float(ys[idx - 1])
    y1 = float(ys[idx])
    if abs(x1 - x0) <= 1.0e-18:
        return y1
    frac = (float(x) - x0) / (x1 - x0)
    return y0 + frac * (y1 - y0)


def _piecewise_linear_max(xs: np.ndarray, ys: np.ndarray, x_lo: float, x_hi: float) -> float:
    if xs.size == 0 or ys.size == 0 or x_hi <= x_lo:
        return 0.0
    candidates = [float(x_lo), float(x_hi)]
    for x in xs:
        xv = float(x)
        if x_lo <= xv <= x_hi:
            candidates.append(xv)
    return max((_interp_piecewise(x, xs, ys) for x in candidates), default=0.0)


def _piecewise_product_max(xs: np.ndarray, ys: np.ndarray, scale: float, x_lo: float, x_hi: float) -> float:
    if xs.size == 0 or ys.size == 0 or x_hi <= x_lo or scale <= 0.0:
        return 0.0
    x_lo = float(x_lo)
    x_hi = float(x_hi)
    knot_values = [x_lo, x_hi]
    for x in xs:
        xv = float(x)
        if x_lo <= xv <= x_hi:
            knot_values.append(xv)
    best = max((scale * x * _interp_piecewise(x, xs, ys) for x in knot_values), default=0.0)
    for idx in range(1, xs.size):
        seg_lo = max(x_lo, float(xs[idx - 1]))
        seg_hi = min(x_hi, float(xs[idx]))
        if seg_hi <= seg_lo:
            continue
        x0 = float(xs[idx - 1])
        x1 = float(xs[idx])
        y0 = float(ys[idx - 1])
        y1 = float(ys[idx])
        if abs(x1 - x0) <= 1.0e-18:
            continue
        a = (y1 - y0) / (x1 - x0)
        b = y0 - a * x0
        if abs(a) > 1.0e-18:
            x_vertex = -b / (2.0 * a)
            if seg_lo <= x_vertex <= seg_hi:
                best = max(best, scale * x_vertex * (a * x_vertex + b))
    return max(best, 0.0)


def _free_piston_geometry_entries(bundle) -> list[GeometryEntry]:
    fp = getattr(bundle, 'free_piston', None)
    if fp is None:
        return []
    entity = str(bundle.volume_names[bundle.cylinder_indices[0]]) if getattr(bundle, 'cylinder_indices', None) else 'free_piston'
    stroke_window_m = max(float(fp.x_max_m) - float(fp.x_min_m), 0.0)
    entries = [
        GeometryEntry('free_piston', entity, 'moving_mass_kg', float(fp.moving_mass_kg), 'kg', 'Freikolben-Geometrie: bewegte Masse.'),
        GeometryEntry('free_piston', entity, 'piston_diameter_mm', float(fp.piston_diameter_m) * 1.0e3, 'mm', 'Freikolben-Geometrie: Kolbendurchmesser.'),
        GeometryEntry('free_piston', entity, 'compression_ratio', float(fp.compression_ratio), '-', 'Freikolben-Geometrie: geometrisches Verdichtungsverhältnis.'),
        GeometryEntry('free_piston', entity, 'piston_area_mm2', float(fp.piston_area_m2) * 1.0e6, 'mm²', 'Freikolben-Geometrie: intern daraus abgeleitete wirksame Kolbenfläche.'),
        GeometryEntry('free_piston', entity, 'clearance_cm3', float(fp.clearance_volume_m3) * 1.0e6, 'cm³', 'Freikolben-Geometrie: intern daraus abgeleitetes Restvolumen des Zylinders bei x_min/TDC.'),
        GeometryEntry('free_piston', entity, 'x_min_mm', float(fp.x_min_m) * 1.0e3, 'mm', 'Freikolben-Geometrie: untere Positionsgrenze.'),
        GeometryEntry('free_piston', entity, 'x_max_mm', float(fp.x_max_m) * 1.0e3, 'mm', 'Freikolben-Geometrie: obere Positionsgrenze.'),
        GeometryEntry('free_piston', entity, 'stroke_window_mm', stroke_window_m * 1.0e3, 'mm', 'Freikolben-Geometrie: verfügbarer Hubraumweg zwischen x_min und x_max.'),
        GeometryEntry('free_piston', entity, 'initial_cylinder_volume_cm3', float(fp.initial_cylinder_volume_m3) * 1.0e6, 'cm³', 'Freikolben-Geometrie: Zylindervolumen zum Startzeitpunkt.'),
        GeometryEntry('free_piston', entity, 'bounce_diameter_mm', float(fp.bounce_chamber_diameter_m) * 1.0e3, 'mm', 'Freikolben-Geometrie: Innendurchmesser des Bounce-Raums.'),
        GeometryEntry('free_piston', entity, 'bounce_length_mm', float(fp.bounce_chamber_length_m) * 1.0e3, 'mm', 'Freikolben-Geometrie: wirksame Bounce-Hublänge zur Bestimmung des Bounce-Hubvolumens.'),
        GeometryEntry('free_piston', entity, 'bounce_compression_ratio', float(fp.bounce_compression_ratio), '-', 'Freikolben-Geometrie: Verdichtungsverhältnis des Bounce-Raums.'),
        GeometryEntry('free_piston', entity, 'bounce_cross_section_mm2', float(fp.bounce_chamber_cross_section_m2) * 1.0e6, 'mm²', 'Freikolben-Geometrie: geometrische Querschnittsfläche des Bounce-Raums aus dem Durchmesser.'),
        GeometryEntry('free_piston', entity, 'bounce_swept_cm3', float(fp.bounce_swept_volume_m3) * 1.0e6, 'cm³', 'Freikolben-Geometrie: Bounce-Hubvolumen aus Durchmesser und Hublänge.'),
        GeometryEntry('free_piston', entity, 'bounce_effective_area_mm2', float(fp.bounce_area_m2) * 1.0e6, 'mm²', 'Freikolben-Geometrie: wirksame dV/dx-Fläche des Bounce-Raums entlang des Freikolbenhubs.'),
        GeometryEntry('free_piston', entity, 'bounce_vmin_cm3', float(fp.bounce_chamber_min_volume_m3) * 1.0e6, 'cm³', 'Freikolben-Geometrie: minimales Bounce-Volumen bei UT/BDC (gegenläufig zum Arbeitszylinder).'),
        GeometryEntry('free_piston', entity, 'bounce_vmax_cm3', float(fp.bounce_chamber_volume0_m3) * 1.0e6, 'cm³', 'Freikolben-Geometrie: maximales Bounce-Volumen bei OT/TDC (gegenläufig zum Arbeitszylinder).'),
    ]
    if bool(getattr(fp, 'scavenging_enabled', False)):
        entries.extend([
            GeometryEntry('scavenging', entity, 'enabled', 1.0, '-', '0D-Scavenging model active.'),
            GeometryEntry('scavenging', entity, 'scavenging_factor', float(getattr(fp, 'scavenging_factor', 0.0)), '-', '0D scavenging: exhaust displacement strength during slot overlap.'),
            GeometryEntry('scavenging', entity, 'max_trapping_efficiency', float(getattr(fp, 'scavenging_max_trapping_efficiency', 0.0)), '-', '0D scavenging: upper limit for fresh-charge trapping efficiency.'),
            GeometryEntry('scavenging', entity, 'short_circuit_start_ratio', float(getattr(fp, 'scavenging_short_circuit_start_ratio', 0.0)), '-', '0D scavenging: transfer/exhaust flow ratio where fresh-air short circuit starts.'),
            GeometryEntry('scavenging', entity, 'short_circuit_slope', float(getattr(fp, 'scavenging_short_circuit_slope', 0.0)), '-', '0D scavenging: soft transition width of the short-circuit fraction.'),
            GeometryEntry('scavenging', entity, 'max_short_circuit_fraction', float(getattr(fp, 'scavenging_max_short_circuit_fraction', 0.0)), '-', '0D scavenging: maximum fresh-air short-circuit fraction.'),
            GeometryEntry('scavenging', entity, 'min_residual_fraction', float(getattr(fp, 'scavenging_min_residual_fraction', 0.0)), '-', '0D scavenging: residual-gas floor for displacement correction.'),
        ])
    return entries


def build_geometry_entries(bundle) -> list[GeometryEntry]:
    entries: list[GeometryEntry] = []
    vol_matrix = getattr(bundle, 'vol_matrix', np.zeros((0, len(VolumeCol)), dtype=np.float64))
    kin_matrix = getattr(bundle, 'kin_matrix', np.zeros((0, len(KinCol)), dtype=np.float64))
    conn_matrix = getattr(bundle, 'conn_matrix', np.zeros((0, len(ConnCol)), dtype=np.float64))
    lift_table = getattr(bundle, 'lift_table', np.zeros((0, 2), dtype=np.float64))
    alpha_table = getattr(bundle, 'alpha_table', np.zeros((0, 3), dtype=np.float64))
    cd_table = getattr(bundle, 'cd_table', np.zeros((0, 3), dtype=np.float64))
    volume_names = list(getattr(bundle, 'volume_names', []) or [])
    connection_names = list(getattr(bundle, 'connection_names', []) or [])

    if getattr(bundle, 'architecture', 'classic') == 'free_piston':
        entries.extend(_free_piston_geometry_entries(bundle))

    for vol_idx in getattr(bundle, 'cylinder_indices', []) or []:
        if int(vol_idx) >= int(vol_matrix.shape[0]):
            continue
        kin_idx = int(vol_matrix[int(vol_idx), VolumeCol.KIN_ROW])
        if kin_idx < 0:
            continue
        if kin_idx >= int(kin_matrix.shape[0]):
            continue
        name = str(volume_names[int(vol_idx)]) if int(vol_idx) < len(volume_names) else f'volume_{int(vol_idx)}'
        bore_m = max(float(kin_matrix[kin_idx, KinCol.BORE]), 0.0)
        stroke_m = max(float(kin_matrix[kin_idx, KinCol.STROKE]), 0.0)
        conrod_m = max(float(kin_matrix[kin_idx, KinCol.CONROD]), 0.0)
        compression_ratio = max(float(kin_matrix[kin_idx, KinCol.COMPRESSION_RATIO]), 1.0)
        bore_area_m2 = 0.25 * math.pi * bore_m * bore_m
        swept_m3 = bore_area_m2 * stroke_m
        clearance_m3 = swept_m3 / (compression_ratio - 1.0) if compression_ratio > 1.0 else 0.0
        entries.extend([
            GeometryEntry('cylinder', name, 'bore_mm', bore_m * 1.0e3, 'mm', 'Zylindergeometrie: Bohrung.'),
            GeometryEntry('cylinder', name, 'stroke_mm', stroke_m * 1.0e3, 'mm', 'Zylindergeometrie: Hub.'),
            GeometryEntry('cylinder', name, 'conrod_mm', conrod_m * 1.0e3, 'mm', 'Zylindergeometrie: Pleuellänge.'),
            GeometryEntry('cylinder', name, 'bore_area_mm2', bore_area_m2 * 1.0e6, 'mm²', 'Zylindergeometrie: Bohrungsfläche.'),
            GeometryEntry('cylinder', name, 'swept_cm3', swept_m3 * 1.0e6, 'cm³', 'Zylindergeometrie: Hubvolumen.'),
            GeometryEntry('cylinder', name, 'clearance_cm3', clearance_m3 * 1.0e6, 'cm³', 'Zylindergeometrie: Restvolumen.'),
        ])


    for vol_idx in range(vol_matrix.shape[0]):
        vol_type = int(vol_matrix[vol_idx, VolumeCol.TYPE])
        if vol_type not in (int(VolumeType.PLENUM), int(VolumeType.ENVIRONMENT)):
            continue
        name = str(volume_names[vol_idx]) if vol_idx < len(volume_names) else f'volume_{vol_idx}'
        fixed_m3 = max(float(vol_matrix[vol_idx, VolumeCol.FIXED_VOLUME]), 0.0)
        metric = 'fixed_cm3' if vol_type == int(VolumeType.PLENUM) else 'reference_cm3'
        details = 'Plenum-Geometrie: festes Volumen.' if vol_type == int(VolumeType.PLENUM) else 'Umgebungs-Referenzvolumen.'
        category = 'plenum' if vol_type == int(VolumeType.PLENUM) else 'environment'
        entries.append(
            GeometryEntry(category, name, metric, fixed_m3 * 1.0e6, 'cm³', details)
        )

    for conn_idx in range(conn_matrix.shape[0]):
        conn = conn_matrix[conn_idx]
        conn_type = int(conn[ConnCol.TYPE])
        name = str(connection_names[conn_idx]) if conn_idx < len(connection_names) else f'connection_{conn_idx}'
        if conn_type == int(ConnectionType.VALVE):
            p_start = int(conn[ConnCol.PROFILE_START])
            p_len = int(conn[ConnCol.PROFILE_LEN])
            a_start = int(conn[ConnCol.ALPHA_START])
            a_len = int(conn[ConnCol.ALPHA_LEN])
            lift_slice = lift_table[p_start:p_start + p_len] if p_len > 0 else np.zeros((0, 2), dtype=np.float64)
            alpha_slice = alpha_table[a_start:a_start + a_len] if a_len > 0 else np.zeros((0, 3), dtype=np.float64)
            lift_scale = max(float(conn[ConnCol.LIFT_SCALE]), 0.0)
            lash_m = max(float(conn[ConnCol.LASH]), 0.0)
            ref_area_m2 = max(float(conn[ConnCol.REF_FLOW_AREA]), 0.0)
            lift_max_m = 0.0
            if lift_slice.size:
                lift_max_m = max(float(np.max(lift_slice[:, 1])) * lift_scale - lash_m, 0.0)
            alpha_f_max = 0.0
            alpha_r_max = 0.0
            if alpha_slice.size and lift_max_m > 0.0:
                xs = np.asarray(alpha_slice[:, 0], dtype=np.float64)
                alpha_f = np.asarray(alpha_slice[:, 1], dtype=np.float64)
                alpha_r = np.asarray(alpha_slice[:, 2], dtype=np.float64)
                alpha_f_max = _piecewise_linear_max(xs, alpha_f, 0.0, lift_max_m)
                alpha_r_max = _piecewise_linear_max(xs, alpha_r, 0.0, lift_max_m)
            entries.extend([
                GeometryEntry('valve', name, 'lift_max_mm', lift_max_m * 1.0e3, 'mm', 'Ventilgeometrie: maximaler effektiver Lift nach Skalierung und Lash.'),
                GeometryEntry('valve', name, 'A_ref_mm2', ref_area_m2 * 1.0e6, 'mm²', 'Ventilgeometrie: Referenzfläche.'),
                GeometryEntry('valve', name, 'A_eff_forward_max_mm2', ref_area_m2 * alpha_f_max * 1.0e6, 'mm²', 'Ventilgeometrie: maximale effektive Vorwärtsfläche.'),
                GeometryEntry('valve', name, 'A_eff_reverse_max_mm2', ref_area_m2 * alpha_r_max * 1.0e6, 'mm²', 'Ventilgeometrie: maximale effektive Rückwärtsfläche.'),
            ])
        elif conn_type == int(ConnectionType.SLOT):
            width_m = max(float(conn[ConnCol.PRIMARY_DIM]), 0.0)
            height_m = max(float(conn[ConnCol.SECONDARY_DIM]), 0.0)
            holes = max(float(conn[ConnCol.N_HOLES]), 0.0)
            geom_scale = width_m * holes
            a_geom_max_m2 = geom_scale * height_m
            if int(conn[ConnCol.CD_MODE]) == int(FlowCoeffMode.CONSTANT):
                a_eff_forward_max_m2 = a_geom_max_m2 * max(float(conn[ConnCol.CD_FORWARD]), 0.0)
                a_eff_reverse_max_m2 = a_geom_max_m2 * max(float(conn[ConnCol.CD_REVERSE]), 0.0)
            else:
                start = int(conn[ConnCol.CD_TABLE_START])
                length = int(conn[ConnCol.CD_TABLE_LEN])
                cd_slice = cd_table[start:start + length] if length > 0 else np.zeros((0, 3), dtype=np.float64)
                xs = np.asarray(cd_slice[:, 0], dtype=np.float64) if cd_slice.size else np.zeros((0,), dtype=np.float64)
                cd_f = np.asarray(cd_slice[:, 1], dtype=np.float64) if cd_slice.size else np.zeros((0,), dtype=np.float64)
                cd_r = np.asarray(cd_slice[:, 2], dtype=np.float64) if cd_slice.size else np.zeros((0,), dtype=np.float64)
                a_eff_forward_max_m2 = _piecewise_product_max(xs, cd_f, geom_scale, 0.0, height_m)
                a_eff_reverse_max_m2 = _piecewise_product_max(xs, cd_r, geom_scale, 0.0, height_m)
            entries.extend([
                GeometryEntry('slot', name, 'slot_height_max_mm', height_m * 1.0e3, 'mm', 'Slotgeometrie: maximale offene Höhe.'),
                GeometryEntry('slot', name, 'A_geom_max_mm2', a_geom_max_m2 * 1.0e6, 'mm²', 'Slotgeometrie: maximale geometrische Öffnungsfläche.'),
                GeometryEntry('slot', name, 'A_eff_forward_max_mm2', a_eff_forward_max_m2 * 1.0e6, 'mm²', 'Slotgeometrie: maximale effektive Vorwärtsfläche.'),
                GeometryEntry('slot', name, 'A_eff_reverse_max_mm2', a_eff_reverse_max_m2 * 1.0e6, 'mm²', 'Slotgeometrie: maximale effektive Rückwärtsfläche.'),
            ])
        elif conn_type == int(ConnectionType.ORIFICE):
            area_m2 = max(float(conn[ConnCol.PRIMARY_DIM]), 0.0)
            a_eff_forward_max_m2 = area_m2 * max(float(conn[ConnCol.CD_FORWARD]), 0.0)
            a_eff_reverse_max_m2 = area_m2 * max(float(conn[ConnCol.CD_REVERSE]), 0.0)
            entries.extend([
                GeometryEntry('orifice', name, 'A_geom_max_mm2', area_m2 * 1.0e6, 'mm²', 'Drosselgeometrie: geometrische Fläche.'),
                GeometryEntry('orifice', name, 'A_eff_forward_max_mm2', a_eff_forward_max_m2 * 1.0e6, 'mm²', 'Drosselgeometrie: maximale effektive Vorwärtsfläche.'),
                GeometryEntry('orifice', name, 'A_eff_reverse_max_mm2', a_eff_reverse_max_m2 * 1.0e6, 'mm²', 'Drosselgeometrie: maximale effektive Rückwärtsfläche.'),
            ])
        elif conn_type == int(ConnectionType.CHECK_VALVE):
            area_m2 = max(float(conn[ConnCol.PRIMARY_DIM]), 0.0)
            cd_forward = max(float(conn[ConnCol.CD_FORWARD]), 0.0)
            cd_reverse = max(float(conn[ConnCol.CD_REVERSE]), 0.0)
            cracking_pressure_bar = max(float(conn[ConnCol.OPEN_VALUE]), 0.0) * 1.0e-5
            entries.extend([
                GeometryEntry('check_valve', name, 'A_geom_max_mm2', area_m2 * 1.0e6, 'mm²', 'Rückschlagventilgeometrie: geometrische Fläche.'),
                GeometryEntry('check_valve', name, 'A_eff_forward_max_mm2', area_m2 * cd_forward * 1.0e6, 'mm²', 'Rückschlagventilgeometrie: maximale effektive Vorwärtsfläche.'),
                GeometryEntry('check_valve', name, 'A_eff_reverse_max_mm2', area_m2 * cd_reverse * 1.0e6, 'mm²', 'Rückschlagventilgeometrie: maximale effektive Rückwärtsfläche.'),
                GeometryEntry('check_valve', name, 'cracking_pressure_bar', cracking_pressure_bar, 'bar', 'Rückschlagventilgeometrie: Öffnungsdruckdifferenz (cracking pressure).'),
            ])
    return entries



def _format_geometry_value(value: float) -> str:
    if math.isfinite(float(value)):
        abs_value = abs(float(value))
        if 0.0 < abs_value < 10.0:
            return f"{float(value):.3f}".rstrip('0').rstrip('.')
        return f"{float(value):.1f}"
    return str(value)


def _equivalent_diameter_mm_from_area_mm2(area_mm2: float) -> float:
    area_mm2 = max(float(area_mm2), 0.0)
    if area_mm2 <= 0.0:
        return 0.0
    return math.sqrt(4.0 * area_mm2 / math.pi)


def _build_free_piston_scavenging_markdown(bundle) -> str:
    fp = getattr(bundle, 'free_piston', None)
    if fp is None or not bool(getattr(fp, 'scavenging_enabled', False)):
        return ""
    lines = [
        "# 0D-Spuelmodell",
        "",
        "Aktiviertes Modell: `overlap_short_circuit_0d`.",
        "",
        "Das Modell wirkt nur waehrend Slot-Overlap: Transfermasse stroemt in den Zylinder, waehrend gleichzeitig Zylindermasse ueber den Auslassslot ausstroemt. Gesamtmasse und Energie bleiben aus der normalen de-Saint-Venant-Wantzel-Stroemung unveraendert; korrigiert wird nur die Aufteilung von Luft- und verbrannter Restgasmasse im Zylinder/Auslass-Stofftransport.",
        "",
        "Formeln:",
        "- `R = mdot_transfer_in / max(mdot_exhaust_out, eps)`",
        "- `eta_scav = min(max_trapping_efficiency, 1 - exp(-scavenging_factor * R))`",
        "- `short = max_short_circuit_fraction * smoothstep((R - short_circuit_start_ratio) / short_circuit_slope)`",
        "- `burned_correction = scavenged_extra_burned_rate - short_circuit_air_rate`",
        "",
        "Vorzeichen der Diagnose `cylinder_scavenging_burned_correction_kg_per_s`: positiv bedeutet, der Auslassstrom wird restgasreicher als im perfekt gemischten 0D-Grundmodell; negativ bedeutet, der Frischgas-Kurzschlussanteil dominiert.",
        "",
        "Wichtige Exportspalten:",
        "- `cylinder_scavenging_transfer_in_kg_per_s`",
        "- `cylinder_scavenging_exhaust_out_kg_per_s`",
        "- `cylinder_scavenging_burned_correction_kg_per_s`",
        "- `cylinder_scavenging_short_circuit_fraction`",
        "- `cylinder_scavenging_efficiency_0to1`",
    ]
    return "\n".join(lines)


def _build_free_piston_results_signal_markdown(bundle) -> str:
    if getattr(bundle, 'architecture', 'classic') != 'free_piston':
        return ""
    lines = [
        "# Free-Piston Ergebnis-Auswertung",
        "",
        "Die Arbeitszylinder-Signale werden zylinderweise ausgegeben. In Free-Piston-Varianten wie V11/V12/V13 sind die Praefixe normalerweise:",
        "",
        "- `cylinder_1_...` fuer Arbeitszylinder 1",
        "- `cylinder_2_...` fuer Arbeitszylinder 2",
        "",
        "## Zugefuehrte Energie",
        "",
        "| Signal Arbeitszylinder 1 | Signal Arbeitszylinder 2 | Bedeutung |",
        "|---|---|---|",
        "| `cylinder_1_added_energy_W` | `cylinder_2_added_energy_W` | Momentane zugefuehrte Leistung durch Verbrennung. Das ist ein Leistungswert in W, kein Zyklusintegral. |",
        "| `cylinder_1_added_energy_cycle_J` | `cylinder_2_added_energy_cycle_J` | Ueber den Zyklus integrierte zugefuehrte Energie. Dieses Signal ist fuer den direkten Energievergleich besser geeignet. |",
        "| `cylinder_1_indicated_power_W` | `cylinder_2_indicated_power_W` | Innere/indizierte Leistung aus kumulierter pV-Arbeit und bisheriger Zykluszeit. Am Zyklusende entspricht sie der mittleren inneren Leistung des Arbeitsspiels. |",
        "| `cylinder_1_combustion_air_mass_latched_kg` | `cylinder_2_combustion_air_mass_latched_kg` | Beim Schlitzschluss gelatchte Luftmasse. Bei `fueling_mode: lambda_from_cylinder_mass_at_slot_close` bestimmt sie die Kraftstoffmasse. |",
        "| `cylinder_1_combustion_fuel_mass_latched_kg` | `cylinder_2_combustion_fuel_mass_latched_kg` | Aus gelatchter Luftmasse und Ziel-Lambda berechnete Kraftstoffmasse. |",
        "| `cylinder_1_combustion_energy_latched_J` | `cylinder_2_combustion_energy_latched_J` | Aus gelatchter Kraftstoffmasse, Heizwert und Verbrennungswirkungsgrad berechnete Energie pro Arbeitsspiel. |",
        "| `cylinder_1_lambda` | `cylinder_2_lambda` | Lambda bezogen auf die gelatchte Luft- und Kraftstoffmasse. |",
        "| `cylinder_1_slot_area_sum_m2` | `cylinder_2_slot_area_sum_m2` | Summe der fuer diesen Zylinder betrachteten Schlitzflaechen beim Latch-Replay. |",
        "",
        "Bei Slot-Close-Lambda gilt naeherungsweise:",
        "",
        "```text",
        "m_fuel = m_air_latched / (lambda_target * AFR_stoich)",
        "Q_zu   = m_fuel * LHV * eta_comb",
        "```",
        "",
        "Grosse Unterschiede in `cylinder_1_added_energy_W` und `cylinder_2_added_energy_W` koennen zwei Ursachen haben: unterschiedliche gelatchte Energie (`*_combustion_energy_latched_J`) oder aehnliche gelatchte Energie mit unterschiedlicher zeitlicher Waermefreisetzung.",
        "",
        "## Brennbeginn",
        "",
        "Die wichtigsten Werte bei Brennbeginn werden aus den bestehenden Zeitreihen an der ersten Zeile mit aktiver Verbrennung bestimmt. Bevorzugt wird `*_combustion_active_0to1 > 0`, alternativ der erste positive Wert von `*_added_energy_W`.",
        "",
        "| Auswertung Arbeitszylinder 1 | Auswertung Arbeitszylinder 2 | Quelle |",
        "|---|---|---|",
        "| Druck bei Brennbeginn | Druck bei Brennbeginn | `cylinder_1_p_Pa` bzw. `cylinder_2_p_Pa` an der Brennbeginn-Zeile. Fuer Anzeige in bar: Wert durch `1.0e5` teilen. |",
        "| Temperatur bei Brennbeginn | Temperatur bei Brennbeginn | `cylinder_1_T_K` bzw. `cylinder_2_T_K` an der Brennbeginn-Zeile. |",
        "| Zeitpunkt Brennbeginn | Zeitpunkt Brennbeginn | `t_s` an der Brennbeginn-Zeile. |",
        "| Kolbenweg bei Brennbeginn | Kolbenweg bei Brennbeginn | `cylinder_1_piston_distance_from_tdc_m` bzw. `cylinder_2_piston_distance_from_tdc_m` an der Brennbeginn-Zeile. |",
        "",
        "## Innere Leistung",
        "",
        "Die innere Leistung wird aus der pV-Arbeit berechnet:",
        "",
        "```text",
        "P_i,1 = cylinder_1_piston_work_cycle_J / (t_s - t_cycle_start_s)",
        "P_i,2 = cylinder_2_piston_work_cycle_J / (t_s - t_cycle_start_s)",
        "P_i,total = P_i,1 + P_i,2",
        "```",
        "",
        "| Signal Arbeitszylinder 1 | Signal Arbeitszylinder 2 | Bedeutung |",
        "|---|---|---|",
        "| `cylinder_1_indicated_power_W` | `cylinder_2_indicated_power_W` | Mittlere innere Leistung innerhalb des laufenden Zyklus. Fuer einen stabilen Vergleich den Wert am Ende eines vollstaendigen Zyklus verwenden. |",
        "| `cylinder_1_piston_work_cycle_J` | `cylinder_2_piston_work_cycle_J` | Kumulierte pV-Arbeit des laufenden Zyklus. |",
        "",
        "## Weitere Arbeitszylinder-Signale",
        "",
        "| Muster fuer Arbeitszylinder 1/2 | Bedeutung |",
        "|---|---|",
        "| `cylinder_1_m_kg`, `cylinder_2_m_kg` | Gasmasse im Arbeitszylinder. |",
        "| `cylinder_1_U_J`, `cylinder_2_U_J` | Innere Energie. |",
        "| `cylinder_1_m_air_kg`, `cylinder_2_m_air_kg` | Luftmasse. |",
        "| `cylinder_1_m_fuel_liquid_kg`, `cylinder_2_m_fuel_liquid_kg` | Fluessige Kraftstoffmasse. |",
        "| `cylinder_1_m_fuel_vapor_kg`, `cylinder_2_m_fuel_vapor_kg` | Kraftstoffdampfmasse. |",
        "| `cylinder_1_m_fuel_total_kg`, `cylinder_2_m_fuel_total_kg` | Summe aus fluessigem Kraftstoff und Kraftstoffdampf. |",
        "| `cylinder_1_m_burned_kg`, `cylinder_2_m_burned_kg` | Verbrannte Masse. |",
        "| `cylinder_1_m_unburned_kg`, `cylinder_2_m_unburned_kg` | Unverbrannte Masse. |",
        "| `cylinder_1_burned_fraction_0to1`, `cylinder_2_burned_fraction_0to1` | Verbrannter Anteil. |",
        "| `cylinder_1_p_Pa`, `cylinder_2_p_Pa` | Druck. |",
        "| `cylinder_1_T_K`, `cylinder_2_T_K` | Temperatur. |",
        "| `cylinder_1_V_m3`, `cylinder_2_V_m3` | Volumen. |",
        "| `cylinder_1_piston_distance_from_tdc_m`, `cylinder_2_piston_distance_from_tdc_m` | Abstand vom lokalen OT. |",
        "| `cylinder_1_piston_v_m_per_s`, `cylinder_2_piston_v_m_per_s` | Lokale Kolbengeschwindigkeit. |",
        "| `cylinder_1_mdot_in_kg_per_s`, `cylinder_2_mdot_in_kg_per_s` | Einlaufender Massenstrom. |",
        "| `cylinder_1_mdot_out_kg_per_s`, `cylinder_2_mdot_out_kg_per_s` | Auslaufender Massenstrom. |",
        "| `cylinder_1_wall_heat_W`, `cylinder_2_wall_heat_W` | Wandwaermestrom. |",
        "| `cylinder_1_piston_work_W`, `cylinder_2_piston_work_W` | p-dV-Leistung am Kolben. |",
        "| `cylinder_1_piston_work_cycle_J`, `cylinder_2_piston_work_cycle_J` | Zyklusintegral der Kolbenarbeit. |",
        "| `cylinder_1_indicated_power_W`, `cylinder_2_indicated_power_W` | Innere/indizierte Leistung aus pV-Arbeit pro Zykluszeit. |",
        "| `cylinder_1_scavenging_transfer_in_kg_per_s`, `cylinder_2_scavenging_transfer_in_kg_per_s` | Spuel-Massenstrom in den Arbeitszylinder. |",
        "| `cylinder_1_scavenging_exhaust_out_kg_per_s`, `cylinder_2_scavenging_exhaust_out_kg_per_s` | Abgas-/Spuel-Massenstrom aus dem Arbeitszylinder. |",
        "| `cylinder_1_scavenging_efficiency_0to1`, `cylinder_2_scavenging_efficiency_0to1` | Spuelwirkungsgrad. |",
    ]
    return "\n".join(lines)


def build_geometry_markdown(bundle, rows: list[dict[str, float | int]] | None = None, title: str = "Geometrie-Übersicht") -> str:
    entries = build_geometry_entries(bundle)
    lines = [_complete_cycle_markdown(bundle, rows)]

    last_cycle_section = build_last_cycle_markdown(bundle, rows)
    if last_cycle_section:
        lines.append("")
        lines.append(last_cycle_section)
    wall_temperature_section = _build_wall_temperature_markdown(bundle, rows)
    if wall_temperature_section:
        lines.append("")
        lines.append(wall_temperature_section)
    energy_balance_section = _build_energy_balance_markdown(bundle, rows)
    if energy_balance_section:
        lines.append("")
        lines.append(energy_balance_section)

    lines.extend(["", f"# {title}", "", "| Kategorie | Name | Größe | Wert | Einheit |", "|---|---|---|---:|---|"])
    for entry in entries:
        value = _format_geometry_value(float(entry.value))
        lines.append(f"| {entry.category} | {entry.entity_name} | {entry.metric_name} | {value} | {entry.unit} |")
        if entry.unit == 'mm²':
            equiv_diameter_mm = _equivalent_diameter_mm_from_area_mm2(float(entry.value))
            lines.append(
                f"| {entry.category} | {entry.entity_name} | {entry.metric_name}_equiv_diameter_mm | {_format_geometry_value(equiv_diameter_mm)} | mm |"
            )
    lines.append("")
    lines.append("Einheiten:")
    lines.append("- Volumen: cm³")
    lines.append("- Längen: mm")
    lines.append("- Flächen: mm²")
    lines.append("- Drücke: bar")
    scavenging_section = _build_free_piston_scavenging_markdown(bundle)
    if scavenging_section:
        lines.append("")
        lines.append(scavenging_section)
    results_signal_section = _build_free_piston_results_signal_markdown(bundle)
    if results_signal_section:
        lines.append("")
        lines.append(results_signal_section)
    return "\n".join(lines)


def write_geometry_readme(bundle, output_dir: str | Path, filename: str = 'README.md', rows: list[dict[str, float | int]] | None = None) -> Path:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    out_path.write_text(build_geometry_markdown(bundle, rows=rows), encoding='utf-8')
    return out_path
