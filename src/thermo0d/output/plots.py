from __future__ import annotations

import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import imageio

from thermo0d.config.constants import ConnCol, ConnectionType, KinCol, VolumeCol, VolumeType
from thermo0d.physics.flow import de_st_venant_wantzel_signed
from thermo0d.physics.kinematics import cylinder_kinematic_state_with_global_from_time
from thermo0d.physics.quellen_props import properties_from_mass_energy_components_quellen
from thermo0d.physics.openings import evaluate_orifice_area, evaluate_slot_state, evaluate_valve_state


def build_batch_plot_path(config_path: str | Path, project_root: str | Path) -> str:
    cfg = Path(config_path)
    out_dir = Path(project_root).resolve() / 'test_cases' / 'plots'
    out_dir.mkdir(parents=True, exist_ok=True)
    return str((out_dir / f"{cfg.stem}_last_cycle_pressure_mdot.png").resolve())


def _connection_flow_quantities_for_step(
    bundle,
    conn_idx: int,
    pressure_by_vol: np.ndarray,
    temperature_by_vol: np.ndarray,
    theta_local_deg_by_vol: np.ndarray,
    theta_global_deg_by_vol: np.ndarray,
    cycle_deg_by_vol: np.ndarray,
    cylinder_travel_by_vol: np.ndarray,
    gas_constant_by_vol: np.ndarray,
    kappa_by_vol: np.ndarray,
) -> tuple[float, float, float]:
    conn = bundle.conn_matrix[conn_idx]
    left = int(conn[ConnCol.FROM_VOL])
    right = int(conn[ConnCol.TO_VOL])
    conn_type = int(conn[ConnCol.TYPE])
    cyl_idx = left if int(bundle.vol_matrix[left, VolumeCol.TYPE]) == VolumeType.CYLINDER else right
    geom_area_m2 = 0.0
    cd_forward = 0.0
    cd_reverse = 0.0
    a_eff_forward = 0.0
    a_eff_reverse = 0.0
    if conn_type == ConnectionType.VALVE:
        if int(bundle.vol_matrix[cyl_idx, VolumeCol.TYPE]) != VolumeType.CYLINDER:
            return 0.0, 0.0, 0.0
        _, bore_area_m2, area_forward_m2, area_reverse_m2, alpha_forward, alpha_reverse = evaluate_valve_state(
            conn,
            theta_local_deg_by_vol[cyl_idx],
            theta_global_deg_by_vol[cyl_idx],
            cycle_deg_by_vol[cyl_idx],
            bundle.lift_table,
            bundle.alpha_table,
        )
        geom_area_m2 = float(bore_area_m2)
        cd_forward = float(alpha_forward)
        cd_reverse = float(alpha_reverse)
        a_eff_forward = float(area_forward_m2)
        a_eff_reverse = float(area_reverse_m2)
    elif conn_type == ConnectionType.SLOT:
        if int(bundle.vol_matrix[cyl_idx, VolumeCol.TYPE]) != VolumeType.CYLINDER:
            return 0.0, 0.0, 0.0
        _, geom_area_m2, area_forward_m2, area_reverse_m2, cd_forward, cd_reverse = evaluate_slot_state(
            conn,
            cylinder_travel_by_vol[cyl_idx],
            bundle.cd_table,
        )
        geom_area_m2 = float(geom_area_m2)
        cd_forward = float(cd_forward)
        cd_reverse = float(cd_reverse)
        a_eff_forward = float(area_forward_m2)
        a_eff_reverse = float(area_reverse_m2)
    elif conn_type == ConnectionType.ORIFICE:
        geom_area_m2, cd_forward, cd_reverse = evaluate_orifice_area(conn)
        geom_area_m2 = float(geom_area_m2)
        cd_forward = float(cd_forward)
        cd_reverse = float(cd_reverse)
        a_eff_forward = float(geom_area_m2 * cd_forward)
        a_eff_reverse = float(geom_area_m2 * cd_reverse)
    else:
        return 0.0, 0.0, 0.0
    if pressure_by_vol[left] >= pressure_by_vol[right]:
        kappa = float(kappa_by_vol[left])
        gas_constant = float(gas_constant_by_vol[left])
    else:
        kappa = float(kappa_by_vol[right])
        gas_constant = float(gas_constant_by_vol[right])
    mdot = float(de_st_venant_wantzel_signed(
        pressure_by_vol[left],
        temperature_by_vol[left],
        pressure_by_vol[right],
        temperature_by_vol[right],
        geom_area_m2,
        cd_forward,
        cd_reverse,
        kappa,
        gas_constant,
    ))
    return mdot, a_eff_forward, a_eff_reverse


