from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from thermo0d.config.constants import AngleReference, CombCol, CombDurationMode, ConnCol, ConnectionType, VolumeCol, VolumeType
from thermo0d.physics.flow import de_st_venant_wantzel_signed
from thermo0d.physics.kinematics import cylinder_kinematic_state_from_time
from thermo0d.model.free_piston.forces import compute_load_info
from thermo0d.model.free_piston.geometry import bounce_volume_from_position, cylinder_distance_from_tdc, cylinder_dvdt_from_velocity, cylinder_volume_from_position, free_piston_equivalent_linear_kinematics, free_piston_is_compression_stroke, free_piston_local_cycle_angle_deg, free_piston_local_cycle_angle_rate_deg_s, free_piston_reference_is_active
from thermo0d.model.free_piston.thermo import pressure_from_state, temperature_from_state
try:
    from thermo0d.model.free_piston.combustion_latch import free_piston_combustion_enabled, free_piston_cylinder_uses_latched_fuel, free_piston_uses_slot_closure_lambda, free_piston_uses_vapor_injector, replay_free_piston_combustion_latch_series, replay_free_piston_time_combustion_series
except Exception:  # pragma: no cover - compatibility for project states without latch patch
    free_piston_combustion_enabled = None
    free_piston_cylinder_uses_latched_fuel = None
    free_piston_uses_slot_closure_lambda = None
    free_piston_uses_vapor_injector = None
    replay_free_piston_combustion_latch_series = None
    replay_free_piston_time_combustion_series = None
try:
    from thermo0d.physics.kinematics import global_theta_and_rate_from_time
except ImportError:
    global_theta_and_rate_from_time = None
from thermo0d.physics.combustion import combustion_duration_mode_from_row, vibe_heat_release_rate_with_total_energy, vibe_time_heat_release_rate_with_total_energy
from thermo0d.physics.rhs import _evaluate_check_valve_area, _evaluate_orifice_area, _evaluate_slot_state, _evaluate_valve_state
from thermo0d.physics.source_terms import cylinder_energy_source_terms_from_context
from thermo0d.physics.composition import burned_fraction_0to1, unburned_mass_kg
from thermo0d.physics.quellen_props import default_airlike_lambda, lambda_from_air_and_fuel_mass, properties_from_mass_energy_components_quellen
from thermo0d.core.state_layout import StateLayout



def _call_evaluate_valve_state(conn, theta_local_deg: float, theta_global_deg: float, cycle_deg: float, lift_table, alpha_table):
    target = getattr(_evaluate_valve_state, "py_func", _evaluate_valve_state)
    try:
        argcount = target.__code__.co_argcount
    except Exception:
        argcount = 6
    if argcount >= 6:
        return _evaluate_valve_state(conn, theta_local_deg, theta_global_deg, cycle_deg, lift_table, alpha_table)
    lift_m, bore_area_m2, area_forward_m2, area_reverse_m2, alpha_forward = _evaluate_valve_state(
        conn, theta_local_deg, cycle_deg, lift_table, alpha_table
    )
    alpha_reverse = area_reverse_m2 / bore_area_m2 if bore_area_m2 > 1.0e-18 else 0.0
    return lift_m, bore_area_m2, area_forward_m2, area_reverse_m2, alpha_forward, alpha_reverse


def _stateful_bounce_index(bundle) -> int:
    vol_matrix = getattr(bundle, 'vol_matrix', None)
    if vol_matrix is None:
        return -1
    for i in range(int(vol_matrix.shape[0])):
        if int(vol_matrix[i, VolumeCol.TYPE]) == VolumeType.BOUNCE_CHAMBER:
            return i
    return -1


def _free_piston_local_kinematics(bundle, vol_idx: int, y_arr: np.ndarray, sample_idx: int) -> tuple[float, float]:
    fp = getattr(bundle, 'free_piston', None)
    if fp is None:
        return 0.0, 0.0

    dof = -1
    if getattr(fp, 'volume_mechanical_dof', None) is not None and vol_idx < int(fp.volume_mechanical_dof.shape[0]):
        dof = int(fp.volume_mechanical_dof[vol_idx])

    if dof >= 0 and getattr(fp, 'mechanical_x_state_indices', None) is not None and dof < int(fp.mechanical_x_state_indices.shape[0]):
        x_idx = int(fp.mechanical_x_state_indices[dof])
        v_idx = int(fp.mechanical_v_state_indices[dof])
    else:
        x_idx = int(fp.x_state_index)
        v_idx = int(fp.v_state_index)

    sign = 1.0
    if getattr(fp, 'volume_mechanical_sign', None) is not None and vol_idx < int(fp.volume_mechanical_sign.shape[0]):
        sign = float(fp.volume_mechanical_sign[vol_idx])

    q_m = float(y_arr[x_idx, sample_idx])
    q_v_m_per_s = float(y_arr[v_idx, sample_idx])
    return free_piston_equivalent_linear_kinematics(
        q_m,
        q_v_m_per_s,
        sign,
        kinematics_type=str(getattr(fp, 'kinematics_type', 'linear') or 'linear'),
        x_min_m=float(fp.x_min_m),
        x_max_m=float(fp.x_max_m),
        angle_min_rad=float(getattr(fp, 'rotary_angle_min_rad', 0.0) or 0.0),
        angle_max_rad=float(getattr(fp, 'rotary_angle_max_rad', 0.0) or 0.0),
        effective_radius_m=float(getattr(fp, 'rotary_effective_radius_m', 1.0) or 1.0),
    )


def _prefix_without_trailing_index(name: str) -> str | None:
    head, sep, tail = str(name).rpartition('_')
    if sep and tail.isdigit() and head:
        return head
    return None


def _add_column_prefix_alias(columns: dict[str, np.ndarray], source_prefix: str, alias_prefix: str) -> None:
    source = str(source_prefix)
    alias = str(alias_prefix)
    if not source or not alias or source == alias:
        return
    needle = f'{source}_'
    for key, arr in list(columns.items()):
        if not str(key).startswith(needle):
            continue
        alias_key = f'{alias}_{str(key)[len(needle):]}'
        if alias_key not in columns:
            columns[alias_key] = arr


def _add_single_instance_compat_aliases(columns: dict[str, np.ndarray], bundle) -> None:
    """Temporarily expose legacy singular signal names for one-instance layouts."""
    vol_matrix = getattr(bundle, 'vol_matrix', None)
    volume_names = list(getattr(bundle, 'volume_names', []) or [])
    connection_names = list(getattr(bundle, 'connection_names', []) or [])

    prefix_counts: dict[str, int] = {}
    for name in volume_names + connection_names:
        base = _prefix_without_trailing_index(str(name))
        if base is not None:
            prefix_counts[base] = prefix_counts.get(base, 0) + 1
    for name in volume_names + connection_names:
        base = _prefix_without_trailing_index(str(name))
        if base is not None and prefix_counts.get(base) == 1:
            _add_column_prefix_alias(columns, str(name), base)

    if vol_matrix is None:
        return
    typed_names: dict[int, list[str]] = {}
    for idx, name in enumerate(volume_names):
        if idx >= int(vol_matrix.shape[0]):
            continue
        vol_type = int(vol_matrix[idx, VolumeCol.TYPE])
        typed_names.setdefault(vol_type, []).append(str(name))

    cylinders = typed_names.get(int(VolumeType.CYLINDER), [])
    if len(cylinders) == 1:
        _add_column_prefix_alias(columns, cylinders[0], 'cylinder')

    bounces = typed_names.get(int(VolumeType.BOUNCE_CHAMBER), [])
    if len(bounces) == 1:
        _add_column_prefix_alias(columns, bounces[0], 'bounce')
        source = f'{bounces[0]}_'
        for conn_name in connection_names:
            if str(conn_name).startswith(source):
                _add_column_prefix_alias(columns, str(conn_name), f'bounce_{str(conn_name)[len(source):]}')