def write_last_cycle_pressure_plot(bundle, t: np.ndarray, y: np.ndarray, cycle_indices: np.ndarray, output_path: str | Path, run_config_path: str | Path | None = None) -> str:
    output_path = str(Path(output_path).resolve())
    unique_cycles = np.unique(cycle_indices)
    if unique_cycles.size == 0:
        return output_path
    last_cycle = None
    ids = np.empty(0, dtype=np.int64)
    for cyc in unique_cycles[::-1]:
        current_ids = np.where(cycle_indices == int(cyc))[0]
        if current_ids.size >= 2:
            last_cycle = int(cyc)
            ids = current_ids
            break
    if last_cycle is None:
        return output_path

    cv_default = float(bundle.gas_props[1])
    gas_constant_default = float(bundle.gas_props[2])
    kappa_default = float(bundle.gas_props[3])
    use_promo_thermo = bundle.gas_props.shape[0] > 4 and float(bundle.gas_props[4]) >= 0.5
    environment_is_fixed = getattr(bundle, 'environment_is_fixed', None)
    environment_pressures_pa = getattr(bundle, 'environment_pressures_pa', None)
    environment_temperatures_K = getattr(bundle, 'environment_temperatures_K', None)
    fig, ax_p = plt.subplots(figsize=(10.8, 6.1), dpi=150)
    ax_m = ax_p.twinx()
    ax_a = ax_p.twinx()
    ax_a.spines['right'].set_position(('outward', 62))

    n_vol = bundle.vol_matrix.shape[0]
    cyl_connection_map: dict[int, list[int]] = {int(c): [] for c in bundle.cylinder_indices}
    for j in range(bundle.conn_matrix.shape[0]):
        left = int(bundle.conn_matrix[j, ConnCol.FROM_VOL])
        right = int(bundle.conn_matrix[j, ConnCol.TO_VOL])
        if left in cyl_connection_map:
            cyl_connection_map[left].append(j)
        if right in cyl_connection_map and right != left:
            cyl_connection_map[right].append(j)

    for cyl_order, cyl_idx in enumerate(bundle.cylinder_indices):
        name = bundle.volume_names[cyl_idx]
        kin_row = bundle.kin_matrix[int(bundle.vol_matrix[cyl_idx, VolumeCol.KIN_ROW])]
        theta_list = []
        pressure_bar_list = []
        mdot_in_list = []
        mdot_out_list = []
        aeff_in_list = []
        aeff_out_list = []
        for k in ids:
            tk = float(t[k])
            pressure_by_vol = np.zeros(n_vol, dtype=np.float64)
            temperature_by_vol = np.full(n_vol, 300.0, dtype=np.float64)
            gas_constant_by_vol = np.full(n_vol, gas_constant_default, dtype=np.float64)
            kappa_by_vol = np.full(n_vol, kappa_default, dtype=np.float64)
            theta_local_deg_by_vol = np.zeros(n_vol, dtype=np.float64)
            theta_global_deg_by_vol = np.zeros(n_vol, dtype=np.float64)
            cycle_deg_by_vol = np.full(n_vol, bundle.cycle_deg, dtype=np.float64)
            cylinder_travel_by_vol = np.zeros(n_vol, dtype=np.float64)
            state_layout = bundle.state_layout
            for i in range(n_vol):
                mass = float(y[int(state_layout.mass_index(i)), k])
                energy = float(y[int(state_layout.energy_index(i)), k])
                vol_type = int(bundle.vol_matrix[i, VolumeCol.TYPE])
                is_env = bool(environment_is_fixed is not None and int(environment_is_fixed[i]) == 1) or vol_type == VolumeType.ENVIRONMENT
                if is_env:
                    temp = float(environment_temperatures_K[i]) if environment_temperatures_K is not None and float(environment_temperatures_K[i]) > 0.0 else 300.0
                    pressure_by_vol[i] = float(environment_pressures_pa[i]) if environment_pressures_pa is not None and float(environment_pressures_pa[i]) > 0.0 else 101325.0
                    temperature_by_vol[i] = temp
                else:
                    air_mass = float(state_layout.air_mass_from_state(y[:, k], i))
                    burned_mass = float(state_layout.burned_mass_from_state(y[:, k], i))
                    fuel_vapor_mass = float(state_layout.fuel_vapor_mass_from_state(y[:, k], i))
                    if use_promo_thermo:
                        temp, _cp_i, cv_i, gas_constant_i, kappa_i = properties_from_mass_energy_components_quellen(
                            mass,
                            energy,
                            air_mass,
                            fuel_vapor_mass,
                            burned_mass,
                            cv_default,
                        )
                        gas_constant_by_vol[i] = gas_constant_i
                        kappa_by_vol[i] = kappa_i
                    else:
                        cv_i = cv_default
                        gas_constant_i = gas_constant_default
                        temp = energy / (mass * cv_i) if mass > 1.0e-18 else 300.0
                    temperature_by_vol[i] = temp
                    if vol_type == VolumeType.CYLINDER:
                        volume, _dvdt, theta_local_deg, theta_global_deg, piston_x_m, _dtheta_dt, cycle_deg = cylinder_kinematic_state_with_global_from_time(
                            bundle.kin_matrix[int(bundle.vol_matrix[i, VolumeCol.KIN_ROW])],
                            tk,
                        )
                        theta_local_deg_by_vol[i] = theta_local_deg
                        theta_global_deg_by_vol[i] = theta_global_deg
                        cycle_deg_by_vol[i] = cycle_deg
                        cylinder_travel_by_vol[i] = piston_x_m
                        pressure_by_vol[i] = mass * gas_constant_i * temp / volume if volume > 1.0e-18 else 0.0
                    else:
                        volume = float(bundle.vol_matrix[i, VolumeCol.FIXED_VOLUME])
                        pressure_by_vol[i] = mass * gas_constant_i * temp / volume if volume > 1.0e-18 else 0.0
            volume, _dvdt, theta_deg, _theta_global_deg, _piston_x, _dtheta_dt, _cycle_deg = cylinder_kinematic_state_with_global_from_time(kin_row, tk)
            temp = temperature_by_vol[cyl_idx]
            mass = float(y[int(bundle.state_layout.mass_index(cyl_idx)), k])
            pressure_pa = mass * float(gas_constant_by_vol[cyl_idx]) * temp / volume if volume > 1.0e-18 else 0.0
            theta_list.append(theta_deg)
            pressure_bar_list.append(pressure_pa / 1.0e5)

            mdot_in = 0.0
            mdot_out = 0.0
            aeff_in = 0.0
            aeff_out = 0.0
            for conn_idx in cyl_connection_map[int(cyl_idx)]:
                conn = bundle.conn_matrix[conn_idx]
                left = int(conn[ConnCol.FROM_VOL])
                right = int(conn[ConnCol.TO_VOL])
                mdot, a_eff_forward, a_eff_reverse = _connection_flow_quantities_for_step(
                    bundle,
                    conn_idx,
                    pressure_by_vol,
                    temperature_by_vol,
                    theta_local_deg_by_vol,
                    theta_global_deg_by_vol,
                    cycle_deg_by_vol,
                    cylinder_travel_by_vol,
                    gas_constant_by_vol,
                    kappa_by_vol,
                )
                if cyl_idx == left:
                    aeff_out += a_eff_forward
                    aeff_in += a_eff_reverse
                    if mdot >= 0.0:
                        mdot_out += mdot
                    else:
                        mdot_in += -mdot
                elif cyl_idx == right:
                    aeff_in += a_eff_forward
                    aeff_out += a_eff_reverse
                    if mdot >= 0.0:
                        mdot_in += mdot
                    else:
                        mdot_out += -mdot
            mdot_in_list.append(mdot_in)
            mdot_out_list.append(-mdot_out)
            aeff_in_list.append(aeff_in)
            aeff_out_list.append(aeff_out)

        theta = np.asarray(theta_list, dtype=np.float64)
        pressure_bar = np.asarray(pressure_bar_list, dtype=np.float64)
        mdot_in = np.asarray(mdot_in_list, dtype=np.float64)
        mdot_out = np.asarray(mdot_out_list, dtype=np.float64)
        aeff_in = np.asarray(aeff_in_list, dtype=np.float64)
        aeff_out = np.asarray(aeff_out_list, dtype=np.float64)
        order = np.argsort(theta)
        ax_p.plot(theta[order], pressure_bar[order], linewidth=2.0, color='black', label=f'{name} p')
        ax_m.plot(theta[order], mdot_in[order], linewidth=1.5, color='lightskyblue', label=f'{name} mdot_in (+)')
        ax_m.plot(theta[order], mdot_out[order], linewidth=1.5, color='darkred', label=f'{name} mdot_out (-)')
        ax_a.plot(theta[order], aeff_in[order] * 1.0e6, linewidth=1.4, color='blue', linestyle=':', label=f'{name} Aeff_in')
        ax_a.plot(theta[order], aeff_out[order] * 1.0e6, linewidth=1.4, color='red', linestyle=':', label=f'{name} Aeff_out')

    ax_p.set_xlabel('Kurbelwinkel [deg]')
    ax_p.set_ylabel('Druck [bar]')
    ax_m.set_ylabel('Massenstrom [kg/s] (+ in, - out)')
    ax_a.set_ylabel('Effektiver Öffnungsquerschnitt [mm²]')

    ax_p.grid(True, alpha=0.35)
    ax_m.axhline(0.0, color='0.3', linewidth=0.9, alpha=0.8)

    handles_p, labels_p = ax_p.get_legend_handles_labels()
    handles_m, labels_m = ax_m.get_legend_handles_labels()
    handles_a, labels_a = ax_a.get_legend_handles_labels()

    ax_p.legend(handles_p + handles_m + handles_a, labels_p + labels_m + labels_a, loc='best', fontsize=7)

    run_config_text = f"Config: {Path(run_config_path).name}" if run_config_path is not None else ""
    plot_config_text = "Plot: built-in free-piston pV plot"

    footer_text = "\n".join(part for part in (run_config_text, plot_config_text) if part)

    if footer_text:
        fig.text(0.995, 0.006, footer_text, ha="right", va="bottom", fontsize=6, color="#666666", alpha=0.9)
    fig.tight_layout(rect=(0.0, 0.02, 1.0, 1.0))
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    plt.close(fig)
    return output_path