def _replay_free_piston_combustion_history(bundle, y_arr: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n_samples = int(y_arr.shape[1]) if y_arr.ndim == 2 else 0
    zeros = np.zeros(n_samples, dtype=np.float64)
    if replay_free_piston_combustion_latch_series is None:
        return zeros.copy(), zeros.copy(), zeros.copy(), zeros.copy()
    try:
        mass_hist, fuel_hist, energy_hist, slot_area_hist = replay_free_piston_combustion_latch_series(bundle, y_arr)
    except Exception:
        return zeros.copy(), zeros.copy(), zeros.copy(), zeros.copy()
    return (
        np.asarray(mass_hist, dtype=np.float64),
        np.asarray(fuel_hist, dtype=np.float64),
        np.asarray(energy_hist, dtype=np.float64),
        np.asarray(slot_area_hist, dtype=np.float64),
    )


def _replay_free_piston_combustion_history_for_cylinder(bundle, y_arr: np.ndarray, cylinder_idx: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n_samples = int(y_arr.shape[1]) if y_arr.ndim == 2 else 0
    zeros = np.zeros(n_samples, dtype=np.float64)
    if replay_free_piston_combustion_latch_series is None:
        return zeros.copy(), zeros.copy(), zeros.copy(), zeros.copy()
    try:
        mass_hist, fuel_hist, energy_hist, slot_area_hist = replay_free_piston_combustion_latch_series(bundle, y_arr, int(cylinder_idx))
    except TypeError:
        if int(cylinder_idx) != int(bundle.cylinder_indices[0]):
            return zeros.copy(), zeros.copy(), zeros.copy(), zeros.copy()
        return _replay_free_piston_combustion_history(bundle, y_arr)
    except Exception:
        return zeros.copy(), zeros.copy(), zeros.copy(), zeros.copy()
    return (
        np.asarray(mass_hist, dtype=np.float64),
        np.asarray(fuel_hist, dtype=np.float64),
        np.asarray(energy_hist, dtype=np.float64),
        np.asarray(slot_area_hist, dtype=np.float64),
    )


def _replay_free_piston_time_combustion_for_cylinder(bundle, t_arr: np.ndarray, y_arr: np.ndarray, latched_energy_hist: np.ndarray | None, cylinder_idx: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n_samples = int(t_arr.shape[0]) if t_arr.ndim == 1 else 0
    zeros = np.zeros(n_samples, dtype=np.float64)
    if replay_free_piston_time_combustion_series is None:
        return zeros.copy(), zeros.copy(), zeros.copy()
    try:
        soc_time_hist, soc_energy_hist, soc_active_hist = replay_free_piston_time_combustion_series(bundle, t_arr, y_arr, latched_energy_hist, int(cylinder_idx))
    except TypeError:
        if int(cylinder_idx) != int(bundle.cylinder_indices[0]):
            return zeros.copy(), zeros.copy(), zeros.copy()
        soc_time_hist, soc_energy_hist, soc_active_hist = replay_free_piston_time_combustion_series(bundle, t_arr, y_arr, latched_energy_hist)
    except Exception:
        return zeros.copy(), zeros.copy(), zeros.copy()
    return (
        np.asarray(soc_time_hist, dtype=np.float64),
        np.asarray(soc_energy_hist, dtype=np.float64),
        np.asarray(soc_active_hist, dtype=np.float64),
    )


def _lambda_from_air_and_fuel(air_mass_kg: float, fuel_mass_kg: float, stoich_afr_kg_air_per_kg_fuel: float) -> float:
    fuel = max(float(fuel_mass_kg), 0.0)
    afr_stoich = max(float(stoich_afr_kg_air_per_kg_fuel), 0.0)
    if fuel <= 1.0e-30 or afr_stoich <= 1.0e-30:
        return 0.0
    return float(max(float(air_mass_kg), 0.0) / (fuel * afr_stoich))


def _smoothstep01(value: float) -> float:
    x = max(0.0, min(1.0, float(value)))
    return x * x * (3.0 - 2.0 * x)


def _scavenging_overlap_diagnostics(fp, cylinder_mass_kg: float, cylinder_air_kg: float, cylinder_burned_kg: float, transfer_in_rate_kg_per_s: float, transfer_air_in_rate_kg_per_s: float, exhaust_out_rate_kg_per_s: float) -> tuple[float, float, float]:
    if fp is None or not bool(getattr(fp, 'scavenging_enabled', False)):
        return 0.0, 0.0, 0.0
    if str(getattr(fp, 'scavenging_model', 'overlap_short_circuit_0d')) != 'overlap_short_circuit_0d':
        return 0.0, 0.0, 0.0
    if cylinder_mass_kg <= 1.0e-18 or transfer_in_rate_kg_per_s <= 1.0e-18 or exhaust_out_rate_kg_per_s <= 1.0e-18:
        return 0.0, 0.0, 0.0
    base_burned_fraction = max(0.0, min(1.0, cylinder_burned_kg / cylinder_mass_kg))
    base_air_fraction = max(0.0, min(1.0 - base_burned_fraction, cylinder_air_kg / cylinder_mass_kg))
    ratio = transfer_in_rate_kg_per_s / max(exhaust_out_rate_kg_per_s, 1.0e-18)
    eta_scav = 1.0 - math.exp(-max(float(getattr(fp, 'scavenging_factor', 1.25)), 0.0) * ratio)
    eta_scav = min(eta_scav, max(float(getattr(fp, 'scavenging_max_trapping_efficiency', 0.92)), 0.0))
    short_x = (ratio - float(getattr(fp, 'scavenging_short_circuit_start_ratio', 0.70))) / max(float(getattr(fp, 'scavenging_short_circuit_slope', 0.35)), 1.0e-12)
    short_fraction = max(float(getattr(fp, 'scavenging_max_short_circuit_fraction', 0.35)), 0.0) * _smoothstep01(short_x)
    if short_fraction > 0.0:
        short_fraction = max(short_fraction, 1.0 - max(float(getattr(fp, 'scavenging_max_trapping_efficiency', 0.92)), 0.0))
    short_fraction = max(0.0, min(1.0, short_fraction))
    normal_exhaust_air_rate = exhaust_out_rate_kg_per_s * base_air_fraction
    normal_exhaust_burned_rate = exhaust_out_rate_kg_per_s * base_burned_fraction
    min_residual_fraction = max(0.0, min(1.0, float(getattr(fp, 'scavenging_min_residual_fraction', 0.03))))
    residual_drive = max(base_burned_fraction - min_residual_fraction, 0.0) / max(1.0 - min_residual_fraction, 1.0e-12)
    scavenged_extra_burned_rate = min(
        eta_scav * (1.0 - short_fraction) * transfer_in_rate_kg_per_s * residual_drive,
        normal_exhaust_air_rate,
        normal_exhaust_burned_rate,
    )
    short_circuit_air_rate = min(
        short_fraction * min(max(transfer_air_in_rate_kg_per_s, 0.0), exhaust_out_rate_kg_per_s),
        normal_exhaust_burned_rate + scavenged_extra_burned_rate,
    )
    return float(scavenged_extra_burned_rate - short_circuit_air_rate), float(short_fraction), float(eta_scav)




def _safe_mass_fraction(component_mass_kg: float, total_mass_kg: float) -> float:
    total = max(float(total_mass_kg), 1.0e-30)
    return float(max(float(component_mass_kg), 0.0) / total)


def _upstream_species_fractions(state_layout: StateLayout, state: np.ndarray, volume_index: int, environment_is_fixed: np.ndarray) -> tuple[float, float]:
    if int(environment_is_fixed[volume_index]) == 1:
        return 0.0, 1.0
    upstream_mass = float(state_layout.gas_mass_from_state(state, volume_index))
    if upstream_mass <= 1.0e-18:
        return 0.0, 0.0
    upstream_burned_mass = float(state_layout.burned_mass_from_state(state, volume_index))
    upstream_air_mass = float(state_layout.air_mass_from_state(state, volume_index))
    burned_fraction = max(0.0, min(1.0, upstream_burned_mass / upstream_mass))
    air_fraction = max(0.0, min(1.0 - burned_fraction, upstream_air_mass / upstream_mass))
    return burned_fraction, air_fraction


@dataclass(slots=True)
class ReconstructedSeries:
    t_s: np.ndarray
    cycle_index: np.ndarray
    theta_deg: np.ndarray
    theta_local_deg: np.ndarray
    columns: dict[str, np.ndarray]

    @property
    def n_samples(self) -> int:
        return int(self.t_s.shape[0])

    def as_columns(self) -> dict[str, np.ndarray]:
        out = {
            't_s': np.asarray(self.t_s),
            'cycle_index': np.asarray(self.cycle_index),
            'theta_deg': np.asarray(self.theta_deg),
            'theta_local_deg': np.asarray(self.theta_local_deg),
        }
        out.update(self.columns)
        return out


class SignalReconstructionService:
    @staticmethod
    def _normalize_cycle_endpoint_theta(theta_deg, t_s, dtheta_dt_deg_s, cycle_deg):
        theta = float(theta_deg)
        cyc = float(cycle_deg)
        if cyc <= 0.0:
            return theta
        theta = theta % cyc
        if theta < 0.0:
            theta += cyc
        if abs(theta) <= 1.0e-9 or abs(theta - cyc) <= 1.0e-9:
            return 0.0
        return theta

    @staticmethod
    def _ensure_float_column(columns: dict[str, np.ndarray], key: str, n_samples: int) -> np.ndarray:
        arr = columns.get(key)
        if arr is None:
            arr = np.zeros(n_samples, dtype=np.float64)
            columns[key] = arr
        return arr

    @staticmethod
    def _ensure_int_column(columns: dict[str, np.ndarray], key: str, n_samples: int) -> np.ndarray:
        arr = columns.get(key)
        if arr is None:
            arr = np.zeros(n_samples, dtype=np.int64)
            columns[key] = arr
        return arr


    @staticmethod
    def _add_burn_window_energy_columns(columns: dict[str, np.ndarray], t_arr: np.ndarray, volume_names: list[str]) -> None:
        n_samples = int(t_arr.shape[0])
        if n_samples <= 0:
            return
        for name in volume_names:
            q_key = f'{name}_added_energy_W'
            q_arr = columns.get(q_key)
            if q_arr is None:
                continue
            q = np.asarray(q_arr, dtype=np.float64)
            if q.shape[0] != n_samples:
                continue
            q_abs_max = float(np.max(np.abs(q))) if q.size else 0.0
            threshold = max(1.0e-9, 1.0e-9 * q_abs_max)
            active_raw = q > threshold
            active = np.asarray(active_raw, dtype=bool).copy()

            # A free-piston burn pulse may cross a velocity reversal where qdot
            # momentarily drops to zero for one or two output samples. Do not split
            # such a pulse into two artificial burn windows in the CSV.
            if n_samples >= 3:
                dt_ref = 0.0
                if n_samples >= 2:
                    dt_vals = np.diff(t_arr)
                    dt_pos = dt_vals[dt_vals > 0.0]
                    if dt_pos.size > 0:
                        dt_ref = float(np.median(dt_pos))
                gap_time_limit = max(0.0, 2.5 * dt_ref) if dt_ref > 0.0 else 0.0
                i = 0
                while i < n_samples:
                    if active[i]:
                        i += 1
                        continue
                    gap_start = i
                    while i < n_samples and not active[i]:
                        i += 1
                    gap_end = i
                    left = gap_start - 1
                    right = gap_end
                    if left < 0 or right >= n_samples:
                        continue
                    if not active[left] or not active[right]:
                        continue
                    gap_dt = max(0.0, float(t_arr[right]) - float(t_arr[left]))
                    q_left = max(float(q[left]), 0.0)
                    q_right = max(float(q[right]), 0.0)
                    q_ratio = min(q_left, q_right) / max(q_left, q_right, 1.0e-18)
                    if gap_end - gap_start <= 2 and (gap_time_limit <= 0.0 or gap_dt <= gap_time_limit) and q_ratio >= 0.5:
                        active[gap_start:gap_end] = True

            active_flag = np.zeros(n_samples, dtype=np.float64)
            window_index = np.zeros(n_samples, dtype=np.int64)
            progress_J = np.zeros(n_samples, dtype=np.float64)
            total_J = np.zeros(n_samples, dtype=np.float64)
            win = 0
            k = 0
            while k < n_samples:
                if not active[k]:
                    k += 1
                    continue
                win += 1
                start = k
                active_flag[k] = 1.0
                window_index[k] = win
                progress_J[k] = 0.0
                k += 1
                while k < n_samples and active[k]:
                    dt = max(0.0, float(t_arr[k]) - float(t_arr[k - 1]))
                    progress_J[k] = progress_J[k - 1] + 0.5 * (max(float(q[k - 1]), 0.0) + max(float(q[k]), 0.0)) * dt
                    active_flag[k] = 1.0
                    window_index[k] = win
                    k += 1
                total_val = float(progress_J[k - 1])
                total_J[start:k] = total_val
            columns[f'{name}_combustion_active_0to1'] = active_flag
            columns[f'{name}_burn_window_index'] = window_index
            columns[f'{name}_released_energy_window_progress_J'] = progress_J
            columns[f'{name}_released_energy_window_J'] = total_J

    @classmethod
    def build(cls, bundle, t: np.ndarray, y: np.ndarray, cycle_indices: np.ndarray) -> ReconstructedSeries:
        cp_default = float(bundle.gas_props[0])
        cv_default = float(bundle.gas_props[1])
        gas_constant_default = float(bundle.gas_props[2])
        kappa_default = float(bundle.gas_props[3])
        use_promo_thermo = bundle.gas_props.shape[0] > 4 and float(bundle.gas_props[4]) >= 0.5
        t_arr = np.asarray(t, dtype=np.float64)
        y_arr = np.asarray(y, dtype=np.float64)
        cycle_idx_arr = np.asarray(cycle_indices, dtype=np.int64)
        n_samples = int(t_arr.shape[0])

        vol_matrix = bundle.vol_matrix
        state_layout = bundle.state_layout if getattr(bundle, "state_layout", None) is not None else StateLayout.classic(int(vol_matrix.shape[0]))
        conn_matrix = bundle.conn_matrix
        kin_matrix = bundle.kin_matrix
        wall_matrix = bundle.wall_matrix
        comb_matrix = bundle.comb_matrix
        evap_matrix = bundle.evap_matrix
        feature_flags = bundle.feature_flags
        volume_names = bundle.volume_names
        connection_names = bundle.connection_names
        lift_table = bundle.lift_table
        alpha_table = bundle.alpha_table
        cd_table = bundle.cd_table
        n_vol = int(vol_matrix.shape[0])
        n_conn = int(conn_matrix.shape[0])
        primary_cyl_idx = int(bundle.cylinder_indices[0]) if getattr(bundle, 'cylinder_indices', None) else -1
        bounce_idx = _stateful_bounce_index(bundle)
        fp = getattr(bundle, 'free_piston', None)
        use_fp_latched_fuel = (
            getattr(bundle, 'architecture', 'classic') == 'free_piston'
            and fp is not None
            and primary_cyl_idx >= 0
            and free_piston_combustion_enabled is not None
            and bool(free_piston_combustion_enabled(bundle))
            and (
                (free_piston_uses_slot_closure_lambda is not None and bool(free_piston_uses_slot_closure_lambda(bundle)))
                or (free_piston_uses_vapor_injector is not None and bool(free_piston_uses_vapor_injector(bundle)))
            )
        )
        latched_air_hist, latched_fuel_hist, latched_energy_hist, slot_area_hist = _replay_free_piston_combustion_history(bundle, y_arr)
        time_vibe_energy_hist = latched_energy_hist if use_fp_latched_fuel else None
        if replay_free_piston_time_combustion_series is not None:
            soc_time_hist, soc_energy_hist, soc_active_hist = replay_free_piston_time_combustion_series(bundle, t_arr, y_arr, time_vibe_energy_hist)
        else:
            soc_time_hist = np.zeros(n_samples, dtype=np.float64)
            soc_energy_hist = np.zeros(n_samples, dtype=np.float64)
            soc_active_hist = np.zeros(n_samples, dtype=np.float64)
        cylinder_latch_histories: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}
        cylinder_soc_histories: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        if use_fp_latched_fuel:
            for cyl_idx in getattr(bundle, 'cylinder_indices', []) or []:
                cyl = int(cyl_idx)
                if free_piston_cylinder_uses_latched_fuel is not None and not bool(free_piston_cylinder_uses_latched_fuel(bundle, cyl)):
                    continue
                latch_hist = _replay_free_piston_combustion_history_for_cylinder(bundle, y_arr, cyl)
                cylinder_latch_histories[cyl] = latch_hist
                cylinder_soc_histories[cyl] = _replay_free_piston_time_combustion_for_cylinder(bundle, t_arr, y_arr, latch_hist[2], cyl)
        environment_is_fixed = getattr(bundle, 'environment_is_fixed', None)
        environment_pressures_pa = getattr(bundle, 'environment_pressures_pa', None)
        environment_temperatures_K = getattr(bundle, 'environment_temperatures_K', None)
        wall_bore_by_vol = getattr(bundle, 'wall_bore_by_vol', None)
        wall_ups_by_vol = getattr(bundle, 'wall_ups_by_vol', None)
        if environment_is_fixed is None:
            environment_is_fixed = np.zeros(n_vol, dtype=np.int64)
        if environment_pressures_pa is None:
            environment_pressures_pa = np.zeros(n_vol, dtype=np.float64)
        if environment_temperatures_K is None:
            environment_temperatures_K = np.zeros(n_vol, dtype=np.float64)
        if wall_bore_by_vol is None:
            wall_bore_by_vol = np.zeros(n_vol, dtype=np.float64)
            for i in range(n_vol):
                if int(vol_matrix[i, VolumeCol.TYPE]) != VolumeType.CYLINDER:
                    continue
                kin_idx = int(vol_matrix[i, VolumeCol.KIN_ROW])
                wall_bore_by_vol[i] = kin_matrix[kin_idx, 1]
        if wall_ups_by_vol is None:
            wall_ups_by_vol = np.zeros(n_vol, dtype=np.float64)
            for i in range(n_vol):
                if int(vol_matrix[i, VolumeCol.TYPE]) != VolumeType.CYLINDER:
                    continue
                kin_idx = int(vol_matrix[i, VolumeCol.KIN_ROW])
                wall_ups_by_vol[i] = 2.0 * kin_matrix[kin_idx, 2] * kin_matrix[kin_idx, 6] / 60.0

        theta_local = np.zeros(n_samples, dtype=np.float64)
        theta_global = np.zeros(n_samples, dtype=np.float64)
        columns: dict[str, np.ndarray] = {}

        piston_x_by_vol = np.zeros(n_vol, dtype=np.float64)
        theta_deg_by_vol = np.zeros(n_vol, dtype=np.float64)
        theta_global_deg_by_vol = np.zeros(n_vol, dtype=np.float64)
        dtheta_local_dt_by_vol = np.zeros(n_vol, dtype=np.float64)
        dtheta_global_dt_by_vol = np.zeros(n_vol, dtype=np.float64)
        cycle_deg_by_vol = np.full(n_vol, 360.0, dtype=np.float64)
        compression_active_by_vol = np.zeros(n_vol, dtype=np.int64)
        pressure_by_vol = np.zeros(n_vol, dtype=np.float64)
        temperature_by_vol = np.full(n_vol, 300.0, dtype=np.float64)
        volume_by_vol = np.zeros(n_vol, dtype=np.float64)
        dvdt_by_vol = np.zeros(n_vol, dtype=np.float64)
        cyl_mdot_in = np.zeros(n_vol, dtype=np.float64)
        cyl_mdot_out = np.zeros(n_vol, dtype=np.float64)
        cyl_enthalpy_in = np.zeros(n_vol, dtype=np.float64)
        cyl_enthalpy_out = np.zeros(n_vol, dtype=np.float64)
        cyl_aeff_in = np.zeros(n_vol, dtype=np.float64)
        cyl_aeff_out = np.zeros(n_vol, dtype=np.float64)
        scav_transfer_in = np.zeros(n_vol, dtype=np.float64)
        scav_transfer_air_in = np.zeros(n_vol, dtype=np.float64)
        scav_exhaust_out = np.zeros(n_vol, dtype=np.float64)
        cp_by_vol = np.full(n_vol, float(cp_default), dtype=np.float64)
        cv_by_vol = np.full(n_vol, float(cv_default), dtype=np.float64)
        gas_constant_by_vol = np.full(n_vol, float(gas_constant_default), dtype=np.float64)
        kappa_by_vol = np.full(n_vol, float(kappa_default), dtype=np.float64)
        lambda_eff_by_vol = np.full(n_vol, default_airlike_lambda(), dtype=np.float64)

        for k, tk in enumerate(t_arr):
            piston_x_by_vol.fill(0.0)
            theta_deg_by_vol.fill(0.0)
            theta_global_deg_by_vol.fill(0.0)
            dtheta_local_dt_by_vol.fill(0.0)
            dtheta_global_dt_by_vol.fill(0.0)
            cycle_deg_by_vol.fill(360.0)
            compression_active_by_vol.fill(0)
            pressure_by_vol.fill(0.0)
            temperature_by_vol.fill(300.0)
            volume_by_vol.fill(0.0)
            dvdt_by_vol.fill(0.0)
            cyl_mdot_in.fill(0.0)
            cyl_mdot_out.fill(0.0)
            cyl_enthalpy_in.fill(0.0)
            cyl_enthalpy_out.fill(0.0)
            cyl_aeff_in.fill(0.0)
            cyl_aeff_out.fill(0.0)
            scav_transfer_in.fill(0.0)
            scav_transfer_air_in.fill(0.0)
            scav_exhaust_out.fill(0.0)
            cp_by_vol.fill(float(cp_default))
            cv_by_vol.fill(float(cv_default))
            gas_constant_by_vol.fill(float(gas_constant_default))
            kappa_by_vol.fill(float(kappa_default))
            lambda_eff_by_vol.fill(default_airlike_lambda())

            theta_local[k] = 0.0
            theta_global[k] = 0.0

            for i in range(n_vol):
                name = volume_names[i]
                state_k = y_arr[:, k]
                mass = float(state_layout.gas_mass_from_state(state_k, i))
                energy = float(y_arr[int(state_layout.energy_index(i)), k])
                burned_mass = float(state_layout.burned_mass_from_state(state_k, i))
                air_mass = float(state_layout.air_mass_from_state(state_k, i))
                liquid_fuel_mass = float(state_layout.liquid_fuel_mass_from_state(state_k, i))
                fuel_vapor_mass = float(state_layout.fuel_vapor_mass_from_state(state_k, i))
                vol_type = int(vol_matrix[i, VolumeCol.TYPE])
                if vol_type == VolumeType.CYLINDER:
                    temp = 300.0
                    kin_idx = int(vol_matrix[i, VolumeCol.KIN_ROW])
                    if getattr(bundle, 'architecture', 'classic') == 'free_piston' and kin_idx < 0 and getattr(bundle, 'free_piston', None) is not None:
                        fp = bundle.free_piston
                        x_idx = int(fp.x_state_index)
                        v_idx = int(fp.v_state_index)
                        piston_q = float(y_arr[x_idx, k])
                        piston_q_dot = float(y_arr[v_idx, k])
                        local_piston_x, local_piston_v = _free_piston_local_kinematics(bundle, i, y_arr, k)
                        piston_x = local_piston_x
                        piston_v = local_piston_v
                        piston_distance_from_tdc = cylinder_distance_from_tdc(local_piston_x, fp.x_min_m, fp.x_max_m)
                        volume = cylinder_volume_from_position(fp.clearance_volume_m3, fp.piston_area_m2, local_piston_x, fp.x_min_m, fp.x_max_m)
                        dvdt = cylinder_dvdt_from_velocity(fp.piston_area_m2, local_piston_v)
                        cycle_deg = float(bundle.cycle_deg)
                        dtheta_global_dt = float(bundle.cycle_deg / bundle.cycle_period_s) if float(bundle.cycle_period_s) > 0.0 else 0.0
                        theta_global_deg = cls._normalize_cycle_endpoint_theta((float(tk) / float(bundle.cycle_period_s)) * float(bundle.cycle_deg), float(tk), float(dtheta_global_dt), float(bundle.cycle_deg))
                        theta_deg = free_piston_local_cycle_angle_deg(local_piston_x, local_piston_v, fp.x_min_m, fp.x_max_m, cycle_deg)
                        dtheta_dt = free_piston_local_cycle_angle_rate_deg_s(local_piston_v, fp.x_min_m, fp.x_max_m, cycle_deg)
                        compression_active_by_vol[i] = 1 if free_piston_is_compression_stroke(local_piston_v, local_piston_x, fp.x_min_m, fp.x_max_m) else 0
                        lambda_air_mass = air_mass
                        lambda_fuel_mass = fuel_vapor_mass
                        if use_fp_latched_fuel and i in cylinder_latch_histories and float(cylinder_latch_histories[i][1][k]) > 0.0:
                            lambda_air_mass = float(cylinder_latch_histories[i][0][k])
                            fuel_mass_eff = float(cylinder_latch_histories[i][1][k])
                            lambda_fuel_mass = fuel_mass_eff
                            afr_eff = float(getattr(fp, "combustion_afr_stoich_kg_air_per_kg_fuel", 14.5) or 14.5)
                        else:
                            fuel_mass_eff = float(bundle.combustion_fuel_mass_by_vol[i]) if getattr(bundle, "combustion_fuel_mass_by_vol", None) is not None and i < int(bundle.combustion_fuel_mass_by_vol.shape[0]) else 0.0
                            afr_eff = float(bundle.combustion_afr_stoich_by_vol[i]) if getattr(bundle, "combustion_afr_stoich_by_vol", None) is not None and i < int(bundle.combustion_afr_stoich_by_vol.shape[0]) else 14.5
                        if use_promo_thermo:
                            lambda_eff = lambda_from_air_and_fuel_mass(lambda_air_mass, lambda_fuel_mass, afr_eff)
                            temp, cp_i, cv_i, gas_constant_i, kappa_i = properties_from_mass_energy_components_quellen(mass, energy, air_mass, fuel_vapor_mass, burned_mass, float(cv_default))
                            pressure = pressure_from_state(mass, energy, volume, gas_constant_i, cv_i)
                            cp_by_vol[i] = cp_i
                            cv_by_vol[i] = cv_i
                            gas_constant_by_vol[i] = gas_constant_i
                            kappa_by_vol[i] = kappa_i
                            lambda_eff_by_vol[i] = lambda_eff
                        else:
                            temp = temperature_from_state(max(mass, 1.0e-30), max(energy, 1.0e-30), float(cv_default))
                            pressure = mass * float(gas_constant_default) * temp / volume if volume > 1.0e-18 else 0.0
                            cp_by_vol[i] = float(cp_default)
                            cv_by_vol[i] = float(cv_default)
                            gas_constant_by_vol[i] = float(gas_constant_default)
                            kappa_by_vol[i] = float(kappa_default)
                            lambda_eff_by_vol[i] = default_airlike_lambda()
                        bounce_volume = bounce_volume_from_position(fp.bounce_chamber_volume0_m3, fp.bounce_area_m2, piston_x, fp.x_min_m, fp.x_max_m)
                        if bounce_idx >= 0:
                            bounce_mass = float(y_arr[int(state_layout.mass_index(bounce_idx)), k])
                            bounce_energy = float(y_arr[int(state_layout.energy_index(bounce_idx)), k])
                            if use_promo_thermo:
                                bounce_air = float(state_layout.air_mass_from_state(y_arr[:, k], bounce_idx))
                                bounce_burned = float(state_layout.burned_mass_from_state(y_arr[:, k], bounce_idx))
                                bounce_fuel_vapor = float(state_layout.fuel_vapor_mass_from_state(y_arr[:, k], bounce_idx))
                                bounce_temp, bounce_cp, bounce_cv, bounce_R, bounce_kappa = properties_from_mass_energy_components_quellen(bounce_mass, bounce_energy, bounce_air, bounce_fuel_vapor, bounce_burned, float(cv_default))
                                bounce_pressure = pressure_from_state(bounce_mass, bounce_energy, bounce_volume, bounce_R, bounce_cv)
                            else:
                                bounce_pressure = pressure_from_state(max(bounce_mass, 1.0e-30), max(bounce_energy, 1.0e-30), bounce_volume, float(gas_constant_default), float(cv_default))
                        else:
                            bounce_pressure = float(fp.bounce_p0_Pa * (fp.bounce_chamber_volume0_m3 / bounce_volume) ** fp.bounce_polytropic_exponent)
                        force_gas = -pressure * fp.piston_area_m2
                        force_bounce = bounce_pressure * fp.bounce_area_m2
                        if abs(piston_v) < 1.0e-15:
                            friction_force = 0.0
                        else:
                            friction_force = -(fp.friction_fc_N * np.copysign(1.0, piston_v) + fp.friction_cv_Ns_per_m * piston_v)
                        load_info = compute_load_info(
                            fp.load_model,
                            fp.load_damping_Ns_per_m,
                            piston_v,
                            x_m=piston_x,
                            x_min_m=fp.x_min_m,
                            x_max_m=fp.x_max_m,
                            max_damping_Ns_per_m=fp.load_max_damping_Ns_per_m,
                            control_zone_m=fp.load_control_zone_m,
                            power_target_W=fp.load_power_target_W,
                            efficiency_0to1=fp.load_efficiency_0to1,
                            min_velocity_m_per_s=fp.load_min_velocity_m_per_s,
                            assist_velocity_threshold_m_per_s=fp.load_assist_velocity_threshold_m_per_s,
                            assist_force_N=fp.load_assist_force_N,
                            target_margin_m=fp.load_target_margin_m,
                            hard_margin_m=fp.load_hard_margin_m,
                            stop_kp=fp.load_stop_kp,
                            moving_mass_kg=fp.moving_mass_kg,
                            max_force_N=fp.load_max_force_N,
                        )
                        load_force_signed = float(load_info.force_signed_N)
                        load_force = -load_force_signed
                        force_net = force_gas + force_bounce + friction_force + load_force
                        if str(getattr(fp, 'kinematics_type', 'linear') or 'linear') == 'oscillating_rotary':
                            radius = max(float(getattr(fp, 'rotary_effective_radius_m', 1.0) or 1.0), 1.0e-18)
                            inertia = max(float(getattr(fp, 'rotary_inertia_kg_m2', fp.moving_mass_kg) or fp.moving_mass_kg), 1.0e-30)
                            equivalent_accel = force_net * radius * radius / inertia
                        else:
                            equivalent_accel = force_net / max(float(fp.moving_mass_kg), 1.0e-30)
                        cls._ensure_float_column(columns, 'free_piston_x_m', n_samples)[k] = piston_x
                        cls._ensure_float_column(columns, 'free_piston_distance_from_tdc_m', n_samples)[k] = cylinder_distance_from_tdc(piston_x, fp.x_min_m, fp.x_max_m)
                        cls._ensure_float_column(columns, 'free_piston_v_m_per_s', n_samples)[k] = piston_v
                        cls._ensure_float_column(columns, 'free_piston_q', n_samples)[k] = piston_q
                        cls._ensure_float_column(columns, 'free_piston_q_dot', n_samples)[k] = piston_q_dot
                        cls._ensure_float_column(columns, 'free_piston_a_m_per_s2', n_samples)[k] = equivalent_accel
                        cls._ensure_float_column(columns, 'bounce_volume_m3', n_samples)[k] = bounce_volume
                        cls._ensure_float_column(columns, 'bounce_pressure_Pa', n_samples)[k] = bounce_pressure
                        cls._ensure_float_column(columns, 'free_piston_F_gas_N', n_samples)[k] = force_gas
                        cls._ensure_float_column(columns, 'free_piston_F_bounce_N', n_samples)[k] = force_bounce
                        cls._ensure_float_column(columns, 'free_piston_F_friction_N', n_samples)[k] = friction_force
                        cls._ensure_float_column(columns, 'free_piston_F_load_N', n_samples)[k] = load_force
                        cls._ensure_float_column(columns, 'free_piston_F_net_N', n_samples)[k] = force_net
                        cls._ensure_float_column(columns, 'free_piston_generator_power_W', n_samples)[k] = float(load_info.mechanical_power_W)
                        cls._ensure_float_column(columns, 'free_piston_generator_electrical_power_W', n_samples)[k] = float(load_info.electrical_power_W)
                        cls._ensure_float_column(columns, 'free_piston_generator_damping_eff_Ns_per_m', n_samples)[k] = float(load_info.effective_damping_Ns_per_m)
                        cls._ensure_float_column(columns, 'free_piston_generator_force_base_N', n_samples)[k] = float(load_info.base_force_N)
                        cls._ensure_float_column(columns, 'free_piston_generator_force_power_N', n_samples)[k] = float(load_info.power_force_N)
                        cls._ensure_float_column(columns, 'free_piston_generator_force_stop_N', n_samples)[k] = float(load_info.stop_force_N)
                        cls._ensure_float_column(columns, 'free_piston_generator_distance_to_stop_m', n_samples)[k] = float(load_info.distance_to_stop_m)
                        cls._ensure_float_column(columns, 'free_piston_generator_midstroke_weight', n_samples)[k] = float(load_info.midstroke_weight_0to1)
                    else:
                        volume, dvdt, theta_deg, piston_x, dtheta_dt, cycle_deg = cylinder_kinematic_state_from_time(kin_matrix[kin_idx], float(tk))
                        theta_deg = cls._normalize_cycle_endpoint_theta(theta_deg, float(tk), float(dtheta_dt), float(cycle_deg))
                        theta_global_deg = theta_deg
                        dtheta_global_dt = dtheta_dt
                        if global_theta_and_rate_from_time is not None:
                            theta_global_deg_raw, _, _ = global_theta_and_rate_from_time(float(tk), kin_matrix[kin_idx])
                            theta_global_deg = cls._normalize_cycle_endpoint_theta(theta_global_deg_raw, float(tk), float(dtheta_dt), float(cycle_deg))
                        fuel_mass_eff = float(bundle.combustion_fuel_mass_by_vol[i]) if getattr(bundle, "combustion_fuel_mass_by_vol", None) is not None and i < int(bundle.combustion_fuel_mass_by_vol.shape[0]) else 0.0
                        afr_eff = float(bundle.combustion_afr_stoich_by_vol[i]) if getattr(bundle, "combustion_afr_stoich_by_vol", None) is not None and i < int(bundle.combustion_afr_stoich_by_vol.shape[0]) else 14.5
                        if use_promo_thermo:
                            lambda_eff = lambda_from_air_and_fuel_mass(air_mass, fuel_vapor_mass, afr_eff)
                            temp, cp_i, cv_i, gas_constant_i, kappa_i = properties_from_mass_energy_components_quellen(mass, energy, air_mass, fuel_vapor_mass, burned_mass, float(cv_default))
                            pressure = mass * gas_constant_i * temp / volume if volume > 1.0e-18 else 0.0
                            cp_by_vol[i] = cp_i
                            cv_by_vol[i] = cv_i
                            gas_constant_by_vol[i] = gas_constant_i
                            kappa_by_vol[i] = kappa_i
                            lambda_eff_by_vol[i] = lambda_eff
                        else:
                            temp = temperature_from_state(max(mass, 1.0e-30), max(energy, 1.0e-30), float(cv_default))
                            pressure = mass * float(gas_constant_default) * temp / volume if volume > 1.0e-18 else 0.0
                            cp_by_vol[i] = float(cp_default)
                            cv_by_vol[i] = float(cv_default)
                            gas_constant_by_vol[i] = float(gas_constant_default)
                            kappa_by_vol[i] = float(kappa_default)
                            lambda_eff_by_vol[i] = default_airlike_lambda()
                    piston_x_by_vol[i] = piston_distance_from_tdc if (getattr(bundle, 'architecture', 'classic') == 'free_piston' and kin_idx < 0 and getattr(bundle, 'free_piston', None) is not None) else piston_x
                    theta_deg_by_vol[i] = theta_deg
                    theta_global_deg_by_vol[i] = theta_global_deg
                    dtheta_local_dt_by_vol[i] = dtheta_dt
                    dtheta_global_dt_by_vol[i] = dtheta_global_dt
                    cycle_deg_by_vol[i] = cycle_deg
                elif vol_type == VolumeType.BOUNCE_CHAMBER and getattr(bundle, 'architecture', 'classic') == 'free_piston' and getattr(bundle, 'free_piston', None) is not None:
                    fp = bundle.free_piston
                    piston_x, piston_v = _free_piston_local_kinematics(bundle, i, y_arr, k)
                    volume = bounce_volume_from_position(fp.bounce_chamber_volume0_m3, fp.bounce_area_m2, piston_x, fp.x_min_m, fp.x_max_m)
                    dvdt = -cylinder_dvdt_from_velocity(fp.bounce_area_m2, piston_v)
                    theta_deg = 0.0
                    fuel_mass_eff = float(bundle.combustion_fuel_mass_by_vol[i]) if getattr(bundle, "combustion_fuel_mass_by_vol", None) is not None and i < int(bundle.combustion_fuel_mass_by_vol.shape[0]) else 0.0
                    afr_eff = float(bundle.combustion_afr_stoich_by_vol[i]) if getattr(bundle, "combustion_afr_stoich_by_vol", None) is not None and i < int(bundle.combustion_afr_stoich_by_vol.shape[0]) else 14.5
                    if use_promo_thermo:
                        lambda_eff = lambda_from_air_and_fuel_mass(air_mass, fuel_vapor_mass, afr_eff)
                        temp, cp_i, cv_i, gas_constant_i, kappa_i = properties_from_mass_energy_components_quellen(mass, energy, air_mass, fuel_vapor_mass, burned_mass, float(cv_default))
                        pressure = mass * gas_constant_i * temp / volume if volume > 1.0e-18 else 0.0
                        cp_by_vol[i] = cp_i
                        cv_by_vol[i] = cv_i
                        gas_constant_by_vol[i] = gas_constant_i
                        kappa_by_vol[i] = kappa_i
                        lambda_eff_by_vol[i] = lambda_eff
                    else:
                        temp = temperature_from_state(max(mass, 1.0e-30), max(energy, 1.0e-30), float(cv_default))
                        pressure = mass * float(gas_constant_default) * temp / volume if volume > 1.0e-18 else 0.0
                        cp_by_vol[i] = float(cp_default)
                        cv_by_vol[i] = float(cv_default)
                        gas_constant_by_vol[i] = float(gas_constant_default)
                        kappa_by_vol[i] = float(kappa_default)
                        lambda_eff_by_vol[i] = default_airlike_lambda()
                elif int(environment_is_fixed[i]) == 1 or vol_type == VolumeType.ENVIRONMENT:
                    temp = float(environment_temperatures_K[i]) if float(environment_temperatures_K[i]) > 0.0 else 300.0
                    pressure = float(environment_pressures_pa[i]) if float(environment_pressures_pa[i]) > 0.0 else 101325.0
                    cp_by_vol[i] = float(cp_default)
                    cv_by_vol[i] = float(cv_default)
                    gas_constant_by_vol[i] = float(gas_constant_default)
                    kappa_by_vol[i] = float(kappa_default)
                    lambda_eff_by_vol[i] = default_airlike_lambda()
                    volume = float(vol_matrix[i, VolumeCol.FIXED_VOLUME])
                    dvdt = 0.0
                    theta_deg = 0.0
                else:
                    volume = float(vol_matrix[i, VolumeCol.FIXED_VOLUME])
                    dvdt = 0.0
                    theta_deg = 0.0
                    fuel_mass_eff = float(bundle.combustion_fuel_mass_by_vol[i]) if getattr(bundle, "combustion_fuel_mass_by_vol", None) is not None and i < int(bundle.combustion_fuel_mass_by_vol.shape[0]) else 0.0
                    afr_eff = float(bundle.combustion_afr_stoich_by_vol[i]) if getattr(bundle, "combustion_afr_stoich_by_vol", None) is not None and i < int(bundle.combustion_afr_stoich_by_vol.shape[0]) else 14.5
                    if use_promo_thermo:
                        lambda_eff = lambda_from_air_and_fuel_mass(air_mass, fuel_vapor_mass, afr_eff)
                        temp, cp_i, cv_i, gas_constant_i, kappa_i = properties_from_mass_energy_components_quellen(mass, energy, air_mass, fuel_vapor_mass, burned_mass, float(cv_default))
                        pressure = mass * gas_constant_i * temp / volume if volume > 1.0e-18 else 0.0
                        cp_by_vol[i] = cp_i
                        cv_by_vol[i] = cv_i
                        gas_constant_by_vol[i] = gas_constant_i
                        kappa_by_vol[i] = kappa_i
                        lambda_eff_by_vol[i] = lambda_eff
                    else:
                        temp = temperature_from_state(max(mass, 1.0e-30), max(energy, 1.0e-30), float(cv_default))
                        pressure = mass * float(gas_constant_default) * temp / volume if volume > 1.0e-18 else 0.0
                        cp_by_vol[i] = float(cp_default)
                        cv_by_vol[i] = float(cv_default)
                        gas_constant_by_vol[i] = float(gas_constant_default)
                        kappa_by_vol[i] = float(kappa_default)
                        lambda_eff_by_vol[i] = default_airlike_lambda()
                pressure_by_vol[i] = pressure
                temperature_by_vol[i] = temp
                volume_by_vol[i] = volume
                dvdt_by_vol[i] = dvdt
                cls._ensure_float_column(columns, f'{name}_m_kg', n_samples)[k] = mass
                cls._ensure_float_column(columns, f'{name}_U_J', n_samples)[k] = energy
                total_inventory_mass = mass + liquid_fuel_mass
                unburned_mass = float(unburned_mass_kg(mass, burned_mass))
                cls._ensure_float_column(columns, f'{name}_m_burned_kg', n_samples)[k] = burned_mass
                cls._ensure_float_column(columns, f'{name}_m_air_kg', n_samples)[k] = air_mass
                cls._ensure_float_column(columns, f'{name}_m_fresh_gas_kg', n_samples)[k] = air_mass + fuel_vapor_mass
                cls._ensure_float_column(columns, f'{name}_m_fuel_liquid_kg', n_samples)[k] = liquid_fuel_mass
                cls._ensure_float_column(columns, f'{name}_m_fuel_vapor_kg', n_samples)[k] = fuel_vapor_mass
                cls._ensure_float_column(columns, f'{name}_m_fuel_total_kg', n_samples)[k] = fuel_vapor_mass + liquid_fuel_mass
                cls._ensure_float_column(columns, f'{name}_m_inventory_total_kg', n_samples)[k] = total_inventory_mass
                cls._ensure_float_column(columns, f'{name}_m_unburned_kg', n_samples)[k] = unburned_mass
                cls._ensure_float_column(columns, f'{name}_burned_fraction_0to1', n_samples)[k] = float(burned_fraction_0to1(mass, burned_mass))
                cls._ensure_float_column(columns, f'{name}_share_air_0to1', n_samples)[k] = _safe_mass_fraction(air_mass, total_inventory_mass)
                cls._ensure_float_column(columns, f'{name}_share_fuel_vapor_0to1', n_samples)[k] = _safe_mass_fraction(fuel_vapor_mass, total_inventory_mass)
                cls._ensure_float_column(columns, f'{name}_share_fuel_liquid_0to1', n_samples)[k] = _safe_mass_fraction(liquid_fuel_mass, total_inventory_mass)
                cls._ensure_float_column(columns, f'{name}_share_fuel_total_0to1', n_samples)[k] = _safe_mass_fraction(fuel_vapor_mass + liquid_fuel_mass, total_inventory_mass)
                cls._ensure_float_column(columns, f'{name}_share_burned_0to1', n_samples)[k] = _safe_mass_fraction(burned_mass, total_inventory_mass)
                cls._ensure_float_column(columns, f'{name}_share_fresh_gas_0to1', n_samples)[k] = _safe_mass_fraction(air_mass + fuel_vapor_mass, total_inventory_mass)
                cls._ensure_float_column(columns, f'{name}_share_unburned_0to1', n_samples)[k] = _safe_mass_fraction(unburned_mass, total_inventory_mass)
                cls._ensure_float_column(columns, f'{name}_T_K', n_samples)[k] = temp
                cls._ensure_float_column(columns, f'{name}_p_Pa', n_samples)[k] = pressure
                cls._ensure_float_column(columns, f'{name}_cp_J_per_kgK', n_samples)[k] = float(cp_by_vol[i])
                cls._ensure_float_column(columns, f'{name}_cv_J_per_kgK', n_samples)[k] = float(cv_by_vol[i])
                cls._ensure_float_column(columns, f'{name}_R_J_per_kgK', n_samples)[k] = float(gas_constant_by_vol[i])
                cls._ensure_float_column(columns, f'{name}_kappa', n_samples)[k] = float(kappa_by_vol[i])
                cls._ensure_float_column(columns, f'{name}_thermo_lambda', n_samples)[k] = float(lambda_eff_by_vol[i])
                cls._ensure_float_column(columns, f'{name}_V_m3', n_samples)[k] = volume
                cls._ensure_float_column(columns, f'{name}_dVdt_m3_per_s', n_samples)[k] = dvdt
                cls._ensure_float_column(columns, f'{name}_theta_deg', n_samples)[k] = theta_deg
                if getattr(bundle, 'architecture', 'classic') == 'free_piston' and getattr(bundle, 'free_piston', None) is not None and vol_type in (VolumeType.CYLINDER, VolumeType.BOUNCE_CHAMBER):
                    fp = bundle.free_piston
                    local_piston_x, local_piston_v = _free_piston_local_kinematics(bundle, i, y_arr, k)
                    cls._ensure_float_column(columns, f'{name}_piston_x_m', n_samples)[k] = local_piston_x
                    cls._ensure_float_column(columns, f'{name}_piston_distance_from_tdc_m', n_samples)[k] = cylinder_distance_from_tdc(local_piston_x, fp.x_min_m, fp.x_max_m)
                    cls._ensure_float_column(columns, f'{name}_piston_v_m_per_s', n_samples)[k] = local_piston_v
                if i == primary_cyl_idx:
                    theta_local[k] = float(theta_deg)
                    theta_global[k] = float(theta_deg)

            if getattr(bundle, 'architecture', 'classic') == 'free_piston' and getattr(bundle, 'free_piston', None) is not None and primary_cyl_idx >= 0:
                fp = bundle.free_piston
                x_idx = int(fp.x_state_index)
                v_idx = int(fp.v_state_index)
                piston_q = float(y_arr[x_idx, k])
                piston_q_dot = float(y_arr[v_idx, k])
                piston_x, piston_v = _free_piston_local_kinematics(bundle, primary_cyl_idx, y_arr, k)
                force_gas = 0.0
                force_bounce = 0.0
                primary_dof = 0
                volume_mechanical_dof = getattr(fp, 'volume_mechanical_dof', np.full(n_vol, -1, dtype=np.int64))
                volume_mechanical_sign = getattr(fp, 'volume_mechanical_sign', np.zeros(n_vol, dtype=np.float64))
                if primary_cyl_idx < int(len(volume_mechanical_dof)):
                    primary_dof = int(volume_mechanical_dof[primary_cyl_idx])
                for mech_i in range(n_vol):
                    if mech_i >= int(len(volume_mechanical_dof)) or int(volume_mechanical_dof[mech_i]) != primary_dof:
                        continue
                    sign_i = float(volume_mechanical_sign[mech_i]) if mech_i < int(len(volume_mechanical_sign)) else 0.0
                    mech_type = int(vol_matrix[mech_i, VolumeCol.TYPE])
                    if mech_type == VolumeType.CYLINDER:
                        force_gas += sign_i * float(pressure_by_vol[mech_i]) * float(fp.piston_area_m2)
                    elif mech_type == VolumeType.BOUNCE_CHAMBER:
                        force_bounce += -sign_i * float(pressure_by_vol[mech_i]) * float(fp.bounce_area_m2)
                if abs(piston_v) < 1.0e-15:
                    friction_force = 0.0
                else:
                    friction_force = -(fp.friction_fc_N * np.copysign(1.0, piston_v) + fp.friction_cv_Ns_per_m * piston_v)
                load_info = compute_load_info(
                    fp.load_model,
                    fp.load_damping_Ns_per_m,
                    piston_v,
                    x_m=piston_x,
                    x_min_m=fp.x_min_m,
                    x_max_m=fp.x_max_m,
                    max_damping_Ns_per_m=fp.load_max_damping_Ns_per_m,
                    control_zone_m=fp.load_control_zone_m,
                    power_target_W=fp.load_power_target_W,
                    efficiency_0to1=fp.load_efficiency_0to1,
                    min_velocity_m_per_s=fp.load_min_velocity_m_per_s,
                    assist_velocity_threshold_m_per_s=fp.load_assist_velocity_threshold_m_per_s,
                    assist_force_N=fp.load_assist_force_N,
                    target_margin_m=fp.load_target_margin_m,
                    hard_margin_m=fp.load_hard_margin_m,
                    stop_kp=fp.load_stop_kp,
                    moving_mass_kg=fp.moving_mass_kg,
                    max_force_N=fp.load_max_force_N,
                )
                load_force = -float(load_info.force_signed_N)
                force_net = force_gas + force_bounce + friction_force + load_force
                if str(getattr(fp, 'kinematics_type', 'linear') or 'linear') == 'oscillating_rotary':
                    radius = max(float(getattr(fp, 'rotary_effective_radius_m', 1.0) or 1.0), 1.0e-18)
                    inertia = max(float(getattr(fp, 'rotary_inertia_kg_m2', fp.moving_mass_kg) or fp.moving_mass_kg), 1.0e-30)
                    equivalent_accel = force_net * radius * radius / inertia
                else:
                    equivalent_accel = force_net / max(float(fp.moving_mass_kg), 1.0e-30)
                cls._ensure_float_column(columns, 'free_piston_x_m', n_samples)[k] = piston_x
                cls._ensure_float_column(columns, 'free_piston_distance_from_tdc_m', n_samples)[k] = cylinder_distance_from_tdc(piston_x, fp.x_min_m, fp.x_max_m)
                cls._ensure_float_column(columns, 'free_piston_v_m_per_s', n_samples)[k] = piston_v
                cls._ensure_float_column(columns, 'free_piston_q', n_samples)[k] = piston_q
                cls._ensure_float_column(columns, 'free_piston_q_dot', n_samples)[k] = piston_q_dot
                cls._ensure_float_column(columns, 'free_piston_a_m_per_s2', n_samples)[k] = equivalent_accel
                if bounce_idx >= 0:
                    cls._ensure_float_column(columns, 'bounce_volume_m3', n_samples)[k] = float(volume_by_vol[bounce_idx])
                    cls._ensure_float_column(columns, 'bounce_pressure_Pa', n_samples)[k] = float(pressure_by_vol[bounce_idx])
                cls._ensure_float_column(columns, 'free_piston_F_gas_N', n_samples)[k] = force_gas
                cls._ensure_float_column(columns, 'free_piston_F_bounce_N', n_samples)[k] = force_bounce
                cls._ensure_float_column(columns, 'free_piston_F_friction_N', n_samples)[k] = friction_force
                cls._ensure_float_column(columns, 'free_piston_F_load_N', n_samples)[k] = load_force
                cls._ensure_float_column(columns, 'free_piston_F_net_N', n_samples)[k] = force_net
                cls._ensure_float_column(columns, 'free_piston_generator_power_W', n_samples)[k] = float(load_info.mechanical_power_W)
                cls._ensure_float_column(columns, 'free_piston_generator_electrical_power_W', n_samples)[k] = float(load_info.electrical_power_W)
                cls._ensure_float_column(columns, 'free_piston_generator_damping_eff_Ns_per_m', n_samples)[k] = float(load_info.effective_damping_Ns_per_m)
                cls._ensure_float_column(columns, 'free_piston_generator_force_base_N', n_samples)[k] = float(load_info.base_force_N)
                cls._ensure_float_column(columns, 'free_piston_generator_force_power_N', n_samples)[k] = float(load_info.power_force_N)
                cls._ensure_float_column(columns, 'free_piston_generator_force_stop_N', n_samples)[k] = float(load_info.stop_force_N)
                cls._ensure_float_column(columns, 'free_piston_generator_distance_to_stop_m', n_samples)[k] = float(load_info.distance_to_stop_m)
                cls._ensure_float_column(columns, 'free_piston_generator_midstroke_weight', n_samples)[k] = float(load_info.midstroke_weight_0to1)

            for j in range(n_conn):
                conn = conn_matrix[j]
                conn_name = connection_names[j]
                left = int(conn[ConnCol.FROM_VOL])
                right = int(conn[ConnCol.TO_VOL])
                conn_type = int(conn[ConnCol.TYPE])
                cyl_idx = left if int(vol_matrix[left, VolumeCol.TYPE]) == VolumeType.CYLINDER else right
                geom_area_m2 = 0.0
                cd_forward = 0.0
                cd_reverse = 0.0
                aeff_forward = 0.0
                aeff_reverse = 0.0

                if conn_type == ConnectionType.VALVE:
                    if int(vol_matrix[cyl_idx, VolumeCol.TYPE]) != VolumeType.CYLINDER:
                        continue
                    lift_m, bore_area_m2, area_forward_m2, area_reverse_m2, alpha_forward, alpha_reverse = _call_evaluate_valve_state(
                        conn,
                        theta_deg_by_vol[cyl_idx],
                        theta_global_deg_by_vol[cyl_idx],
                        cycle_deg_by_vol[cyl_idx],
                        lift_table,
                        alpha_table,
                    )
                    geom_area_m2 = float(bore_area_m2)
                    cd_forward = float(alpha_forward)
                    cd_reverse = float(alpha_reverse)
                    aeff_forward = float(area_forward_m2)
                    aeff_reverse = float(area_reverse_m2)
                    cls._ensure_float_column(columns, f'{conn_name}_valve_lift_m', n_samples)[k] = float(lift_m)
                    cls._ensure_float_column(columns, f'{conn_name}_A_geom_m2', n_samples)[k] = float(bore_area_m2)
                    cls._ensure_float_column(columns, f'{conn_name}_A_eff_forward_m2', n_samples)[k] = aeff_forward
                    cls._ensure_float_column(columns, f'{conn_name}_A_eff_reverse_m2', n_samples)[k] = aeff_reverse
                elif conn_type == ConnectionType.SLOT:
                    if int(vol_matrix[cyl_idx, VolumeCol.TYPE]) != VolumeType.CYLINDER:
                        continue
                    open_height_m, geom_area_m2, area_forward_m2, area_reverse_m2, cd_forward, cd_reverse = _evaluate_slot_state(conn, piston_x_by_vol[cyl_idx], cd_table)
                    geom_area_m2 = float(geom_area_m2)
                    aeff_forward = float(area_forward_m2)
                    aeff_reverse = float(area_reverse_m2)
                    cls._ensure_float_column(columns, f'{conn_name}_slot_height_m', n_samples)[k] = float(open_height_m)
                    cls._ensure_float_column(columns, f'{conn_name}_A_geom_m2', n_samples)[k] = geom_area_m2
                    cls._ensure_float_column(columns, f'{conn_name}_A_eff_forward_m2', n_samples)[k] = aeff_forward
                    cls._ensure_float_column(columns, f'{conn_name}_A_eff_reverse_m2', n_samples)[k] = aeff_reverse
                elif conn_type == ConnectionType.ORIFICE:
                    geom_area_m2, cd_forward, cd_reverse = _evaluate_orifice_area(conn)
                    aeff_forward = float(geom_area_m2 * cd_forward)
                    aeff_reverse = float(geom_area_m2 * cd_reverse)
                    cls._ensure_float_column(columns, f'{conn_name}_A_geom_m2', n_samples)[k] = float(geom_area_m2)
                    cls._ensure_float_column(columns, f'{conn_name}_A_eff_forward_m2', n_samples)[k] = aeff_forward
                    cls._ensure_float_column(columns, f'{conn_name}_A_eff_reverse_m2', n_samples)[k] = aeff_reverse
                elif conn_type == ConnectionType.CHECK_VALVE:
                    geom_area_m2, cd_forward, cd_reverse = _evaluate_check_valve_area(conn, pressure_by_vol[left], pressure_by_vol[right])
                    aeff_forward = float(geom_area_m2 * cd_forward)
                    aeff_reverse = float(geom_area_m2 * cd_reverse)
                    cls._ensure_float_column(columns, f'{conn_name}_A_geom_m2', n_samples)[k] = float(geom_area_m2)
                    cls._ensure_float_column(columns, f'{conn_name}_A_eff_forward_m2', n_samples)[k] = aeff_forward
                    cls._ensure_float_column(columns, f'{conn_name}_A_eff_reverse_m2', n_samples)[k] = aeff_reverse
                    cls._ensure_float_column(columns, f'{conn_name}_open_0to1', n_samples)[k] = 1.0 if cd_forward > 0.0 else 0.0
                else:
                    continue

                if pressure_by_vol[left] >= pressure_by_vol[right]:
                    gamma_up = float(kappa_by_vol[left])
                    gas_constant_up = float(gas_constant_by_vol[left])
                    cp_up = float(cp_by_vol[left])
                    temp_up = float(temperature_by_vol[left])
                else:
                    gamma_up = float(kappa_by_vol[right])
                    gas_constant_up = float(gas_constant_by_vol[right])
                    cp_up = float(cp_by_vol[right])
                    temp_up = float(temperature_by_vol[right])
                mdot_kg_per_s = float(de_st_venant_wantzel_signed(
                    pressure_by_vol[left],
                    temperature_by_vol[left],
                    pressure_by_vol[right],
                    temperature_by_vol[right],
                    geom_area_m2,
                    cd_forward,
                    cd_reverse,
                    gamma_up,
                    gas_constant_up,
                ))
                if mdot_kg_per_s >= 0.0:
                    upstream_state = y_arr[:, k]
                    upstream_burned_fraction, upstream_air_fraction = _upstream_species_fractions(state_layout, upstream_state, left, environment_is_fixed)
                    h_up = cp_up * temp_up
                else:
                    upstream_state = y_arr[:, k]
                    upstream_burned_fraction, upstream_air_fraction = _upstream_species_fractions(state_layout, upstream_state, right, environment_is_fixed)
                    h_up = cp_up * temp_up
                mdot_burned_kg_per_s = float(mdot_kg_per_s * upstream_burned_fraction)
                mdot_air_kg_per_s = float(mdot_kg_per_s * upstream_air_fraction)
                mdot_unburned_kg_per_s = float(mdot_kg_per_s - mdot_burned_kg_per_s)
                mdot_fuel_vapor_kg_per_s = float(mdot_kg_per_s - mdot_burned_kg_per_s - mdot_air_kg_per_s)
                cls._ensure_float_column(columns, f'{conn_name}_mdot_kg_per_s', n_samples)[k] = mdot_kg_per_s
                cls._ensure_float_column(columns, f'{conn_name}_mdot_burned_kg_per_s', n_samples)[k] = mdot_burned_kg_per_s
                cls._ensure_float_column(columns, f'{conn_name}_mdot_air_kg_per_s', n_samples)[k] = mdot_air_kg_per_s
                cls._ensure_float_column(columns, f'{conn_name}_mdot_fuel_vapor_kg_per_s', n_samples)[k] = mdot_fuel_vapor_kg_per_s
                cls._ensure_float_column(columns, f'{conn_name}_mdot_unburned_kg_per_s', n_samples)[k] = mdot_unburned_kg_per_s

                if conn_type == int(ConnectionType.SLOT):
                    if int(vol_matrix[right, VolumeCol.TYPE]) == VolumeType.CYLINDER and mdot_kg_per_s > 0.0:
                        scav_transfer_in[right] += mdot_kg_per_s
                        scav_transfer_air_in[right] += max(mdot_air_kg_per_s, 0.0)
                    elif int(vol_matrix[left, VolumeCol.TYPE]) == VolumeType.CYLINDER and mdot_kg_per_s < 0.0:
                        scav_transfer_in[left] += -mdot_kg_per_s
                        scav_transfer_air_in[left] += max(-mdot_air_kg_per_s, 0.0)
                    if int(vol_matrix[left, VolumeCol.TYPE]) == VolumeType.CYLINDER and mdot_kg_per_s > 0.0:
                        scav_exhaust_out[left] += mdot_kg_per_s
                    elif int(vol_matrix[right, VolumeCol.TYPE]) == VolumeType.CYLINDER and mdot_kg_per_s < 0.0:
                        scav_exhaust_out[right] += -mdot_kg_per_s

                if int(vol_matrix[left, VolumeCol.TYPE]) == VolumeType.CYLINDER:
                    if mdot_kg_per_s >= 0.0:
                        cyl_mdot_out[left] += mdot_kg_per_s
                        cyl_enthalpy_out[left] += mdot_kg_per_s * h_up
                        cyl_aeff_out[left] += aeff_forward
                    else:
                        cyl_mdot_in[left] += -mdot_kg_per_s
                        cyl_enthalpy_in[left] += -mdot_kg_per_s * h_up
                        cyl_aeff_in[left] += aeff_reverse
                if int(vol_matrix[right, VolumeCol.TYPE]) == VolumeType.CYLINDER:
                    if mdot_kg_per_s >= 0.0:
                        cyl_mdot_in[right] += mdot_kg_per_s
                        cyl_enthalpy_in[right] += mdot_kg_per_s * h_up
                        cyl_aeff_in[right] += aeff_forward
                    else:
                        cyl_mdot_out[right] += -mdot_kg_per_s
                        cyl_enthalpy_out[right] += -mdot_kg_per_s * h_up
                        cyl_aeff_out[right] += aeff_reverse

            for i in range(n_vol):
                if int(vol_matrix[i, VolumeCol.TYPE]) != VolumeType.CYLINDER:
                    continue
                name = volume_names[i]
                pdv_power, wall_heat_w, heat_transfer_coeff, _wall_velocity, added_energy_w, evap_sink_w = cylinder_energy_source_terms_from_context(
                    vol_matrix[i],
                    wall_matrix,
                    comb_matrix,
                    evap_matrix,
                    feature_flags,
                    wall_bore_by_vol[i],
                    wall_ups_by_vol[i],
                    pressure_by_vol[i],
                    temperature_by_vol[i],
                    volume_by_vol[i],
                    float(y_arr[int(state_layout.mass_index(i)), k]),
                    float(cyl_mdot_in[i]),
                    dvdt_by_vol[i],
                    theta_deg_by_vol[i],
                    theta_global_deg_by_vol[i],
                    dtheta_local_dt_by_vol[i],
                    dtheta_global_dt_by_vol[i],
                    cycle_deg_by_vol[i],
                )
                comb_idx = int(vol_matrix[i, VolumeCol.COMB_ROW])
                if i in cylinder_latch_histories and comb_idx >= 0:
                    cyl_latched_energy_hist = cylinder_latch_histories[i][2]
                    cyl_soc_time_hist, cyl_soc_energy_hist, _cyl_soc_active_hist = cylinder_soc_histories.get(
                        i,
                        (soc_time_hist, soc_energy_hist, soc_active_hist),
                    )
                    comb_row = comb_matrix[comb_idx]
                    duration_mode = int(combustion_duration_mode_from_row(comb_row))
                    if duration_mode == int(CombDurationMode.TIME):
                        added_energy_w = vibe_time_heat_release_rate_with_total_energy(
                            t_arr[k],
                            float(cyl_soc_time_hist[k]),
                            float(comb_row[CombCol.DURATION_DEG]),
                            float(comb_row[CombCol.A]),
                            float(comb_row[CombCol.M]),
                            float(cyl_soc_energy_hist[k]),
                        )
                    elif use_fp_latched_fuel:
                        if free_piston_reference_is_active(int(comb_row[CombCol.REF_TYPE]), float(piston_x_by_vol[i]), float(piston_v_by_vol[i]), fp.x_min_m, fp.x_max_m):
                            added_energy_w = vibe_heat_release_rate_with_total_energy(
                                theta_deg_by_vol[i],
                                theta_global_deg_by_vol[i],
                                dtheta_local_dt_by_vol[i],
                                dtheta_global_dt_by_vol[i],
                                float(comb_row[CombCol.START_DEG]),
                                float(comb_row[CombCol.DURATION_DEG]),
                                float(comb_row[CombCol.A]),
                                float(comb_row[CombCol.M]),
                                float(cyl_latched_energy_hist[k]),
                                int(comb_row[CombCol.REF_TYPE]),
                                cycle_deg_by_vol[i],
                            )
                        else:
                            added_energy_w = 0.0
                _ = (comb_idx, compression_active_by_vol[i])
                cls._ensure_float_column(columns, f'{name}_mdot_in_kg_per_s', n_samples)[k] = float(cyl_mdot_in[i])
                cls._ensure_float_column(columns, f'{name}_mdot_out_kg_per_s', n_samples)[k] = float(cyl_mdot_out[i])
                cls._ensure_float_column(columns, f'{name}_A_eff_in_m2', n_samples)[k] = float(cyl_aeff_in[i])
                cls._ensure_float_column(columns, f'{name}_A_eff_out_m2', n_samples)[k] = float(cyl_aeff_out[i])
                cls._ensure_float_column(columns, f'{name}_enthalpy_in_W', n_samples)[k] = float(cyl_enthalpy_in[i])
                cls._ensure_float_column(columns, f'{name}_enthalpy_out_W', n_samples)[k] = float(cyl_enthalpy_out[i])
                cls._ensure_float_column(columns, f'{name}_wall_heat_W', n_samples)[k] = float(wall_heat_w)
                cls._ensure_float_column(columns, f'{name}_heat_transfer_power_W', n_samples)[k] = float(wall_heat_w)
                cls._ensure_float_column(columns, f'{name}_htc_W_per_m2K', n_samples)[k] = float(heat_transfer_coeff)
                cls._ensure_float_column(columns, f'{name}_added_energy_W', n_samples)[k] = float(added_energy_w)
                cls._ensure_float_column(columns, f'{name}_evaporation_sink_W', n_samples)[k] = float(evap_sink_w)
                cls._ensure_float_column(columns, f'{name}_piston_work_W', n_samples)[k] = float(pdv_power)
                if fp is not None and bool(getattr(fp, 'scavenging_enabled', False)):
                    cyl_mass_kg = float(y_arr[int(state_layout.mass_index(i)), k])
                    cyl_air_kg = float(y_arr[int(state_layout.air_mass_index(i)), k])
                    cyl_burned_kg = float(y_arr[int(state_layout.burned_mass_index(i)), k])
                    burned_correction, short_fraction, eta_scav = _scavenging_overlap_diagnostics(
                        fp,
                        cyl_mass_kg,
                        cyl_air_kg,
                        cyl_burned_kg,
                        float(scav_transfer_in[i]),
                        float(scav_transfer_air_in[i]),
                        float(scav_exhaust_out[i]),
                    )
                    cls._ensure_float_column(columns, f'{name}_scavenging_transfer_in_kg_per_s', n_samples)[k] = float(scav_transfer_in[i])
                    cls._ensure_float_column(columns, f'{name}_scavenging_exhaust_out_kg_per_s', n_samples)[k] = float(scav_exhaust_out[i])
                    cls._ensure_float_column(columns, f'{name}_scavenging_burned_correction_kg_per_s', n_samples)[k] = burned_correction
                    cls._ensure_float_column(columns, f'{name}_scavenging_short_circuit_fraction', n_samples)[k] = short_fraction
                    cls._ensure_float_column(columns, f'{name}_scavenging_efficiency_0to1', n_samples)[k] = eta_scav
                if use_fp_latched_fuel and i in cylinder_latch_histories:
                    cyl_latched_air_hist, cyl_latched_fuel_hist, cyl_latched_energy_hist, cyl_slot_area_hist = cylinder_latch_histories[i]
                    air_mass_kg = float(cyl_latched_air_hist[k])
                    fuel_mass_kg = float(cyl_latched_fuel_hist[k])
                    energy_latched_J = float(cyl_latched_energy_hist[k])
                    afr_latched = float(bundle.combustion_afr_stoich_by_vol[i]) if getattr(bundle, 'combustion_afr_stoich_by_vol', None) is not None and i < int(bundle.combustion_afr_stoich_by_vol.shape[0]) else float(getattr(fp, 'combustion_afr_stoich_kg_air_per_kg_fuel', 0.0) or 0.0)
                    lambda_value = _lambda_from_air_and_fuel(air_mass_kg, fuel_mass_kg, afr_latched)
                    cls._ensure_float_column(columns, f'{name}_combustion_air_mass_latched_kg', n_samples)[k] = air_mass_kg
                    cls._ensure_float_column(columns, f'{name}_combustion_fuel_mass_latched_kg', n_samples)[k] = fuel_mass_kg
                    cls._ensure_float_column(columns, f'{name}_combustion_energy_latched_J', n_samples)[k] = energy_latched_J
                    cls._ensure_float_column(columns, f'{name}_lambda', n_samples)[k] = lambda_value
                    cls._ensure_float_column(columns, f'{name}_slot_area_sum_m2', n_samples)[k] = float(cyl_slot_area_hist[k])
                    if i == primary_cyl_idx:
                        cls._ensure_float_column(columns, 'free_piston_slot_area_sum_m2', n_samples)[k] = float(cyl_slot_area_hist[k])
                        cls._ensure_float_column(columns, 'free_piston_combustion_mass_latched_kg', n_samples)[k] = air_mass_kg
                        cls._ensure_float_column(columns, 'free_piston_combustion_fuel_mass_latched_kg', n_samples)[k] = fuel_mass_kg
                        cls._ensure_float_column(columns, 'free_piston_combustion_energy_latched_J', n_samples)[k] = energy_latched_J
                        cls._ensure_float_column(columns, 'free_piston_combustion_lambda', n_samples)[k] = lambda_value

        cls._add_burn_window_energy_columns(columns, t_arr, list(volume_names))
        _add_single_instance_compat_aliases(columns, bundle)

        columns['t_s'] = np.asarray(t_arr, dtype=np.float64)
        columns['cycle_index'] = np.asarray(cycle_idx_arr, dtype=np.int64)
        columns['theta_deg'] = np.asarray(theta_global, dtype=np.float64)
        columns['theta_local_deg'] = np.asarray(theta_local, dtype=np.float64)
        return ReconstructedSeries(
            t_s=np.asarray(t_arr, dtype=np.float64),
            cycle_index=np.asarray(cycle_idx_arr, dtype=np.int64),
            theta_deg=np.asarray(theta_global, dtype=np.float64),
            theta_local_deg=np.asarray(theta_local, dtype=np.float64),
            columns=columns,
        )