def _write_free_piston_last_ut_ot_ut_pv_plot_for_cylinder(
    bundle,
    rows: list[dict[str, float | int]],
    output_path: str | Path,
    cylinder_idx: int,
    run_config_path: str | Path | None = None,
) -> str | None:
    output = Path(output_path).resolve()
    if not rows:
        return None
    cyl_indices = list(getattr(bundle, 'cylinder_indices', []) or [])
    if not cyl_indices:
        return None
    cyl_idx = int(cylinder_idx)
    if cyl_idx not in [int(idx) for idx in cyl_indices]:
        return None
    cyl_name = str(bundle.volume_names[cyl_idx])
    p_key = f"{cyl_name}_p_Pa"
    V_key = f"{cyl_name}_V_m3"
    x_key = f"{cyl_name}_piston_distance_from_tdc_m" if f"{cyl_name}_piston_distance_from_tdc_m" in rows[0] else 'free_piston_distance_from_tdc_m'
    v_key = f"{cyl_name}_piston_v_m_per_s" if f"{cyl_name}_piston_v_m_per_s" in rows[0] else 'free_piston_v_m_per_s'
    if any(key not in rows[0] for key in (p_key, V_key, x_key, v_key)):
        return None

    def _arr(key: str) -> np.ndarray:
        values: list[float] = []
        for row in rows:
            try:
                values.append(float(row.get(key, np.nan)))
            except Exception:
                values.append(np.nan)
        return np.asarray(values, dtype=np.float64)

    p_pa = _arr(p_key)
    V_m3 = _arr(V_key)
    x_m = _arr(x_key)
    v_mps = _arr(v_key)
    valid = np.isfinite(p_pa) & np.isfinite(V_m3) & np.isfinite(x_m) & np.isfinite(v_mps)
    if int(np.count_nonzero(valid)) < 5:
        return None
    valid_rows = [row for row, ok in zip(rows, valid) if bool(ok)]
    p_pa = p_pa[valid]
    V_m3 = V_m3[valid]
    x_m = x_m[valid]
    v_mps = v_mps[valid]

    def _optional_arr(keys: list[str]) -> np.ndarray:
        for key in keys:
            if key and any(key in row for row in valid_rows):
                values: list[float] = []
                for row in valid_rows:
                    try:
                        values.append(float(row.get(key, np.nan)))
                    except Exception:
                        values.append(np.nan)
                return np.asarray(values, dtype=np.float64)
        return np.full(p_pa.shape, np.nan, dtype=np.float64)

    def _finite(value: object) -> float | None:
        try:
            out = float(value)
        except Exception:
            return None
        return out if math.isfinite(out) else None

    def _last_finite_value(segment_rows: list[dict[str, float | int]], keys: list[str], *, positive: bool = False) -> float | None:
        for row in reversed(segment_rows):
            for key in keys:
                if not key:
                    continue
                value = _finite(row.get(key))
                if value is not None and (not positive or value > 0.0):
                    return value
        return None

    def _integrate_over_time(values: np.ndarray, time_s: np.ndarray, start: int, stop: int) -> float | None:
        y_vals = values[start:stop + 1]
        t_vals = time_s[start:stop + 1]
        mask = np.isfinite(y_vals) & np.isfinite(t_vals)
        if int(np.count_nonzero(mask)) < 2:
            return None
        return float(np.trapezoid(y_vals[mask], t_vals[mask]))

    def _integrate_abs_over_time(values: np.ndarray | None, time_s: np.ndarray, start: int, stop: int) -> float | None:
        if values is None:
            return None
        y_vals = values[start:stop + 1]
        t_vals = time_s[start:stop + 1]
        mask = np.isfinite(y_vals) & np.isfinite(t_vals)
        if int(np.count_nonzero(mask)) < 2:
            return None
        y_masked = y_vals[mask]
        t_masked = t_vals[mask]
        return float(np.trapezoid(np.abs(y_masked), t_masked))

    def _cycle_window_delta(segment_rows: list[dict[str, float | int]], keys: list[str]) -> float | None:
        if not segment_rows:
            return None
        for key in keys:
            start_value = _finite(segment_rows[0].get(key))
            end_value = _finite(segment_rows[-1].get(key))
            if start_value is not None and end_value is not None:
                return float(end_value - start_value)
        return None

    def _sum_optional_integrals(values_list: list[np.ndarray | None], time_s: np.ndarray, start: int, stop: int) -> float | None:
        total = 0.0
        used = False
        for values in values_list:
            if values is None:
                continue
            value = _integrate_over_time(values, time_s, start, stop)
            if value is None:
                continue
            total += value
            used = True
        return total if used else None

    def _integrate_abs_sum_over_time(values_list: list[np.ndarray | None], time_s: np.ndarray, start: int, stop: int) -> float | None:
        summed: np.ndarray | None = None
        for values in values_list:
            if values is None:
                continue
            segment = values[start:stop + 1]
            summed = segment.astype(np.float64, copy=True) if summed is None else summed + segment
        if summed is None:
            return None
        t_vals = time_s[start:stop + 1]
        mask = np.isfinite(summed) & np.isfinite(t_vals)
        if int(np.count_nonzero(mask)) < 2:
            return None
        return float(np.trapezoid(np.abs(summed[mask]), t_vals[mask]))

    def _sum_optional_cycle_deltas(segment_rows: list[dict[str, float | int]], key_groups: list[list[str]]) -> float | None:
        total = 0.0
        used = False
        for keys in key_groups:
            value = _cycle_window_delta(segment_rows, keys)
            if value is None:
                continue
            total += value
            used = True
        return total if used else None

    def _event_index_from_time_or_integral(
        segment_rows: list[dict[str, float | int]],
        *,
        event_time_keys: list[str],
        integral_keys: list[str],
        t_values_s: np.ndarray,
        segment_start_idx: int,
    ) -> int | None:
        event_time_s: float | None = None
        for row in segment_rows:
            event_time_s = _last_finite_value([row], event_time_keys, positive=True)
            if event_time_s is not None:
                break
        if event_time_s is not None and segment_start_idx < int(t_values_s.shape[0]):
            local_t = t_values_s[segment_start_idx:segment_start_idx + len(segment_rows)]
            mask = np.isfinite(local_t)
            if int(np.count_nonzero(mask)) > 0:
                candidates = np.where(mask)[0]
                best_local = int(candidates[int(np.argmin(np.abs(local_t[mask] - event_time_s)))])
                return int(segment_start_idx + best_local)

        best_idx: int | None = None
        best_value = -1.0
        prev_value: float | None = None
        for local_idx, row in enumerate(segment_rows):
            value = _last_finite_value([row], integral_keys)
            if value is None:
                continue
            value = max(0.0, min(1.0, float(value)))
            if prev_value is not None and prev_value > 0.65 and value < prev_value:
                return int(segment_start_idx + local_idx)
            if value > best_value:
                best_value = value
                best_idx = int(segment_start_idx + local_idx)
            prev_value = value
        if best_idx is not None and best_value > 0.65:
            return best_idx
        return None

    def _format_value(value: float | None, unit: str = "", digits: int = 2) -> str:
        if value is None or not math.isfinite(float(value)):
            return "n/v"
        suffix = f" {unit}" if unit else ""
        abs_value = abs(float(value))
        if 0.0 < abs_value < 0.01 or abs_value >= 10000.0:
            return f"{float(value):.{digits}e}{suffix}"
        return f"{float(value):.{digits}f}{suffix}"

    def _geometric_compression_ratio() -> float | None:
        if getattr(bundle, "architecture", "classic") == "free_piston" and getattr(bundle, "free_piston", None) is not None:
            fp = bundle.free_piston
            vmin = max(float(getattr(fp, "clearance_volume_m3", 0.0) or 0.0), 0.0)
            swept = max(float(getattr(fp, "piston_area_m2", 0.0) or 0.0), 0.0) * max(
                float(getattr(fp, "x_max_m", 0.0) or 0.0) - float(getattr(fp, "x_min_m", 0.0) or 0.0),
                0.0,
            )
            if vmin > 1.0e-18:
                return float((vmin + swept) / vmin)
        for vol_idx in cyl_indices:
            kin_idx = int(bundle.vol_matrix[int(vol_idx), VolumeCol.KIN_ROW])
            if kin_idx >= 0:
                cr = float(bundle.kin_matrix[kin_idx, KinCol.COMPRESSION_RATIO])
                if math.isfinite(cr) and cr > 1.0:
                    return cr
        return None

    def _slot_closure_effective_compression_ratio() -> float | None:
        if getattr(bundle, "architecture", "classic") != "free_piston" or getattr(bundle, "free_piston", None) is None:
            return None
        fp = bundle.free_piston
        cylinder_idx = cyl_idx
        slot_open_distances: list[float] = []
        for conn_idx in range(int(bundle.conn_matrix.shape[0])):
            conn = bundle.conn_matrix[conn_idx]
            if int(conn[ConnCol.TYPE]) != int(ConnectionType.SLOT):
                continue
            left = int(conn[ConnCol.FROM_VOL])
            right = int(conn[ConnCol.TO_VOL])
            if left == cylinder_idx or right == cylinder_idx:
                slot_open_distances.append(float(conn[ConnCol.OPEN_VALUE]))
        if not slot_open_distances:
            return None
        closed_distance = max(0.0, min(min(slot_open_distances), max(float(fp.x_max_m) - float(fp.x_min_m), 0.0)))
        vmin = max(float(fp.clearance_volume_m3), 0.0)
        vmax_closed = vmin + max(float(fp.piston_area_m2), 0.0) * closed_distance
        if vmin <= 1.0e-18 or vmax_closed < vmin:
            return None
        return float(vmax_closed / vmin)

    ut_idx = np.where((v_mps[:-1] > 0.0) & (v_mps[1:] <= 0.0))[0] + 1
    ot_idx = np.where((v_mps[:-1] < 0.0) & (v_mps[1:] >= 0.0))[0] + 1
    if ut_idx.size < 2 or ot_idx.size < 1:
        return None

    ut2 = int(ut_idx[-1])
    earlier_ut = ut_idx[ut_idx < ut2]
    if earlier_ut.size == 0:
        return None
    ut1 = int(earlier_ut[-1])
    ot_between = ot_idx[(ot_idx > ut1) & (ot_idx < ut2)]
    if ot_between.size == 0:
        return None
    ot = int(ot_between[-1])

    seg = slice(ut1, ut2 + 1)
    V_cm3 = V_m3[seg] * 1.0e6
    p_bar = p_pa[seg] / 1.0e5
    segment_rows = valid_rows[ut1:ut2 + 1]

    t_s = _optional_arr(["t_s"])
    added_energy_W = _optional_arr([f"{cyl_name}_added_energy_W", "cylinder_added_energy_W"])
    wall_heat_W = _optional_arr([
        f"{cyl_name}_wall_heat_W",
        f"{cyl_name}_wall_heat_zones_sum_W",
        "cylinder_wall_heat_W",
        "cylinder_wall_heat_zones_sum_W",
    ])
    wall_cylinder_heat_W = _optional_arr([f"{cyl_name}_wall_cylinder_heat_W", "cylinder_wall_cylinder_heat_W"])
    wall_head_heat_W = _optional_arr([f"{cyl_name}_wall_head_heat_W", "cylinder_wall_head_heat_W"])
    wall_piston_heat_W = _optional_arr([f"{cyl_name}_wall_piston_heat_W", "cylinder_wall_piston_heat_W"])
    piston_work_J = float(np.trapezoid(p_pa[seg], V_m3[seg]))
    swept_volume_m3 = float(np.max(V_m3[seg]) - np.min(V_m3[seg]))
    pmi_bar = piston_work_J / swept_volume_m3 / 1.0e5 if swept_volume_m3 > 1.0e-18 else None
    duration_s = None
    if np.isfinite(t_s[ut1]) and np.isfinite(t_s[ut2]) and t_s[ut2] > t_s[ut1]:
        duration_s = float(t_s[ut2] - t_s[ut1])
    frequency_hz = 1.0 / duration_s if duration_s is not None and duration_s > 1.0e-15 else None
    indicated_power_W = piston_work_J / duration_s if duration_s is not None and duration_s > 1.0e-15 else None
    cold_flame_idx = _event_index_from_time_or_integral(
        segment_rows,
        event_time_keys=[f"{cyl_name}_cool_flame_time_s", "cylinder_cool_flame_time_s"],
        integral_keys=[f"{cyl_name}_hcci_cool_ignition_integral_0to1", "cylinder_hcci_cool_ignition_integral_0to1"],
        t_values_s=t_s,
        segment_start_idx=ut1,
    )
    hot_flame_idx = _event_index_from_time_or_integral(
        segment_rows,
        event_time_keys=[f"{cyl_name}_combustion_soc_time_s", "cylinder_combustion_soc_time_s"],
        integral_keys=[f"{cyl_name}_hcci_ignition_integral_0to1", "cylinder_hcci_ignition_integral_0to1"],
        t_values_s=t_s,
        segment_start_idx=ut1,
    )
    added_energy_J = _integrate_over_time(added_energy_W, t_s, ut1, ut2)
    if added_energy_J is None:
        added_energy_J = _cycle_window_delta(segment_rows, [f"{cyl_name}_added_energy_cycle_J", "cylinder_added_energy_cycle_J"])
    if added_energy_J is None:
        added_energy_J = _last_finite_value(segment_rows, [
            f"{cyl_name}_combustion_energy_latched_J",
            "cylinder_combustion_energy_latched_J",
            "free_piston_combustion_energy_latched_J",
        ], positive=True)

    wall_heat_loss_J = _integrate_abs_over_time(wall_heat_W, t_s, ut1, ut2)
    if wall_heat_loss_J is None:
        wall_heat_loss_J = _integrate_abs_sum_over_time(
            [wall_cylinder_heat_W, wall_head_heat_W, wall_piston_heat_W],
            t_s,
            ut1,
            ut2,
        )

    wall_heat_net_J = _integrate_over_time(wall_heat_W, t_s, ut1, ut2)
    if wall_heat_net_J is None or abs(wall_heat_net_J) <= 1.0e-12:
        zone_wall_heat_net_J = _sum_optional_integrals(
            [wall_cylinder_heat_W, wall_head_heat_W, wall_piston_heat_W],
            t_s,
            ut1,
            ut2,
        )
        if zone_wall_heat_net_J is not None:
            wall_heat_net_J = zone_wall_heat_net_J
    if wall_heat_net_J is None:
        wall_heat_net_J = _cycle_window_delta(segment_rows, [
            f"{cyl_name}_wall_heat_cycle_J",
            f"{cyl_name}_wall_heat_zones_sum_cycle_J",
            "cylinder_wall_heat_cycle_J",
            "cylinder_wall_heat_zones_sum_cycle_J",
        ])
    if wall_heat_net_J is None or abs(wall_heat_net_J) <= 1.0e-12:
        zone_wall_heat_net_J = _sum_optional_cycle_deltas(segment_rows, [
            [f"{cyl_name}_wall_cylinder_heat_cycle_J", "cylinder_wall_cylinder_heat_cycle_J"],
            [f"{cyl_name}_wall_head_heat_cycle_J", "cylinder_wall_head_heat_cycle_J"],
            [f"{cyl_name}_wall_piston_heat_cycle_J", "cylinder_wall_piston_heat_cycle_J"],
        ])
        if zone_wall_heat_net_J is not None:
            wall_heat_net_J = zone_wall_heat_net_J
    if wall_heat_loss_J is None and wall_heat_net_J is not None:
        wall_heat_loss_J = abs(wall_heat_net_J)
    lambda_latch_value = _last_finite_value(segment_rows, [
        f"{cyl_name}_lambda",
        "cylinder_lambda",
        "free_piston_combustion_lambda",
    ], positive=True)

    pmax_bar = float(np.max(p_bar)) if p_bar.size else None
    geom_cr = _geometric_compression_ratio()
    eff_cr = _slot_closure_effective_compression_ratio()
    real_cr = float(np.max(V_m3[seg]) / np.min(V_m3[seg])) if np.min(V_m3[seg]) > 1.0e-18 else None
    mass_at_intake_close_mg = None
    air_mass_at_intake_close_mg = None
    burned_mass_at_intake_close_mg = None
    theta_at_intake_close_deg = None
    fp = getattr(bundle, "free_piston", None)
    slot_closed_threshold_m2 = max(float(getattr(fp, "combustion_slot_closed_threshold_m2", 1.0e-9) or 1.0e-9), 0.0)
    for row in segment_rows:
        slot_area_m2 = _last_finite_value([row], [
            f"{cyl_name}_slot_area_sum_m2",
            "cylinder_slot_area_sum_m2",
            "free_piston_slot_area_sum_m2",
        ])
        if slot_area_m2 is None:
            slot_area_mm2 = _last_finite_value([row], [
                f"{cyl_name}_slot_area_sum_mm2",
                "cylinder_slot_area_sum_mm2",
                "free_piston_slot_area_sum_mm2",
            ])
            slot_area_m2 = slot_area_mm2 * 1.0e-6 if slot_area_mm2 is not None else None
        if slot_area_m2 is None or slot_area_m2 > slot_closed_threshold_m2:
            continue
        theta_at_intake_close_deg = _last_finite_value([row], [
            f"{cyl_name}_theta_deg",
            "cylinder_theta_deg",
            "free_piston_crank_angle_deg",
        ])
        cylinder_mass_kg = _last_finite_value([row], [f"{cyl_name}_m_kg", "cylinder_m_kg"])
        if cylinder_mass_kg is not None:
            mass_at_intake_close_mg = cylinder_mass_kg * 1.0e6
        air_mass_kg = _last_finite_value([row], [f"{cyl_name}_m_air_kg", "cylinder_m_air_kg"])
        if air_mass_kg is not None:
            air_mass_at_intake_close_mg = air_mass_kg * 1.0e6
        burned_mass_kg = _last_finite_value([row], [f"{cyl_name}_m_burned_kg", "cylinder_m_burned_kg"])
        if burned_mass_kg is not None:
            burned_mass_at_intake_close_mg = burned_mass_kg * 1.0e6
        break

    restgas_row = None
    for row in segment_rows:
        added = _finite(row.get(f"{cyl_name}_added_energy_W"))
        if added is None:
            added = _finite(row.get("cylinder_added_energy_W"))
        if added is not None and added > 1.0e-12:
            restgas_row = row
            break
    if restgas_row is None and segment_rows:
        restgas_row = segment_rows[min(max(ot - ut1, 0), len(segment_rows) - 1)]
    restgas_percent = None
    burned_percent = None
    lambda_thermo_at_combustion_start = None
    combustion_start_pressure_bar = None
    combustion_start_temperature_K = None
    if restgas_row is not None:
        combustion_start_pressure_Pa = _last_finite_value([restgas_row], [f"{cyl_name}_p_Pa", "cylinder_p_Pa"])
        if combustion_start_pressure_Pa is None:
            combustion_start_pressure_bar = _last_finite_value([restgas_row], [f"{cyl_name}_p_bar", "cylinder_p_bar"])
        else:
            combustion_start_pressure_bar = combustion_start_pressure_Pa * 1.0e-5
        combustion_start_temperature_K = _last_finite_value([restgas_row], [f"{cyl_name}_T_K", "cylinder_T_K"])
        lambda_thermo_at_combustion_start = _last_finite_value([restgas_row], [
            f"{cyl_name}_thermo_lambda",
            "cylinder_thermo_lambda",
        ], positive=True)
        burned_share = _last_finite_value([restgas_row], [f"{cyl_name}_share_burned_0to1", "cylinder_share_burned_0to1"])
        if burned_share is not None:
            burned_percent = 100.0 * max(0.0, min(1.0, burned_share))
            restgas_percent = burned_percent
        else:
            burned_mass = _last_finite_value([restgas_row], [f"{cyl_name}_m_burned_kg", "cylinder_m_burned_kg"])
            total_mass = _last_finite_value([restgas_row], [f"{cyl_name}_m_kg", "cylinder_m_kg"])
            if burned_mass is not None and total_mass is not None and total_mass > 1.0e-18:
                burned_percent = 100.0 * max(0.0, min(1.0, burned_mass / total_mass))
                restgas_percent = burned_percent
    if added_energy_J is not None and math.isfinite(added_energy_J) and added_energy_J > 0:
        wall_heat_pct = f" ({round(wall_heat_loss_J / added_energy_J * 100):.0f}%)" if wall_heat_loss_J is not None and math.isfinite(wall_heat_loss_J) else ""
        piston_work_pct = f" ({round(piston_work_J / added_energy_J * 100):.0f}%)" if piston_work_J is not None and math.isfinite(piston_work_J) else ""
    else:
        wall_heat_pct = ""
        piston_work_pct = ""

    # ... (Zusammenstellung der Textzeilen für den Plot)


    info_text = "\n".join([
        f"Zugef. Energie: {_format_value(added_energy_J, 'J')}",
        f"Wandwaermeverluste: {_format_value(wall_heat_loss_J, 'J')}{wall_heat_pct}",
        f"Kolbenarbeit: {_format_value(piston_work_J, 'J')}{piston_work_pct}",

        f"Druck Brennbeginn: {_format_value(combustion_start_pressure_bar, 'bar')}",
        f"Temperatur Brennbeginn: {_format_value(combustion_start_temperature_K, 'K')}",
        f"Lambda (SOC): {_format_value(lambda_thermo_at_combustion_start, '-', 3)}",
        f"Frequenz: {_format_value(frequency_hz, 'Hz')}",
        f"Innere Leistung: {_format_value(indicated_power_W/1000, 'kW')}",
        f"pmi: {_format_value(pmi_bar, 'bar')}",
        f"pmax: {_format_value(pmax_bar, 'bar')}",
        f"Frischluft Einlassschluss: {_format_value(air_mass_at_intake_close_mg, 'mg')}",
        f"Gesamtmasse Einlassschluss: {_format_value(mass_at_intake_close_mg, 'mg')}",
        f"Verbrannt Einlassschluss: {_format_value(burned_mass_at_intake_close_mg, 'mg')}",
        f"Restgasanteil: {_format_value(restgas_percent, '%', 1)}",

        f"Verdichtung geom.: {_format_value(geom_cr, '-', 1)}",
        f"Verdichtung eff.: {_format_value(eff_cr, '-', 1)}",
        f"Verdichtung real: {_format_value(real_cr, '-', 1)}",
    ])

    fig, ax = plt.subplots(figsize=(8.0, 5.0), dpi=150)
    ax.plot(V_cm3, p_bar, linewidth=2.0)
    ax.scatter([V_m3[ut1] * 1.0e6, V_m3[ot] * 1.0e6, V_m3[ut2] * 1.0e6], [p_pa[ut1] / 1.0e5, p_pa[ot] / 1.0e5, p_pa[ut2] / 1.0e5], s=28.0)
    ax.annotate('UT', (V_m3[ut1] * 1.0e6, p_pa[ut1] / 1.0e5), xytext=(6, 6), textcoords='offset points')
    ax.annotate('OT', (V_m3[ot] * 1.0e6, p_pa[ot] / 1.0e5), xytext=(6, 6), textcoords='offset points')
    ax.annotate('UT', (V_m3[ut2] * 1.0e6, p_pa[ut2] / 1.0e5), xytext=(6, 6), textcoords='offset points')
    if cold_flame_idx is not None and ut1 <= cold_flame_idx <= ut2:
        cf_x = V_m3[cold_flame_idx] * 1.0e6
        cf_y = p_pa[cold_flame_idx] / 1.0e5
        ax.scatter([cf_x], [cf_y], s=42.0, color='#f97316', edgecolors='black', linewidths=0.8, zorder=5)
        ax.annotate('CF ZI=1', (cf_x, cf_y), xytext=(7, -14), textcoords='offset points', color='#c2410c', fontsize=8)
    if hot_flame_idx is not None and ut1 <= hot_flame_idx <= ut2:
        hf_x = V_m3[hot_flame_idx] * 1.0e6
        hf_y = p_pa[hot_flame_idx] / 1.0e5
        ax.scatter([hf_x], [hf_y], s=42.0, color='#dc2626', edgecolors='black', linewidths=0.8, zorder=5)
        ax.annotate('HF ZI=1', (hf_x, hf_y), xytext=(7, 9), textcoords='offset points', color='#b91c1c', fontsize=8)
    ax.set_xlabel('Zylindervolumen [cm³]')
    ax.set_ylabel('Zylinderdruck [bar]')
    ax.set_title(f'{cyl_name}: Druck-Volumen - letzter UT-OT-UT-Zyklus')
    ax.grid(True, alpha=0.35)
    ax.text(
        0.98,
        0.98,
        info_text,
        transform=ax.transAxes,
        ha='right',
        va='top',
        fontsize=7.2,
        linespacing=1.2,
        bbox=dict(boxstyle='square,pad=0.45', facecolor='white', edgecolor='black', linewidth=1.0, alpha=0.96),
    )
    run_config_text = f"Config: {Path(run_config_path).name}" if run_config_path is not None else ""
    plot_config_text = f"Plot: built-in free-piston pV plot | {cyl_name}"
    footer_text = "\n".join(part for part in (run_config_text, plot_config_text) if part)
    if footer_text:
        fig.text(0.995, 0.006, footer_text, ha="right", va="bottom", fontsize=6, color="#666666", alpha=0.9)
    fig.tight_layout(rect=(0.0, 0.02, 1.0, 1.0))
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output)
    plt.close(fig)
    return str(output)


def write_free_piston_last_ut_ot_ut_pv_plot(bundle, rows: list[dict[str, float | int]], output_path: str | Path, run_config_path: str | Path | None = None) -> list[str] | None:
    output = Path(output_path).resolve()
    cyl_indices = [int(idx) for idx in (getattr(bundle, 'cylinder_indices', []) or [])]
    if not cyl_indices:
        return None

    written: list[str] = []
    for order, cyl_idx in enumerate(cyl_indices):
        cyl_name = str(bundle.volume_names[cyl_idx])
        cyl_output = output
        if order > 0:
            cyl_output = output.with_name(f"{output.stem}__{cyl_name}{output.suffix}")
        path = _write_free_piston_last_ut_ot_ut_pv_plot_for_cylinder(
            bundle,
            rows,
            cyl_output,
            cyl_idx,
            run_config_path=run_config_path,
        )
        if path is not None:
            written.append(path)
    return written or None


def write_free_piston_last_ut_ot_ut_species_plot(bundle, rows: list[dict[str, float | int]], output_path: str | Path, run_config_path: str | Path | None = None) -> str | None:
    output = Path(output_path).resolve()
    if not rows:
        return None
    cyl_indices = list(getattr(bundle, 'cylinder_indices', []) or [])
    if not cyl_indices:
        return None
    cyl_name = str(bundle.volume_names[int(cyl_indices[0])])
    x_key = 'free_piston_distance_from_tdc_m'
    v_key = 'free_piston_v_m_per_s'
    if any(key not in rows[0] for key in (x_key, v_key)):
        return None

    def _arr(key: str) -> np.ndarray:
        values: list[float] = []
        for row in rows:
            try:
                values.append(float(row.get(key, np.nan)))
            except Exception:
                values.append(np.nan)
        return np.asarray(values, dtype=np.float64)

    def _arr_first(keys: list[str]) -> np.ndarray:
        for key in keys:
            if key and any(key in row for row in rows):
                return _arr(key)
        return np.full(len(rows), np.nan, dtype=np.float64)

    t_s = _arr('t_s')
    x_m = _arr(x_key)
    v_mps = _arr(v_key)
    q_rad = _arr_first(['free_piston_q', 'cylinder_free_piston_q'])
    fresh_gas_kg = _arr_first([f'{cyl_name}_m_fresh_gas_kg', 'cylinder_m_fresh_gas_kg'])
    if not np.any(np.isfinite(fresh_gas_kg)):
        air_kg = _arr_first([f'{cyl_name}_m_air_kg', 'cylinder_m_air_kg'])
        fuel_vapor_kg = _arr_first([f'{cyl_name}_m_fuel_vapor_kg', 'cylinder_m_fuel_vapor_kg'])
        fresh_gas_kg = air_kg + np.where(np.isfinite(fuel_vapor_kg), fuel_vapor_kg, 0.0)
    burned_kg = _arr_first([f'{cyl_name}_m_burned_kg', 'cylinder_m_burned_kg'])

    valid = np.isfinite(x_m) & np.isfinite(v_mps) & (
        np.isfinite(fresh_gas_kg) | np.isfinite(burned_kg)
    )
    if int(np.count_nonzero(valid)) < 5:
        return None
    t_s = t_s[valid]
    x_m = x_m[valid]
    v_mps = v_mps[valid]
    fresh_gas_kg = fresh_gas_kg[valid]
    burned_kg = burned_kg[valid]
    q_rad = q_rad[valid]

    ut_idx = np.where((v_mps[:-1] > 0.0) & (v_mps[1:] <= 0.0))[0] + 1
    ot_idx = np.where((v_mps[:-1] < 0.0) & (v_mps[1:] >= 0.0))[0] + 1
    if ut_idx.size < 2 or ot_idx.size < 1:
        return None
    ut2 = int(ut_idx[-1])
    earlier_ut = ut_idx[ut_idx < ut2]
    if earlier_ut.size == 0:
        return None
    ut1 = int(earlier_ut[-1])
    ot_between = ot_idx[(ot_idx > ut1) & (ot_idx < ut2)]
    if ot_between.size == 0:
        return None
    ot = int(ot_between[-1])

    seg = slice(ut1, ut2 + 1)
    if np.isfinite(t_s[ut1]) and np.isfinite(t_s[ut2]) and t_s[ut2] > t_s[ut1]:
        x_progress_deg = 360.0 * (t_s[seg] - t_s[ut1]) / (t_s[ut2] - t_s[ut1])
        ot_progress_deg = 360.0 * (t_s[ot] - t_s[ut1]) / (t_s[ut2] - t_s[ut1])
    else:
        x_progress_deg = np.linspace(0.0, 360.0, int(ut2 - ut1 + 1), dtype=np.float64)
        ot_progress_deg = float(x_progress_deg[int(ot - ut1)])

    fig, ax = plt.subplots(figsize=(8.0, 5.0), dpi=150)
    ax.plot(x_progress_deg, fresh_gas_kg[seg] * 1.0e6, linewidth=1.7, color='#175cd3', label='fresh gas')
    ax.plot(x_progress_deg, burned_kg[seg] * 1.0e6, linewidth=1.7, color='#b42318', label='burned total')
    ax.axvline(0.0, color='0.35', linewidth=0.9, linestyle=':')
    ax.axvline(ot_progress_deg, color='0.35', linewidth=0.9, linestyle=':')
    ax.axvline(360.0, color='0.35', linewidth=0.9, linestyle=':')
    ax.text(0.0, 0.98, 'UT', transform=ax.get_xaxis_transform(), ha='left', va='top', fontsize=7)
    ax.text(ot_progress_deg, 0.98, 'OT', transform=ax.get_xaxis_transform(), ha='center', va='top', fontsize=7)
    ax.text(360.0, 0.98, 'UT', transform=ax.get_xaxis_transform(), ha='right', va='top', fontsize=7)
    ax.set_xlim(0.0, 360.0)
    ax.set_xlabel('UT-OT-UT Fortschritt [deg]')
    ax.set_ylabel('Masse im Zylinder [mg]')
    ax.set_title('Frischgas und verbranntes Gas im Zylinder - letzter UT-OT-UT-Zyklus')
    ax.grid(True, alpha=0.35)
    ax.legend(loc='best', fontsize=7)
    run_config_text = f"Config: {Path(run_config_path).name}" if run_config_path is not None else ""
    plot_config_text = "Plot: built-in free-piston last UT-OT-UT species"
    footer_text = "\n".join(part for part in (run_config_text, plot_config_text) if part)
    if footer_text:
        fig.text(0.995, 0.006, footer_text, ha="right", va="bottom", fontsize=6, color="#666666", alpha=0.9)
    fig.tight_layout(rect=(0.0, 0.02, 1.0, 1.0))
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output)
    plt.close(fig)
    return str(output)


def write_free_piston_last_ut_ot_ut_diagnostic_plots(bundle, rows: list[dict[str, float | int]], output_dir: str | Path, prefix: str, run_config_path: str | Path | None = None) -> list[str]:
    """Write diagnostic plots for the final complete UT-OT-UT free-piston cycle."""
    output_dir = Path(output_dir).resolve()
    if not rows:
        return []

    # The diagnostic plots are tied to the free-piston displacement and velocity
    # channels. Without both channels, a reliable UT/OT cycle cannot be detected.
    x_key = 'free_piston_distance_from_tdc_m'
    v_key = 'free_piston_v_m_per_s'
    if any(key not in rows[0] for key in (x_key, v_key)):
        return []

    def _arr(key: str) -> np.ndarray:
        values: list[float] = []
        for row in rows:
            try:
                values.append(float(row.get(key, np.nan)))
            except Exception:
                values.append(np.nan)
        return np.asarray(values, dtype=np.float64)

    def _arr_first(keys: list[str]) -> np.ndarray:
        for key in keys:
            if key and any(key in row for row in rows):
                return _arr(key)
        return np.full(len(rows), np.nan, dtype=np.float64)

    # Convert the row-oriented export data into aligned NumPy arrays and keep
    # only samples with finite piston position and velocity.
    t_s = _arr('t_s')
    x_m = _arr(x_key)
    v_mps = _arr(v_key)
    q_rad = _arr_first(['free_piston_q', 'cylinder_free_piston_q'])
    valid = np.isfinite(x_m) & np.isfinite(v_mps)
    if int(np.count_nonzero(valid)) < 5:
        return []
    t_s = t_s[valid]
    x_m = x_m[valid]
    v_mps = v_mps[valid]
    q_rad = q_rad[valid]

    # UT and OT are identified from velocity sign changes. The last full cycle
    # is the final UT, the previous UT, and the last OT between them.
    ut_idx = np.where((v_mps[:-1] > 0.0) & (v_mps[1:] <= 0.0))[0] + 1
    ot_idx = np.where((v_mps[:-1] < 0.0) & (v_mps[1:] >= 0.0))[0] + 1
    if ut_idx.size < 2 or ot_idx.size < 1:
        return []
    ut2 = int(ut_idx[-1])
    earlier_ut = ut_idx[ut_idx < ut2]
    if earlier_ut.size == 0:
        return []
    ut1 = int(earlier_ut[-1])
    ot_between = ot_idx[(ot_idx > ut1) & (ot_idx < ut2)]
    if ot_between.size == 0:
        return []
    ot = int(ot_between[-1])
    seg = slice(ut1, ut2 + 1)

    fp = getattr(bundle, 'free_piston', None)
    is_rotary = fp is not None and getattr(fp, 'kinematics_type', 'linear') == 'oscillating_rotary'

    # Rotary kinematics can use the simulated oscillation angle directly. Linear
    # kinematics are normalized to a 0..360 degree progress axis for comparability.
    if is_rotary and np.any(np.isfinite(q_rad)):
        q_deg = q_rad * (180.0 / math.pi)
        x_progress_deg = q_deg[seg]
        ot_progress_deg = q_deg[ot]
        ut_start_deg = q_deg[ut1]
        ut_end_deg = q_deg[ut2]
        xlabel = 'Schwingwinkel [deg]'
        xlim_min = min(float(np.min(x_progress_deg)), ot_progress_deg)
        xlim_max = max(float(np.max(x_progress_deg)), ot_progress_deg)
    else:
        if np.isfinite(t_s[ut1]) and np.isfinite(t_s[ut2]) and t_s[ut2] > t_s[ut1]:
            x_progress_deg = 360.0 * (t_s[seg] - t_s[ut1]) / (t_s[ut2] - t_s[ut1])
            ot_progress_deg = 360.0 * (t_s[ot] - t_s[ut1]) / (t_s[ut2] - t_s[ut1])
        else:
            x_progress_deg = np.linspace(0.0, 360.0, int(ut2 - ut1 + 1), dtype=np.float64)
            ot_progress_deg = float(x_progress_deg[int(ot - ut1)])
        ut_start_deg = 0.0
        ut_end_deg = 360.0
        xlabel = 'UT-OT-UT Fortschritt [deg]'
        xlim_min = 0.0
        xlim_max = 360.0

    # Helper for optional channels: use the first available key, slice it to the
    # selected cycle, and apply unit conversion in one place.
    def _series(keys: list[str], scale: float = 1.0, offset: float = 0.0, fallback: np.ndarray | None = None) -> np.ndarray:
        values = _arr_first(keys)[valid]
        if not np.any(np.isfinite(values)) and fallback is not None:
            values = fallback
        return values[seg] * scale + offset

    def _accel() -> np.ndarray:
        # Prefer the exported acceleration channel; fall back to a numerical
        # derivative only when timestamps are usable.
        a = _arr_first(['free_piston_a_m_per_s2'])[valid]
        if np.any(np.isfinite(a)):
            return a
        if not (np.all(np.isfinite(t_s)) and t_s.size >= 2):
            return np.full(t_s.shape, np.nan, dtype=np.float64)
        return np.gradient(v_mps, t_s)

    def _plot_multi_axis(filename: str, title: str, axes: list[dict[str, object]]) -> str | None:
        # Each plot may combine several physical quantities with their own
        # y-axis. Series without enough finite samples are skipped.
        fig, base_ax = plt.subplots(figsize=(9.0, 5.2), dpi=150)
        axis_map: dict[str, object] = {}
        for idx, axis_spec in enumerate(axes):
            if idx == 0:
                ax = base_ax
            else:
                ax = base_ax.twinx()
                ax.spines['right'].set_position(('outward', 58 * (idx - 1)))
            axis_id = str(axis_spec['id'])
            axis_map[axis_id] = ax
            ax.set_ylabel(str(axis_spec.get('ylabel', '')))
            if 'ylim' in axis_spec:
                y_min, y_max = axis_spec['ylim']  # type: ignore[index]
                ax.set_ylim(float(y_min), float(y_max))
        handles = []
        labels = []
        for axis_spec in axes:
            ax = axis_map[str(axis_spec['id'])]
            for item in axis_spec.get('series', []):  # type: ignore[union-attr]
                y_vals = item['values']  # type: ignore[index]
                mask = np.isfinite(x_progress_deg) & np.isfinite(y_vals)
                if int(np.count_nonzero(mask)) < 2:
                    continue
                line = ax.plot(
                    x_progress_deg[mask],
                    y_vals[mask],
                    linewidth=float(item.get('linewidth', 1.35)),  # type: ignore[union-attr]
                    color=str(item.get('color', '#111111')),  # type: ignore[union-attr]
                    linestyle=str(item.get('linestyle', '-')),  # type: ignore[union-attr]
                    label=str(item.get('label', '')),  # type: ignore[union-attr]
                )[0]
                handles.append(line)
                labels.append(str(item.get('label', '')))  # type: ignore[union-attr]
        if not handles:
            plt.close(fig)
            return None
        base_ax.axvline(ut_start_deg, color='0.35', linewidth=0.9, linestyle=':')
        base_ax.axvline(ot_progress_deg, color='0.35', linewidth=0.9, linestyle=':')
        if not is_rotary:
            base_ax.axvline(ut_end_deg, color='0.35', linewidth=0.9, linestyle=':')
        base_ax.text(ut_start_deg, 0.98, 'UT', transform=base_ax.get_xaxis_transform(), ha='left' if not is_rotary else 'center', va='top', fontsize=7)
        base_ax.text(ot_progress_deg, 0.98, 'OT', transform=base_ax.get_xaxis_transform(), ha='center', va='top', fontsize=7)
        if not is_rotary:
            base_ax.text(ut_end_deg, 0.98, 'UT', transform=base_ax.get_xaxis_transform(), ha='right', va='top', fontsize=7)
        base_ax.set_xlim(xlim_min, xlim_max)
        base_ax.set_xlabel(xlabel)
        base_ax.set_title(title)
        base_ax.grid(True, alpha=0.35)
        base_ax.legend(handles, labels, loc='best', fontsize=7)
        run_config_text = f"Config: {Path(run_config_path).name}" if run_config_path is not None else ""
        plot_config_text = "Plot: built-in free-piston last UT-OT-UT diagnostic"
        footer_text = "\n".join(part for part in (run_config_text, plot_config_text) if part)
        if footer_text:
            fig.text(0.995, 0.006, footer_text, ha="right", va="bottom", fontsize=6, color="#666666", alpha=0.9)
        fig.tight_layout(rect=(0.0, 0.02, 1.0, 1.0))
        path = output_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path)
        plt.close(fig)
        return str(path)

    # Frequently reused diagnostic channels. Unit conversions are applied here
    # so the plot specifications below remain mostly declarative.
    piston_mm = _series(['free_piston_x_m'], scale=-1000.0, offset=54.04, fallback=x_m)
    transfer_mdot = _series(['transfer_slot_mdot_kg_per_s'])
    exhaust_mdot = _series(['exhaust_slot_mdot_kg_per_s'])
    transfer_area = _series(['transfer_slot_open_area_m2', 'transfer_slot_A_eff_forward_m2', 'cylinder_A_eff_in_m2'], scale=1.0e6)
    exhaust_area = _series(['exhaust_slot_open_area_m2', 'exhaust_slot_A_eff_forward_m2', 'cylinder_A_eff_out_m2'], scale=1.0e6)
    q_add = _series(['cylinder_added_energy_W'])

    plots: list[tuple[str, str, list[dict[str, object]]]] = [
        (
            f'{prefix}__last_ut_ot_ut_mass_shares.png',
            'Zylinder Massenanteile - letztes Arbeitsspiel',
            [{
                'id': 'share',
                'ylabel': 'Anteil [%]',
                'ylim': (0.0, 100.0),
                'series': [
                    {'values': _series(['cylinder_share_air_0to1'], 100.0), 'label': 'Luft', 'color': '#175cd3'},
                    {'values': _series(['cylinder_share_fuel_vapor_0to1'], 100.0), 'label': 'Kraftstoff gasfoermig', 'color': '#f79009'},
                    {'values': _series(['cylinder_share_fuel_liquid_0to1'], 100.0), 'label': 'Kraftstoff fluessig', 'color': '#12b76a'},
                    {'values': _series(['cylinder_share_burned_0to1'], 100.0), 'label': 'Verbrannt / Restgas', 'color': '#b42318'},
                ],
            }],
        ),
        (
            f'{prefix}__last_ut_ot_ut_energy_overview.png',
            'Kolbenweg, Oeffnungsquerschnitte, Massenstrom, Zugefuehrte Energie - letztes Arbeitsspiel',
            [
                {'id': 'x', 'ylabel': 'Kolbenweg [mm]', 'ylim': (-60.0, 60.0), 'series': [{'values': piston_mm, 'label': 'Kolbenweg', 'color': '#111111'}]},
                {'id': 'mdot', 'ylabel': 'Massenstrom [kg/s]', 'series': [
                    {'values': transfer_mdot, 'label': 'Einströmender Massenstrom', 'color': '#12b76a'},
                    {'values': exhaust_mdot, 'label': 'Ausströmender Massenstrom', 'color': '#f79009'},
                ]},
                {'id': 'q', 'ylabel': 'Qzu [W]', 'series': [{'values': q_add, 'label': 'Zugeführte Energie', 'color': '#ff0000'}]},
                {'id': 'area', 'ylabel': 'A_eff [mm²]', 'series': [
                    {'values': transfer_area, 'label': 'Transfer A_eff', 'color': '#175cd3', 'linestyle': '--'},
                    {'values': exhaust_area, 'label': 'Auslass A_eff', 'color': '#b42318', 'linestyle': '--'},
                ]},
            ],
        ),
        (
            f'{prefix}__last_ut_ot_ut_piston_area_mdot.png',
            'Kolbenweg y1, Oeffnungsquerschnitte y2, Massenstrom y3 - letztes Arbeitsspiel',
            [
                {'id': 'x', 'ylabel': 'Kolbenweg [mm]', 'ylim': (-60.0, 60.0), 'series': [{'values': piston_mm, 'label': 'Kolbenweg', 'color': '#111111'}]},
                {'id': 'area', 'ylabel': 'Freigegebener Öffnungsquerschnitt [mm²]', 'series': [
                    {'values': transfer_area, 'label': 'Transfer Querschnitt', 'color': '#175cd3'},
                    {'values': exhaust_area, 'label': 'Auslass Querschnitt', 'color': '#b42318'},
                ]},
                {'id': 'mdot', 'ylabel': 'Massenstrom [kg/s]', 'series': [
                    {'values': transfer_mdot, 'label': 'Einströmender Massenstrom', 'color': '#12b76a'},
                    {'values': exhaust_mdot, 'label': 'Ausströmender Massenstrom', 'color': '#f79009'},
                ]},
            ],
        ),
        (
            f'{prefix}__last_ut_ot_ut_motion.png',
            'Geschwindigkeit, Beschleunigung und Kolbenweg - letztes Arbeitsspiel',
            [
                {'id': 'v', 'ylabel': 'Geschwindigkeit [m/s]', 'series': [{'values': _series(['free_piston_v_m_per_s'], fallback=v_mps), 'label': 'Geschwindigkeit', 'color': '#175cd3'}]},
                {'id': 'a', 'ylabel': 'Beschleunigung [m/s²]', 'series': [{'values': _series(['free_piston_a_m_per_s2'], fallback=_accel()), 'label': 'Beschleunigung', 'color': '#b42318'}]},
                {'id': 'x', 'ylabel': 'Kolbenweg [mm]', 'ylim': (-60.0, 60.0), 'series': [{'values': piston_mm, 'label': 'Kolbenweg', 'color': '#027a48'}]},
            ],
        ),
        (
            f'{prefix}__last_ut_ot_ut_pressure.png',
            'Pressure - letztes Arbeitsspiel',
            [{
                'id': 'p',
                'ylabel': 'Druck [bar]',
                'series': [
                    {'values': _series(['cylinder_p_Pa', 'cylinder_pressure_Pa'], 1.0e-5), 'label': 'Zylinder', 'color': '#b42318'},
                    {'values': _series(['bounce_p_Pa', 'bounce_pressure_Pa'], 1.0e-5), 'label': 'Bounce', 'color': '#111111'},
                    {'values': _series(['receiver_p_Pa', 'receiver_pressure_Pa'], 1.0e-5), 'label': 'Transfer', 'color': '#0000ff'},
                ],
            }],
        ),
    ]

    written: list[str] = []
    for filename, title, axes in plots:
        path = _plot_multi_axis(filename, title, axes)
        if path is not None:
            written.append(path)
    # Return only plots that actually contain at least one drawable series.
    return written


def export_free_piston_last_ut_ot_ut_frames(
    bundle,
    rows: list[dict[str, float | int]],
    output_dir: str | Path,
    step_deg: float = 1.0,
    axis_min_deg: float = 0.0,
    axis_max_deg: float = 360.0,
    export_video: bool = True,
    video_fps: int = 30,
    run_config_path: str | Path | None = None
) -> list[str]:
    """
    Export individual frames and optional video for the last UT-OT-UT cycle.

    Optimizations:
    - Configurable frame step for performance
    - Lazy loading of data
    - Parallel frame generation if needed
    - Video export with imageio
    - Annotations for UT/OT markers
    """
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not rows:
        return []

    cyl_indices = list(getattr(bundle, 'cylinder_indices', []) or [])
    if not cyl_indices:
        return []

    cyl_name = str(bundle.volume_names[int(cyl_indices[0])])
    p_key = f"{cyl_name}_p_Pa"
    V_key = f"{cyl_name}_V_m3"
    x_key = 'free_piston_distance_from_tdc_m'
    v_key = 'free_piston_v_m_per_s'
    theta_key = f"{cyl_name}_theta_deg"  # Kurbelwinkel

    if any(key not in rows[0] for key in (p_key, V_key, x_key, v_key)):
        return []

    def _arr(key: str) -> np.ndarray:
        values: list[float] = []
        for row in rows:
            try:
                values.append(float(row.get(key, np.nan)))
            except Exception:
                values.append(np.nan)
        return np.asarray(values, dtype=np.float64)

    p_pa = _arr(p_key)
    V_m3 = _arr(V_key)
    x_m = _arr(x_key)
    v_mps = _arr(v_key)
    theta_deg = _arr(theta_key) if theta_key in rows[0] else np.zeros_like(x_m)
    q_rad = _arr('free_piston_q')

    valid = np.isfinite(p_pa) & np.isfinite(V_m3) & np.isfinite(x_m) & np.isfinite(v_mps)
    if int(np.count_nonzero(valid)) < 5:
        return []

    p_pa = p_pa[valid]
    V_m3 = V_m3[valid]
    x_m = x_m[valid]
    v_mps = v_mps[valid]
    theta_deg = theta_deg[valid]
    q_rad = q_rad[valid]

    # Detect UT/OT transitions
    ut_idx = np.where((v_mps[:-1] > 0.0) & (v_mps[1:] <= 0.0))[0] + 1
    ot_idx = np.where((v_mps[:-1] < 0.0) & (v_mps[1:] >= 0.0))[0] + 1

    if ut_idx.size < 2 or ot_idx.size < 1:
        return []

    ut2 = int(ut_idx[-1])
    earlier_ut = ut_idx[ut_idx < ut2]
    if earlier_ut.size == 0:
        return []
    ut1 = int(earlier_ut[-1])
    ot_between = ot_idx[(ot_idx > ut1) & (ot_idx < ut2)]
    if ot_between.size == 0:
        return []
    ot = int(ot_between[-1])

    # Extract last cycle
    seg = slice(ut1, ut2 + 1)
    theta_cycle = theta_deg[seg]
    p_cycle = p_pa[seg]
    V_cycle = V_m3[seg]
    x_cycle = x_m[seg]
    ot_idx_local = ot - ut1  # Local index within cycle

    fp = getattr(bundle, 'free_piston', None)
    is_rotary = fp is not None and getattr(fp, 'kinematics_type', 'linear') == 'oscillating_rotary'

    if is_rotary and np.any(np.isfinite(q_rad[seg])):
        x_axis_cycle = q_rad[seg] * (180.0 / math.pi)
        xlabel = 'Schwingwinkel [°]'
        xlim_min = float(np.min(x_axis_cycle)) - 0.5
        xlim_max = float(np.max(x_axis_cycle)) + 0.5
    else:
        x_axis_cycle = None
        xlabel = 'Kurbelwinkel [°]'
        xlim_min = axis_min_deg - 5
        xlim_max = axis_max_deg + 5

    # Normalize angles to 0-360
    theta_cycle = (theta_cycle - theta_cycle[0]) % 360.0

    # Generate frames at specified step
    angles = np.arange(axis_min_deg, axis_max_deg + step_deg, step_deg)
    angles = angles[angles <= theta_cycle.max()]

    written: list[str] = []
    frame_paths: list[Path] = []

    for frame_idx, angle in enumerate(angles):
        # Interpolate data at this angle
        idx = np.searchsorted(theta_cycle, angle)
        if idx == 0:
            p_val = p_cycle[0]
            V_val = V_cycle[0]
            if x_axis_cycle is not None:
                current_x = x_axis_cycle[0]
        elif idx >= len(theta_cycle):
            p_val = p_cycle[-1]
            V_val = V_cycle[-1]
            if x_axis_cycle is not None:
                current_x = x_axis_cycle[-1]
        else:
            # Linear interpolation with bounds checking
            theta_prev = theta_cycle[idx - 1]
            theta_next = theta_cycle[idx]
            if abs(theta_next - theta_prev) < 1e-9:
                frac = 0.0
            else:
                frac = (angle - theta_prev) / (theta_next - theta_prev)
                frac = np.clip(frac, 0.0, 1.0)
            p_val = p_cycle[idx - 1] + frac * (p_cycle[idx] - p_cycle[idx - 1])
            V_val = V_cycle[idx - 1] + frac * (V_cycle[idx] - V_cycle[idx - 1])
            if x_axis_cycle is not None:
                current_x = x_axis_cycle[idx - 1] + frac * (x_axis_cycle[idx] - x_axis_cycle[idx - 1])

        # Create frame plot with enhanced annotations
        fig, ax = plt.subplots(figsize=(8.0, 5.0), dpi=150)
        x_axis_cycle_plot = x_axis_cycle if x_axis_cycle is not None else theta_cycle
        ax.plot(x_axis_cycle_plot, p_cycle / 1.0e5, linewidth=2.0, label='Druck [bar]', color='#1f77b4')

        if x_axis_cycle is not None:
            angle_label = f'{current_x:.1f}°'
        else:
            current_x = angle
            angle_label = f'{angle:.1f}°'

        ax.axvline(current_x, color='#d62728', linestyle='--', linewidth=2.0, alpha=0.7, label=f'Aktuelle Position: {angle_label}')

        # Mark UT/OT points
        ax.scatter([x_axis_cycle_plot[0], x_axis_cycle_plot[ot_idx_local], x_axis_cycle_plot[-1]],
                   [p_cycle[0] / 1.0e5, p_cycle[ot_idx_local] / 1.0e5, p_cycle[-1] / 1.0e5],
                   s=80, marker='o', color=['#2ca02c', '#ff7f0e', '#2ca02c'], zorder=5, edgecolors='black', linewidth=1.5)

        ax.annotate('UT (Start)', xy=(x_axis_cycle_plot[0], p_cycle[0] / 1.0e5), xytext=(10, 10),
                   textcoords='offset points', fontsize=8, fontweight='bold',
                   bbox=dict(boxstyle='round,pad=0.4', facecolor='#2ca02c', alpha=0.7),
                   arrowprops=dict(arrowstyle='->', lw=1.5))
        ax.annotate('OT', xy=(x_axis_cycle_plot[ot_idx_local], p_cycle[ot_idx_local] / 1.0e5), xytext=(10, -15),
                   textcoords='offset points', fontsize=8, fontweight='bold',
                   bbox=dict(boxstyle='round,pad=0.4', facecolor='#ff7f0e', alpha=0.7),
                   arrowprops=dict(arrowstyle='->', lw=1.5))
        ax.annotate('UT (End)', xy=(x_axis_cycle_plot[-1], p_cycle[-1] / 1.0e5), xytext=(-60, 10),
                   textcoords='offset points', fontsize=8, fontweight='bold',
                   bbox=dict(boxstyle='round,pad=0.4', facecolor='#2ca02c', alpha=0.7),
                   arrowprops=dict(arrowstyle='->', lw=1.5))

        ax.set_xlabel(xlabel, fontsize=10, fontweight='bold')
        ax.set_ylabel('Zylinderdruck [bar]', fontsize=10, fontweight='bold')
        ax.set_xlim(xlim_min, xlim_max)
        ax.grid(True, alpha=0.35, linestyle='--')
        ax.legend(loc='upper left', fontsize=8)
        ax.set_title(f'UT-OT-UT Hub (Frame {frame_idx + 1}/{len(angles)})', fontsize=10, fontweight='bold')

        # Footer with actual values
        run_config_text = f"Config: {Path(run_config_path).name}" if run_config_path is not None else ""
        if x_axis_cycle is not None:
            plot_config_text = f"Schwingwinkel: {current_x:.1f}° | p={p_val/1.0e5:.2f} bar | V={V_val*1.0e6:.2f} cm³"
        else:
            plot_config_text = f"Frame: {angle:.1f}° | p={p_val/1.0e5:.2f} bar | V={V_val*1.0e6:.2f} cm³"
        footer_text = "\n".join(part for part in (run_config_text, plot_config_text) if part)
        if footer_text:
            fig.text(0.995, 0.006, footer_text, ha="right", va="bottom", fontsize=6, color="#666666", alpha=0.9)

        fig.tight_layout(rect=(0.0, 0.02, 1.0, 1.0))

        frame_path = output_dir / f"frame_{frame_idx:04d}_angle_{int(angle):03d}deg.png"
        frame_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(frame_path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        written.append(str(frame_path))
        frame_paths.append(frame_path)

    # Export video if requested
    if export_video and frame_paths:
        video_path = output_dir / "last_cycle_animation.mp4"
        with imageio.get_writer(str(video_path), fps=video_fps) as writer:
            for frame_path in frame_paths:
                image = imageio.imread(str(frame_path))
                writer.append_data(image)
        written.append(str(video_path))

    return written
