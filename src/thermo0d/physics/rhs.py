"""Thermo0D right-hand side and Jacobian support.

The module implements the mass and internal-energy balance for every control
volume. The hot path is structured in three stages:

1. reconstruct per-volume thermodynamic and kinematic state
2. evaluate connection mass/enthalpy flow
3. add local source terms such as p*dV work, wall heat, Vibe heat release and
   the evaporation sink

The bottom section provides analytic and hybrid Jacobian helpers for the stiff
solver path.
"""

from __future__ import annotations

import math

import numba as nb
import numpy as np

from thermo0d.compute.jacobian import finite_difference_jacobian
from thermo0d.config.constants import (
    AngleDomain,
    AngleReference,
    CombCol,
    CombDurationMode,
    ConnCol,
    ConnectionType,
    EndpointKind,
    EvapCol,
    FeatureCol,
    FlowCoeffMode,
    VolumeCol,
    VolumeType,
    WallCol,
    WallTemperatureCol,
    WallTemperatureZone,
)
from thermo0d.physics.flow import de_st_venant_wantzel_signed, interpolate_piecewise
from thermo0d.physics.thermo import safe_pressure_from_ideal_gas, safe_temperature_from_state
from thermo0d.physics.source_terms import volume_energy_source_terms
from thermo0d.physics.combustion import _comb_duration_mode_from_row, vibe_fraction_and_rate_numba
from thermo0d.physics.composition import burned_fraction_0to1, combustion_conversion_rate_kg_per_s
from thermo0d.physics.quellen_props import default_airlike_lambda, lambda_from_air_and_fuel_mass, properties_from_mass_energy_components_quellen
from thermo0d.physics.kinematics import (
    cylinder_kinematic_state_from_time,
    global_theta_and_rate_from_time,
    piston_displacement_from_tdc,
    reference_zero_deg,
    theta_and_rate_from_time,
    wrap_angle_deg,
)

V_TYPE = int(VolumeCol.TYPE)
V_KIN_ROW = int(VolumeCol.KIN_ROW)
V_FIXED = int(VolumeCol.FIXED_VOLUME)
V_WALL = int(VolumeCol.WALL_ROW)
V_COMB = int(VolumeCol.COMB_ROW)
V_EVAP = int(VolumeCol.EVAP_ROW)

C_TYPE = int(ConnCol.TYPE)
C_FROM = int(ConnCol.FROM_VOL)
C_TO = int(ConnCol.TO_VOL)
C_PRIMARY = int(ConnCol.PRIMARY_DIM)
C_SECONDARY = int(ConnCol.SECONDARY_DIM)
C_OPEN = int(ConnCol.OPEN_VALUE)
C_REF = int(ConnCol.REF_TYPE)
C_ANGLE_DOMAIN = int(ConnCol.ANGLE_DOMAIN)
C_LIFT_SCALE = int(ConnCol.LIFT_SCALE)
C_LASH = int(ConnCol.LASH)
C_N_HOLES = int(ConnCol.N_HOLES)
C_CD_MODE = int(ConnCol.CD_MODE)
C_CD_F = int(ConnCol.CD_FORWARD)
C_CD_R = int(ConnCol.CD_REVERSE)
C_PROFILE_START = int(ConnCol.PROFILE_START)
C_PROFILE_LEN = int(ConnCol.PROFILE_LEN)
C_ALPHA_START = int(ConnCol.ALPHA_START)
C_ALPHA_LEN = int(ConnCol.ALPHA_LEN)
C_CD_TABLE_START = int(ConnCol.CD_TABLE_START)
C_CD_TABLE_LEN = int(ConnCol.CD_TABLE_LEN)
C_REF_FLOW_AREA = int(ConnCol.REF_FLOW_AREA)
C_FROM_KIND = int(ConnCol.FROM_KIND)
C_TO_KIND = int(ConnCol.TO_KIND)
ENDPOINT_VOLUME = int(EndpointKind.VOLUME)

W_MODEL = int(WallCol.MODEL)
W_C1 = int(WallCol.C1)
W_C2 = int(WallCol.C2)
W_C3 = int(WallCol.C3)
W_TEMP = int(WallCol.WALL_TEMP)
W_AREA = int(WallCol.WALL_AREA)

WT_AREA = int(WallTemperatureCol.AREA)
WT_ENABLED = int(WallTemperatureCol.ENABLED)
WT_ZONE_COUNT = len(WallTemperatureZone)

B_START = int(CombCol.START_DEG)
B_DURATION = int(CombCol.DURATION_DEG)
B_A = int(CombCol.A)
B_M = int(CombCol.M)
B_FUEL = int(CombCol.FUEL_MASS_PER_CYCLE)
B_LHV = int(CombCol.LHV)
B_REF = int(CombCol.REF_TYPE)

E_START = int(EvapCol.START_DEG)
E_DURATION = int(EvapCol.DURATION_DEG)
E_MASS = int(EvapCol.EVAP_MASS_PER_CYCLE)
E_LATENT = int(EvapCol.LATENT_HEAT)
E_REF = int(EvapCol.REF_TYPE)

F_MASS = int(FeatureCol.MASS_FLOW)
F_WALL = int(FeatureCol.WALL_HEAT)
F_COMB = int(FeatureCol.COMBUSTION)
F_EVAP = int(FeatureCol.EVAPORATION)
F_PV = int(FeatureCol.PV_WORK)

REF_ABSOLUTE = int(AngleReference.ABSOLUTE)
DURATION_MODE_TIME = int(CombDurationMode.TIME)
ANGLE_DOMAIN_CAM = int(AngleDomain.CAM)
FLOW_COEFF_CONSTANT = int(FlowCoeffMode.CONSTANT)
CONN_VALVE = int(ConnectionType.VALVE)
CONN_SLOT = int(ConnectionType.SLOT)
CONN_ORIFICE = int(ConnectionType.ORIFICE)
CONN_CHECK_VALVE = int(ConnectionType.CHECK_VALVE)
VOL_CYLINDER = int(VolumeType.CYLINDER)
VOL_ENVIRONMENT = int(VolumeType.ENVIRONMENT)



@nb.njit(cache=True)
def _reference_theta_and_zero(theta_local_deg: float, theta_global_deg: float, cycle_deg: float, ref_type: int) -> tuple[float, float]:
    if ref_type == REF_ABSOLUTE:
        return theta_global_deg, 0.0
    return theta_local_deg, reference_zero_deg(cycle_deg, ref_type)


@nb.njit(cache=True)
def _evaluate_valve_state(
    conn_row: np.ndarray,
    theta_local_deg: float,
    theta_global_deg: float,
    cycle_deg: float,
    lift_table: np.ndarray,
    alpha_table: np.ndarray,
) -> tuple[float, float, float, float, float, float]:
    theta_ref_deg, ref_zero = _reference_theta_and_zero(theta_local_deg, theta_global_deg, cycle_deg, int(conn_row[C_REF]))
    local_crank_deg = wrap_angle_deg(theta_ref_deg - ref_zero - conn_row[C_OPEN], cycle_deg)
    profile_deg = local_crank_deg
    if int(conn_row[C_ANGLE_DOMAIN]) == ANGLE_DOMAIN_CAM:
        cam_ratio = cycle_deg / 360.0
        profile_deg = local_crank_deg / cam_ratio
    p_start = int(conn_row[C_PROFILE_START])
    p_len = int(conn_row[C_PROFILE_LEN])
    raw_lift = interpolate_piecewise(profile_deg, lift_table, p_start, p_len, 0, 1)
    lift = raw_lift * conn_row[C_LIFT_SCALE] - conn_row[C_LASH]
    if lift < 0.0:
        lift = 0.0
    a_start = int(conn_row[C_ALPHA_START])
    a_len = int(conn_row[C_ALPHA_LEN])
    alpha_forward = interpolate_piecewise(lift, alpha_table, a_start, a_len, 0, 1)
    alpha_reverse = interpolate_piecewise(lift, alpha_table, a_start, a_len, 0, 2)
    bore_area = conn_row[C_REF_FLOW_AREA]
    area_forward = alpha_forward * bore_area
    area_reverse = alpha_reverse * bore_area
    return lift, bore_area, area_forward, area_reverse, alpha_forward, alpha_reverse


@nb.njit(cache=True)
def _evaluate_valve_area(
    conn_row: np.ndarray,
    theta_local_deg: float,
    theta_global_deg: float,
    cycle_deg: float,
    lift_table: np.ndarray,
    alpha_table: np.ndarray,
) -> tuple[float, float, float]:
    theta_ref_deg, ref_zero = _reference_theta_and_zero(theta_local_deg, theta_global_deg, cycle_deg, int(conn_row[C_REF]))
    local_crank_deg = wrap_angle_deg(theta_ref_deg - ref_zero - conn_row[C_OPEN], cycle_deg)
    profile_deg = local_crank_deg
    if int(conn_row[C_ANGLE_DOMAIN]) == ANGLE_DOMAIN_CAM:
        cam_ratio = cycle_deg / 360.0
        profile_deg = local_crank_deg / cam_ratio
    p_start = int(conn_row[C_PROFILE_START])
    p_len = int(conn_row[C_PROFILE_LEN])
    raw_lift = interpolate_piecewise(profile_deg, lift_table, p_start, p_len, 0, 1)
    lift = raw_lift * conn_row[C_LIFT_SCALE] - conn_row[C_LASH]
    if lift < 0.0:
        lift = 0.0
    bore_area = conn_row[C_REF_FLOW_AREA]
    if bore_area <= 1.0e-18:
        return 0.0, 0.0, 0.0
    a_start = int(conn_row[C_ALPHA_START])
    a_len = int(conn_row[C_ALPHA_LEN])
    alpha_forward = interpolate_piecewise(lift, alpha_table, a_start, a_len, 0, 1)
    alpha_reverse = interpolate_piecewise(lift, alpha_table, a_start, a_len, 0, 2)
    return bore_area, alpha_forward, alpha_reverse


@nb.njit(cache=True)
def _evaluate_slot_state(conn_row: np.ndarray, piston_x_m: float, cd_table: np.ndarray) -> tuple[float, float, float, float, float, float]:
    width = conn_row[C_PRIMARY]
    height = conn_row[C_SECONDARY]
    holes = conn_row[C_N_HOLES]
    open_distance = conn_row[C_OPEN]
    uncovered = piston_x_m - open_distance
    if uncovered < 0.0:
        uncovered = 0.0
    if uncovered > height:
        uncovered = height
    geom_area = width * uncovered * holes
    if int(conn_row[C_CD_MODE]) == FLOW_COEFF_CONSTANT:
        cd_f = conn_row[C_CD_F]
        cd_r = conn_row[C_CD_R]
    else:
        start = int(conn_row[C_CD_TABLE_START])
        length = int(conn_row[C_CD_TABLE_LEN])
        cd_f = interpolate_piecewise(uncovered, cd_table, start, length, 0, 1)
        cd_r = interpolate_piecewise(uncovered, cd_table, start, length, 0, 2)
    area_forward = geom_area * cd_f
    area_reverse = geom_area * cd_r
    return uncovered, geom_area, area_forward, area_reverse, cd_f, cd_r


@nb.njit(cache=True)
def _evaluate_slot_area(conn_row: np.ndarray, piston_x_m: float, cd_table: np.ndarray) -> tuple[float, float, float]:
    _uncovered, geom_area, _area_forward, _area_reverse, cd_f, cd_r = _evaluate_slot_state(conn_row, piston_x_m, cd_table)
    return geom_area, cd_f, cd_r


@nb.njit(cache=True)
def _evaluate_orifice_area(conn_row: np.ndarray) -> tuple[float, float, float]:
    area = max(conn_row[C_PRIMARY], 0.0)
    return area, max(conn_row[C_CD_F], 0.0), max(conn_row[C_CD_R], 0.0)


@nb.njit(cache=True)
def _evaluate_check_valve_area(conn_row: np.ndarray, p_from_pa: float, p_to_pa: float) -> tuple[float, float, float]:
    area = max(conn_row[C_PRIMARY], 0.0)
    cd = max(conn_row[C_CD_F], 0.0)
    cracking = max(conn_row[C_OPEN], 0.0)
    if (p_from_pa - p_to_pa) <= cracking:
        return area, 0.0, 0.0
    return area, cd, 0.0


@nb.njit(cache=True)
def _connection_area_and_coefficients(
    conn_row: np.ndarray,
    conn_type: int,
    cyl_theta_deg: float,
    cyl_theta_global_deg: float,
    cyl_cycle_deg: float,
    cyl_piston_x_m: float,
    lift_table: np.ndarray,
    alpha_table: np.ndarray,
    cd_table: np.ndarray,
    p_from_pa: float = 0.0,
    p_to_pa: float = 0.0,
) -> tuple[float, float, float]:
    if conn_type == CONN_VALVE:
        return _evaluate_valve_area(conn_row, cyl_theta_deg, cyl_theta_global_deg, cyl_cycle_deg, lift_table, alpha_table)
    if conn_type == CONN_SLOT:
        return _evaluate_slot_area(conn_row, cyl_piston_x_m, cd_table)
    if conn_type == CONN_ORIFICE:
        return _evaluate_orifice_area(conn_row)
    if conn_type == CONN_CHECK_VALVE:
        return _evaluate_check_valve_area(conn_row, p_from_pa, p_to_pa)
    return 0.0, 0.0, 0.0


@nb.njit(cache=True)
def _vibe_heat_release_rate(theta_deg: float, dtheta_dt_deg_s: float, comb_row: np.ndarray, cycle_deg: float) -> float:
    ref_zero = reference_zero_deg(cycle_deg, int(comb_row[B_REF]))
    theta_local = wrap_angle_deg(theta_deg - ref_zero, cycle_deg)
    start_deg = comb_row[B_START]
    duration_deg = comb_row[B_DURATION]
    if duration_deg <= 1.0e-18:
        return 0.0
    if theta_local < start_deg or theta_local > start_deg + duration_deg:
        return 0.0
    x = (theta_local - start_deg) / duration_deg
    a = comb_row[B_A]
    m = comb_row[B_M]
    dxb_dx = a * (m + 1.0) * (x ** m) * math.exp(-a * (x ** (m + 1.0)))
    dxb_dtheta = dxb_dx / duration_deg
    q_total = comb_row[B_FUEL] * comb_row[B_LHV]
    return q_total * dxb_dtheta * dtheta_dt_deg_s


@nb.njit(cache=True)
def _evaporation_sink_rate(theta_deg: float, dtheta_dt_deg_s: float, evap_row: np.ndarray, cycle_deg: float) -> float:
    ref_zero = reference_zero_deg(cycle_deg, int(evap_row[E_REF]))
    theta_local = wrap_angle_deg(theta_deg - ref_zero, cycle_deg)
    start_deg = evap_row[E_START]
    duration_deg = evap_row[E_DURATION]
    if duration_deg <= 1.0e-18:
        return 0.0
    if theta_local < start_deg or theta_local > start_deg + duration_deg:
        return 0.0
    mass_rate_per_deg = evap_row[E_MASS] / duration_deg
    return mass_rate_per_deg * dtheta_dt_deg_s * evap_row[E_LATENT]




@nb.njit(cache=True)
def _gas_state_base_index(volume_index: int) -> int:
    return 5 * int(volume_index)


@nb.njit(cache=True)
def _gas_mass_from_state_vec(y: np.ndarray, volume_index: int) -> float:
    value = y[_gas_state_base_index(volume_index)]
    return value if value > 0.0 else 0.0


@nb.njit(cache=True)
def _burned_mass_from_state_vec(y: np.ndarray, volume_index: int) -> float:
    gas = _gas_mass_from_state_vec(y, volume_index)
    burned = y[_gas_state_base_index(volume_index) + 2]
    if burned <= 0.0:
        return 0.0
    if burned >= gas:
        return gas
    return burned


@nb.njit(cache=True)
def _air_mass_from_state_vec(y: np.ndarray, volume_index: int) -> float:
    gas = _gas_mass_from_state_vec(y, volume_index)
    burned = _burned_mass_from_state_vec(y, volume_index)
    air = y[_gas_state_base_index(volume_index) + 3]
    if air <= 0.0:
        return 0.0
    max_air = gas - burned
    if max_air <= 0.0:
        return 0.0
    if air >= max_air:
        return max_air
    return air


@nb.njit(cache=True)
def _fuel_vapor_mass_from_state_vec(y: np.ndarray, volume_index: int) -> float:
    gas = _gas_mass_from_state_vec(y, volume_index)
    burned = _burned_mass_from_state_vec(y, volume_index)
    air = _air_mass_from_state_vec(y, volume_index)
    vapor = gas - burned - air
    return vapor if vapor > 0.0 else 0.0


@nb.njit(cache=True)
def _upstream_species_fractions(y: np.ndarray, volume_index: int, environment_is_fixed: np.ndarray) -> tuple[float, float]:
    if int(environment_is_fixed[volume_index]) == 1:
        return 0.0, 1.0
    upstream_mass = _gas_mass_from_state_vec(y, volume_index)
    upstream_burned = _burned_mass_from_state_vec(y, volume_index)
    upstream_air = _air_mass_from_state_vec(y, volume_index)
    if upstream_mass <= 1.0e-18:
        return 0.0, 0.0
    burned_fraction = upstream_burned / upstream_mass
    air_fraction = upstream_air / upstream_mass
    if burned_fraction < 0.0:
        burned_fraction = 0.0
    elif burned_fraction > 1.0:
        burned_fraction = 1.0
    remaining = 1.0 - burned_fraction
    if air_fraction < 0.0:
        air_fraction = 0.0
    elif air_fraction > remaining:
        air_fraction = remaining
    return burned_fraction, air_fraction


@nb.njit(cache=True)
def rhs_thermo_numba(
    t: float,
    y: np.ndarray,
    vol_matrix: np.ndarray,
    kin_matrix: np.ndarray,
    conn_matrix: np.ndarray,
    wall_matrix: np.ndarray,
    comb_matrix: np.ndarray,
    evap_matrix: np.ndarray,
    lift_table: np.ndarray,
    alpha_table: np.ndarray,
    cd_table: np.ndarray,
    gas_props: np.ndarray,
    feature_flags: np.ndarray,
    wall_bore_by_vol: np.ndarray,
    wall_ups_by_vol: np.ndarray,
    wall_temperature_enabled: int,
    wall_temperature_state_index_by_vol: np.ndarray,
    wall_temperature_params_by_vol: np.ndarray,
    environment_is_fixed: np.ndarray,
    environment_pressures_pa: np.ndarray,
    environment_temperatures_K: np.ndarray,
    boundary_pressures_pa: np.ndarray,
    boundary_temperatures_K: np.ndarray,
    combustion_fuel_mass_by_vol: np.ndarray,
    combustion_afr_stoich_by_vol: np.ndarray,
    dt_s: float,
) -> np.ndarray:
    """Evaluate the full Thermo0D right-hand side.

    Per volume the thermodynamic state is ordered as
    ``[m_gas, U, m_burned, m_air, m_fuel_liquid]``.
    The gas-phase fuel vapor mass is reconstructed as
    ``m_gas - m_burned - m_air``.
    """
    cp_default = gas_props[0]
    cv_default = gas_props[1]
    gas_constant_default = gas_props[2]
    kappa_default = gas_props[3]
    use_promo_thermo = gas_props.shape[0] > 4 and gas_props[4] >= 0.5

    enable_mass = feature_flags.size > F_MASS and int(feature_flags[F_MASS]) == 1
    enable_wall = feature_flags.size > F_WALL and int(feature_flags[F_WALL]) == 1
    enable_comb = feature_flags.size > F_COMB and int(feature_flags[F_COMB]) == 1
    enable_evap = feature_flags.size > F_EVAP and int(feature_flags[F_EVAP]) == 1
    enable_pv = feature_flags.size > F_PV and int(feature_flags[F_PV]) == 1

    n_vol = vol_matrix.shape[0]
    dy = np.zeros_like(y)
    wall_temp_eff_by_vol = np.empty(0, dtype=np.float64)
    wall_area_eff_by_vol = np.empty(0, dtype=np.float64)
    if wall_temperature_enabled == 1:
        wall_temp_eff_by_vol = np.zeros(n_vol, dtype=np.float64)
        wall_area_eff_by_vol = np.zeros(n_vol, dtype=np.float64)
        for i in range(n_vol):
            wall_row_idx = int(vol_matrix[i, V_WALL])
            if wall_row_idx >= 0 and wall_row_idx < wall_matrix.shape[0]:
                wall_temp_eff_by_vol[i] = wall_matrix[wall_row_idx, W_TEMP]
                wall_area_eff_by_vol[i] = wall_matrix[wall_row_idx, W_AREA]
            if wall_temperature_state_index_by_vol.shape[0] > i:
                if wall_row_idx >= 0 and wall_row_idx < wall_matrix.shape[0]:
                    total_area = 0.0
                    weighted_temp = 0.0
                    for zone in range(WT_ZONE_COUNT):
                        wall_state_idx = int(wall_temperature_state_index_by_vol[i, zone])
                        if wall_state_idx >= 0 and wall_temperature_params_by_vol[i, zone, WT_ENABLED] > 0.5:
                            area = wall_temperature_params_by_vol[i, zone, WT_AREA]
                            total_area += area
                            weighted_temp += area * y[wall_state_idx]
                    if total_area > 1.0e-18:
                        wall_area_eff_by_vol[i] = total_area
                        wall_temp_eff_by_vol[i] = weighted_temp / total_area
    pressures = np.zeros(n_vol, dtype=np.float64)
    temperatures = np.zeros(n_vol, dtype=np.float64)
    volumes = np.zeros(n_vol, dtype=np.float64)
    dvdts = np.zeros(n_vol, dtype=np.float64)
    cp_by_vol = np.full(n_vol, cp_default, dtype=np.float64)
    cv_by_vol = np.full(n_vol, cv_default, dtype=np.float64)
    gas_constant_by_vol = np.full(n_vol, gas_constant_default, dtype=np.float64)
    kappa_by_vol = np.full(n_vol, kappa_default, dtype=np.float64)
    lambda_by_vol = np.full(n_vol, default_airlike_lambda(), dtype=np.float64)
    piston_x = np.zeros(n_vol, dtype=np.float64)
    theta_deg_by_vol = np.zeros(n_vol, dtype=np.float64)
    dtheta_dt_by_vol = np.zeros(n_vol, dtype=np.float64)
    cycle_deg_by_vol = np.full(n_vol, 360.0, dtype=np.float64)
    theta_global_deg_by_vol = np.zeros(n_vol, dtype=np.float64)
    mdot_in_by_vol = np.zeros(n_vol, dtype=np.float64)

    for i in range(n_vol):
        vol_row = vol_matrix[i]
        vol_type = int(vol_row[V_TYPE])
        is_fixed_environment = int(environment_is_fixed[i]) == 1 or vol_type == VOL_ENVIRONMENT
        base = _gas_state_base_index(i)
        mass_idx = base
        energy_idx = base + 1
        mass = _gas_mass_from_state_vec(y, i)
        energy = y[energy_idx]
        air_mass = _air_mass_from_state_vec(y, i)
        burned_mass = _burned_mass_from_state_vec(y, i)
        fuel_vapor_mass = _fuel_vapor_mass_from_state_vec(y, i)

        if vol_type == VOL_CYLINDER:
            kin_idx = int(vol_row[V_KIN_ROW])
            kin_row = kin_matrix[kin_idx]
            volume, dvdt, theta_deg, piston_pos, dtheta_dt_deg_s, cycle_deg = cylinder_kinematic_state_from_time(kin_row, t)
            theta_global_deg, _dtheta_global_dt_deg_s, _cycle_global_deg = global_theta_and_rate_from_time(t, kin_row)
            piston_x[i] = piston_pos
            theta_deg_by_vol[i] = theta_deg
            theta_global_deg_by_vol[i] = theta_global_deg
            dtheta_dt_by_vol[i] = dtheta_dt_deg_s
            cycle_deg_by_vol[i] = cycle_deg
            afr_stoich = combustion_afr_stoich_by_vol[i] if combustion_afr_stoich_by_vol.size > i else 14.5
            if use_promo_thermo:
                lambda_value = lambda_from_air_and_fuel_mass(air_mass, fuel_vapor_mass, afr_stoich)
                temp, cp_i, cv_i, gas_constant_i, kappa_i = properties_from_mass_energy_components_quellen(mass, energy, air_mass, fuel_vapor_mass, burned_mass, cv_default)
                press = safe_pressure_from_ideal_gas(mass, temp, gas_constant_i, volume)
                cp_by_vol[i] = cp_i
                cv_by_vol[i] = cv_i
                gas_constant_by_vol[i] = gas_constant_i
                kappa_by_vol[i] = kappa_i
                lambda_by_vol[i] = lambda_value
            else:
                temp = safe_temperature_from_state(mass, energy, cv_default)
                press = safe_pressure_from_ideal_gas(mass, temp, gas_constant_default, volume)
                cp_by_vol[i] = cp_default
                cv_by_vol[i] = cv_default
                gas_constant_by_vol[i] = gas_constant_default
                kappa_by_vol[i] = kappa_default
                lambda_by_vol[i] = default_airlike_lambda()
        elif is_fixed_environment:
            volume = max(vol_row[V_FIXED], 0.0)
            dvdt = 0.0
            temp = max(environment_temperatures_K[i], 1.0)
            press = max(environment_pressures_pa[i], 1.0)
            cp_by_vol[i] = cp_default
            cv_by_vol[i] = cv_default
            gas_constant_by_vol[i] = gas_constant_default
            kappa_by_vol[i] = kappa_default
            lambda_by_vol[i] = default_airlike_lambda()
        else:
            volume = vol_row[V_FIXED]
            dvdt = 0.0
            afr_stoich = combustion_afr_stoich_by_vol[i] if combustion_afr_stoich_by_vol.size > i else 14.5
            if use_promo_thermo:
                lambda_value = lambda_from_air_and_fuel_mass(air_mass, fuel_vapor_mass, afr_stoich)
                temp, cp_i, cv_i, gas_constant_i, kappa_i = properties_from_mass_energy_components_quellen(mass, energy, air_mass, fuel_vapor_mass, burned_mass, cv_default)
                press = safe_pressure_from_ideal_gas(mass, temp, gas_constant_i, volume)
                cp_by_vol[i] = cp_i
                cv_by_vol[i] = cv_i
                gas_constant_by_vol[i] = gas_constant_i
                kappa_by_vol[i] = kappa_i
                lambda_by_vol[i] = lambda_value
            else:
                temp = safe_temperature_from_state(mass, energy, cv_default)
                press = safe_pressure_from_ideal_gas(mass, temp, gas_constant_default, volume)
                cp_by_vol[i] = cp_default
                cv_by_vol[i] = cv_default
                gas_constant_by_vol[i] = gas_constant_default
                kappa_by_vol[i] = kappa_default
                lambda_by_vol[i] = default_airlike_lambda()

        temperatures[i] = temp
        pressures[i] = press
        volumes[i] = volume
        dvdts[i] = dvdt

    if enable_mass:
        for j in range(conn_matrix.shape[0]):
            conn = conn_matrix[j]
            left = int(conn[C_FROM])
            right = int(conn[C_TO])
            conn_type = int(conn[C_TYPE])
            left_kind = int(conn[C_FROM_KIND]) if conn.shape[0] > C_FROM_KIND else ENDPOINT_VOLUME
            right_kind = int(conn[C_TO_KIND]) if conn.shape[0] > C_TO_KIND else ENDPOINT_VOLUME
            left_is_volume = left_kind == ENDPOINT_VOLUME
            right_is_volume = right_kind == ENDPOINT_VOLUME
            p_left = pressures[left] if left_is_volume else max(boundary_pressures_pa[left], 1.0)
            t_left = temperatures[left] if left_is_volume else max(boundary_temperatures_K[left], 1.0)
            p_right = pressures[right] if right_is_volume else max(boundary_pressures_pa[right], 1.0)
            t_right = temperatures[right] if right_is_volume else max(boundary_temperatures_K[right], 1.0)

            if conn_type == CONN_VALVE or conn_type == CONN_SLOT:
                if left_is_volume and int(vol_matrix[left, V_TYPE]) == VOL_CYLINDER:
                    cyl_idx = left
                elif right_is_volume and int(vol_matrix[right, V_TYPE]) == VOL_CYLINDER:
                    cyl_idx = right
                else:
                    continue
                area, cd_f, cd_r = _connection_area_and_coefficients(
                    conn,
                    conn_type,
                    theta_deg_by_vol[cyl_idx],
                    theta_global_deg_by_vol[cyl_idx],
                    cycle_deg_by_vol[cyl_idx],
                    piston_x[cyl_idx],
                    lift_table,
                    alpha_table,
                    cd_table,
                )
            elif conn_type == CONN_ORIFICE:
                area, cd_f, cd_r = _evaluate_orifice_area(conn)
            elif conn_type == CONN_CHECK_VALVE:
                area, cd_f, cd_r = _evaluate_check_valve_area(conn, p_left, p_right)
            else:
                continue

            if area <= 1.0e-18 or (cd_f <= 0.0 and cd_r <= 0.0):
                continue

            if p_left >= p_right:
                gamma_up = kappa_by_vol[left] if left_is_volume else kappa_default
                gas_constant_up = gas_constant_by_vol[left] if left_is_volume else gas_constant_default
                cp_up = cp_by_vol[left] if left_is_volume else cp_default
                temp_up = t_left
            else:
                gamma_up = kappa_by_vol[right] if right_is_volume else kappa_default
                gas_constant_up = gas_constant_by_vol[right] if right_is_volume else gas_constant_default
                cp_up = cp_by_vol[right] if right_is_volume else cp_default
                temp_up = t_right
            mdot = de_st_venant_wantzel_signed(
                p_left,
                t_left,
                p_right,
                t_right,
                area,
                cd_f,
                cd_r,
                gamma_up,
                gas_constant_up,
            )
            h_up = cp_up * temp_up

            left_m = _gas_state_base_index(left)
            left_u = left_m + 1
            left_b = left_m + 2
            left_a = left_m + 3
            left_l = left_m + 4
            right_m = _gas_state_base_index(right)
            right_u = right_m + 1
            right_b = right_m + 2
            right_a = right_m + 3
            right_l = right_m + 4
            _ = (left_l, right_l)

            if left_is_volume and int(environment_is_fixed[left]) != 1:
                dy[left_m] -= mdot
                dy[left_u] -= mdot * h_up
            if right_is_volume and int(environment_is_fixed[right]) != 1:
                dy[right_m] += mdot
                dy[right_u] += mdot * h_up

            if mdot >= 0.0:
                if left_is_volume:
                    upstream_burned_fraction, upstream_air_fraction = _upstream_species_fractions(y, left, environment_is_fixed)
                else:
                    upstream_burned_fraction, upstream_air_fraction = 0.0, 1.0
                burned_transfer = mdot * upstream_burned_fraction
                air_transfer = mdot * upstream_air_fraction
                if left_is_volume and int(environment_is_fixed[left]) != 1:
                    dy[left_b] -= burned_transfer
                    dy[left_a] -= air_transfer
                if right_is_volume and int(environment_is_fixed[right]) != 1:
                    dy[right_b] += burned_transfer
                    dy[right_a] += air_transfer
            else:
                if right_is_volume:
                    upstream_burned_fraction, upstream_air_fraction = _upstream_species_fractions(y, right, environment_is_fixed)
                else:
                    upstream_burned_fraction, upstream_air_fraction = 0.0, 1.0
                burned_transfer = (-mdot) * upstream_burned_fraction
                air_transfer = (-mdot) * upstream_air_fraction
                if left_is_volume and int(environment_is_fixed[left]) != 1:
                    dy[left_b] += burned_transfer
                    dy[left_a] += air_transfer
                if right_is_volume and int(environment_is_fixed[right]) != 1:
                    dy[right_b] -= burned_transfer
                    dy[right_a] -= air_transfer

            if left_is_volume and int(vol_matrix[left, V_TYPE]) == VOL_CYLINDER and mdot < 0.0:
                mdot_in_by_vol[left] += -mdot
            if right_is_volume and int(vol_matrix[right, V_TYPE]) == VOL_CYLINDER and mdot > 0.0:
                mdot_in_by_vol[right] += mdot

    for i in range(n_vol):
        vol_row = vol_matrix[i]
        vol_type = int(vol_row[V_TYPE])
        base = _gas_state_base_index(i)
        mass_idx = base
        energy_idx = base + 1
        burned_idx = base + 2
        air_idx = base + 3
        liquid_idx = base + 4
        if int(environment_is_fixed[i]) == 1 or vol_type == VOL_ENVIRONMENT:
            dy[mass_idx] = 0.0
            dy[energy_idx] = 0.0
            dy[burned_idx] = 0.0
            dy[air_idx] = 0.0
            dy[liquid_idx] = 0.0
            continue

        theta_deg = theta_deg_by_vol[i]
        dtheta_dt_deg_s = dtheta_dt_by_vol[i]
        cycle_deg = cycle_deg_by_vol[i]
        pdv_power, qdot_wall, htc_wall, _wall_velocity, qdot_comb, qdot_evap = volume_energy_source_terms(
            vol_type,
            int(vol_row[V_WALL]),
            int(vol_row[V_COMB]),
            int(vol_row[V_EVAP]),
            1 if enable_wall else 0,
            1 if enable_comb else 0,
            1 if enable_evap else 0,
            1 if enable_pv else 0,
            wall_matrix,
            comb_matrix,
            evap_matrix,
            wall_bore_by_vol[i],
            wall_ups_by_vol[i],
            pressures[i],
            temperatures[i],
            volumes[i],
            _gas_mass_from_state_vec(y, i),
            mdot_in_by_vol[i],
            dvdts[i],
            theta_deg,
            theta_global_deg_by_vol[i],
            dtheta_dt_deg_s,
            dtheta_dt_deg_s,
            cycle_deg,
        )
        if wall_temperature_enabled == 1 and enable_wall and int(vol_row[V_WALL]) >= 0 and wall_area_eff_by_vol[i] > 0.0:
            qdot_wall = htc_wall * wall_area_eff_by_vol[i] * (wall_temp_eff_by_vol[i] - temperatures[i])
        dy[energy_idx] = dy[energy_idx] - pdv_power + qdot_wall + qdot_comb - qdot_evap

        evap_idx = int(vol_row[V_EVAP])
        if vol_type == VOL_CYLINDER and enable_evap and evap_idx >= 0 and qdot_evap > 0.0:
            latent = evap_matrix[evap_idx, E_LATENT]
            if latent > 1.0e-18 and y[liquid_idx] > 0.0:
                evap_mdot = qdot_evap / latent
                dy[liquid_idx] -= evap_mdot
                dy[mass_idx] += evap_mdot

        comb_idx = int(vol_row[V_COMB])
        if vol_type == VOL_CYLINDER and enable_comb and comb_idx >= 0 and qdot_comb > 0.0:
            comb_row = comb_matrix[comb_idx]
            if _comb_duration_mode_from_row(comb_row) != DURATION_MODE_TIME:
                xb, dxb_dt = vibe_fraction_and_rate_numba(
                    theta_deg,
                    theta_global_deg_by_vol[i],
                    dtheta_dt_deg_s,
                    dtheta_dt_deg_s,
                    comb_row[B_START],
                    comb_row[B_DURATION],
                    comb_row[B_A],
                    comb_row[B_M],
                    int(comb_row[B_REF]),
                    cycle_deg,
                )
                burn_rate_requested = combustion_conversion_rate_kg_per_s(_gas_mass_from_state_vec(y, i), _burned_mass_from_state_vec(y, i), xb, dxb_dt)
                unburned_mass = _gas_mass_from_state_vec(y, i) - _burned_mass_from_state_vec(y, i)
                air_mass = _air_mass_from_state_vec(y, i)
                vapor_mass = _fuel_vapor_mass_from_state_vec(y, i)
                lhv = comb_row[B_LHV]
                afr_stoich = combustion_afr_stoich_by_vol[i] if combustion_afr_stoich_by_vol.size > i else 14.5
                if unburned_mass > 1.0e-18 and burn_rate_requested > 0.0 and lhv > 1.0e-18 and afr_stoich > 1.0e-18:
                    if dt_s > 1.0e-18:
                        max_total_burn_rate_from_fuel_inventory = vapor_mass * (1.0 + afr_stoich) / dt_s
                        max_total_burn_rate_from_air_inventory = air_mass * (1.0 + 1.0 / afr_stoich) / dt_s
                        max_total_burn_rate_from_unburned_inventory = unburned_mass / dt_s
                    else:
                        max_total_burn_rate_from_fuel_inventory = burn_rate_requested
                        max_total_burn_rate_from_air_inventory = burn_rate_requested
                        max_total_burn_rate_from_unburned_inventory = burn_rate_requested
                    max_total_burn_rate_from_energy = (qdot_comb / lhv) * (1.0 + afr_stoich)
                    burn_rate = min(
                        burn_rate_requested,
                        max_total_burn_rate_from_energy,
                        max_total_burn_rate_from_fuel_inventory,
                        max_total_burn_rate_from_air_inventory,
                        max_total_burn_rate_from_unburned_inventory,
                    )
                    if burn_rate > 0.0:
                        fuel_consumption_rate = burn_rate / (1.0 + afr_stoich)
                        air_consumption_rate = burn_rate - fuel_consumption_rate
                        qdot_comb = fuel_consumption_rate * lhv
                        dy[energy_idx] = dy[energy_idx] - pdv_power + qdot_wall + qdot_comb - qdot_evap
                        dy[burned_idx] += burn_rate
                        dy[air_idx] -= air_consumption_rate

    return dy


def _safe_state_for_jacobian(mass: float, energy: float, cv: float, gas_constant: float, volume: float) -> tuple[float, float, float, float, float]:
    mass_eff = max(float(mass), 1.0e-18)
    energy_eff = max(float(energy), mass_eff * cv * 1.0)
    temp = energy_eff / (mass_eff * cv)
    pressure = mass_eff * gas_constant * temp / max(float(volume), 1.0e-18)
    dtemp_dm = -temp / mass_eff
    dtemp_dU = 1.0 / (mass_eff * cv)
    dp_dm = 0.0
    dp_dU = gas_constant / (cv * max(float(volume), 1.0e-18))
    return temp, pressure, dtemp_dm, dtemp_dU, dp_dU


def _subcritical_phi_and_derivative(pr: float, kappa: float) -> tuple[float, float]:
    c = 2.0 * kappa / (kappa - 1.0)
    a = 2.0 / kappa
    b = (kappa + 1.0) / kappa
    term = (pr ** a) - (pr ** b)
    term = max(term, 0.0)
    phi = math.sqrt(c * term)
    if phi <= 1.0e-30:
        return phi, 0.0
    dterm = a * (pr ** (a - 1.0)) - b * (pr ** (b - 1.0))
    dphi = 0.5 * c * dterm / phi
    return phi, dphi


def _connection_effective_areas_py(conn: np.ndarray, conn_type: int, theta_deg: float, theta_global_deg: float, cycle_deg: float, piston_x: float, lift_table: np.ndarray, alpha_table: np.ndarray, cd_table: np.ndarray) -> tuple[float, float]:
    if conn_type == ConnectionType.VALVE:
        _lift, _bore_area, area_forward, area_reverse, _alpha_forward, _alpha_reverse = _evaluate_valve_state(conn, theta_deg, theta_global_deg, cycle_deg, lift_table, alpha_table)
        return float(area_forward), float(area_reverse)
    if conn_type == ConnectionType.SLOT:
        _uncovered, _geom_area, area_forward, area_reverse, _cd_f, _cd_r = _evaluate_slot_state(conn, piston_x, cd_table)
        return float(area_forward), float(area_reverse)
    if conn_type == ConnectionType.ORIFICE:
        area, cd_f, cd_r = _evaluate_orifice_area(conn)
        return float(area * cd_f), float(area * cd_r)
    return 0.0, 0.0


def analytic_flow_energy_jacobian(bundle, t: float, y: np.ndarray) -> np.ndarray:
    """Return analytic Jacobian contributions from connection mass/energy flow.

    This covers the signed isentropic flow term and the coupled transported
    enthalpy term ``mdot * h_u``. Remaining source terms are intentionally
    excluded and can be added by finite differences in the hybrid Jacobian path.
    """
    b = bundle
    cp, cv, gas_constant, kappa = [float(v) for v in b.gas_props]
    environment_is_fixed = getattr(b, "environment_is_fixed", None)
    environment_pressures_pa = getattr(b, "environment_pressures_pa", None)
    environment_temperatures_K = getattr(b, "environment_temperatures_K", None)
    boundary_pressures_pa = getattr(b, "boundary_pressures_pa", None)
    boundary_temperatures_K = getattr(b, "boundary_temperatures_K", None)
    if environment_is_fixed is None:
        environment_is_fixed = np.zeros(b.vol_matrix.shape[0], dtype=np.int64)
    if environment_pressures_pa is None:
        environment_pressures_pa = np.zeros(b.vol_matrix.shape[0], dtype=np.float64)
    if environment_temperatures_K is None:
        environment_temperatures_K = np.zeros(b.vol_matrix.shape[0], dtype=np.float64)
    if boundary_pressures_pa is None:
        boundary_pressures_pa = np.zeros(0, dtype=np.float64)
    if boundary_temperatures_K is None:
        boundary_temperatures_K = np.zeros(0, dtype=np.float64)
    n_vol = b.vol_matrix.shape[0]
    jac = np.zeros((y.size, y.size), dtype=np.float64)
    if b.feature_flags.size <= F_MASS or int(b.feature_flags[F_MASS]) != 1:
        return jac

    volumes = np.zeros(n_vol, dtype=np.float64)
    piston_x = np.zeros(n_vol, dtype=np.float64)
    theta_deg_by_vol = np.zeros(n_vol, dtype=np.float64)
    cycle_deg_by_vol = np.full(n_vol, 360.0, dtype=np.float64)
    theta_global_deg_by_vol = np.zeros(n_vol, dtype=np.float64)
    temps = np.zeros(n_vol, dtype=np.float64)
    press = np.zeros(n_vol, dtype=np.float64)
    dTdm = np.zeros(n_vol, dtype=np.float64)
    dTdU = np.zeros(n_vol, dtype=np.float64)
    dpdU = np.zeros(n_vol, dtype=np.float64)

    for i in range(n_vol):
        mass = float(y[2 * i])
        energy = float(y[2 * i + 1])
        vol_type = int(b.vol_matrix[i, V_TYPE])
        if vol_type == VolumeType.CYLINDER:
            kin_idx = int(b.vol_matrix[i, V_KIN_ROW])
            volume, _dvdt, theta_deg, piston_pos, _dtheta_dt_deg_s, cycle_deg = cylinder_kinematic_state_from_time(b.kin_matrix[kin_idx], float(t))
            theta_global_deg, _dtheta_global_dt_deg_s, _cycle_global_deg = global_theta_and_rate_from_time(float(t), b.kin_matrix[kin_idx])
            piston_x[i] = piston_pos
            theta_deg_by_vol[i] = theta_deg
            theta_global_deg_by_vol[i] = theta_global_deg
            cycle_deg_by_vol[i] = cycle_deg
            temp, pressure, dtemp_dm, dtemp_dU, dp_dU_i = _safe_state_for_jacobian(mass, energy, cv, gas_constant, volume)
        elif int(environment_is_fixed[i]) == 1 or vol_type == VolumeType.ENVIRONMENT:
            volume = float(b.vol_matrix[i, V_FIXED])
            piston_x[i] = 0.0
            temp = max(float(environment_temperatures_K[i]), 1.0)
            pressure = max(float(environment_pressures_pa[i]), 1.0)
            dtemp_dm = 0.0
            dtemp_dU = 0.0
            dp_dU_i = 0.0
        else:
            volume = float(b.vol_matrix[i, V_FIXED])
            piston_x[i] = 0.0
            temp, pressure, dtemp_dm, dtemp_dU, dp_dU_i = _safe_state_for_jacobian(mass, energy, cv, gas_constant, volume)
        volumes[i] = volume
        temps[i] = temp
        press[i] = pressure
        dTdm[i] = dtemp_dm
        dTdU[i] = dtemp_dU
        dpdU[i] = dp_dU_i

    crit = (2.0 / (kappa + 1.0)) ** (kappa / (kappa - 1.0))
    phi_crit = math.sqrt(kappa * (2.0 / (kappa + 1.0)) ** ((kappa + 1.0) / (kappa - 1.0)))

    for j in range(b.conn_matrix.shape[0]):
        conn = b.conn_matrix[j]
        left = int(conn[C_FROM])
        right = int(conn[C_TO])
        conn_type = int(conn[C_TYPE])
        left_kind = int(conn[C_FROM_KIND]) if conn.shape[0] > C_FROM_KIND else ENDPOINT_VOLUME
        right_kind = int(conn[C_TO_KIND]) if conn.shape[0] > C_TO_KIND else ENDPOINT_VOLUME
        left_is_volume = left_kind == ENDPOINT_VOLUME
        right_is_volume = right_kind == ENDPOINT_VOLUME
        cyl_idx = -1
        if left_is_volume and int(b.vol_matrix[left, V_TYPE]) == VolumeType.CYLINDER:
            cyl_idx = left
        elif right_is_volume and int(b.vol_matrix[right, V_TYPE]) == VolumeType.CYLINDER:
            cyl_idx = right
        if conn_type in (ConnectionType.VALVE, ConnectionType.SLOT) and cyl_idx < 0:
            continue
        aeff_f, aeff_r = _connection_effective_areas_py(
            conn,
            conn_type,
            float(theta_deg_by_vol[cyl_idx]),
            float(theta_global_deg_by_vol[cyl_idx]),
            float(cycle_deg_by_vol[cyl_idx]),
            float(piston_x[cyl_idx]),
            b.lift_table,
            b.alpha_table,
            b.cd_table,
        )
        p_left = press[left] if left_is_volume else max(float(boundary_pressures_pa[left]), 1.0)
        p_right = press[right] if right_is_volume else max(float(boundary_pressures_pa[right]), 1.0)
        t_left = temps[left] if left_is_volume else max(float(boundary_temperatures_K[left]), 1.0)
        t_right = temps[right] if right_is_volume else max(float(boundary_temperatures_K[right]), 1.0)

        if aeff_f <= 0.0 and aeff_r <= 0.0:
            continue

        if p_left >= p_right:
            sign = 1.0
            aeff = aeff_f
            up = left
            down = right
        else:
            sign = -1.0
            aeff = aeff_r
            up = right
            down = left
        if aeff <= 0.0:
            continue

        p_up = p_left if up == left else p_right
        p_down = p_right if up == left else p_left
        t_up = t_left if up == left else t_right
        if p_up <= 0.0 or t_up <= 0.0:
            continue
        pr = max(0.0, min(1.0, p_down / p_up))
        if pr <= crit:
            phi = phi_crit
            dphi_dpr = 0.0
        else:
            phi, dphi_dpr = _subcritical_phi_and_derivative(pr, kappa)

        sqrt_rt = math.sqrt(gas_constant * t_up)
        mdot = sign * aeff * p_up / sqrt_rt * phi
        h_up = cp * t_up

        coeff_up_p = sign * aeff / sqrt_rt * (phi - pr * dphi_dpr)
        coeff_down_p = sign * aeff / sqrt_rt * dphi_dpr
        coeff_up_t = sign * aeff * (-0.5) * p_up * phi / (sqrt_rt * t_up)

        dmdot = {2 * left: 0.0, 2 * left + 1: 0.0, 2 * right: 0.0, 2 * right + 1: 0.0}
        if (up == left and left_is_volume) or (up == right and right_is_volume):
            dmdot[2 * up] += coeff_up_t * dTdm[up]
            dmdot[2 * up + 1] += coeff_up_p * dpdU[up] + coeff_up_t * dTdU[up]
        if (down == left and left_is_volume) or (down == right and right_is_volume):
            dmdot[2 * down + 1] += coeff_down_p * dpdU[down]

        dh_up = {2 * left: 0.0, 2 * left + 1: 0.0, 2 * right: 0.0, 2 * right + 1: 0.0}
        if (up == left and left_is_volume) or (up == right and right_is_volume):
            dh_up[2 * up] = cp * dTdm[up]
            dh_up[2 * up + 1] = cp * dTdU[up]

        left_fixed = (not left_is_volume) or int(environment_is_fixed[left]) == 1
        right_fixed = (not right_is_volume) or int(environment_is_fixed[right]) == 1
        for col, dmd in dmdot.items():
            if dmd == 0.0 and dh_up[col] == 0.0:
                continue
            ed = h_up * dmd + mdot * dh_up[col]
            if not left_fixed:
                jac[2 * left, col] -= dmd
                jac[2 * left + 1, col] -= ed
            if not right_fixed:
                jac[2 * right, col] += dmd
                jac[2 * right + 1, col] += ed
    return jac


class RHSWrapper:
    """Python-side adapter around the Numba RHS and Jacobian helpers."""

    def __init__(self, bundle):
        self.bundle = bundle
        self._feature_flags_nonflow = bundle.feature_flags.copy()
        if self._feature_flags_nonflow.size > F_MASS:
            self._feature_flags_nonflow[F_MASS] = 0.0
        self._wall_bore_by_vol = bundle.wall_bore_by_vol if getattr(bundle, 'wall_bore_by_vol', None) is not None else np.zeros(bundle.vol_matrix.shape[0], dtype=np.float64)
        self._wall_ups_by_vol = bundle.wall_ups_by_vol if getattr(bundle, 'wall_ups_by_vol', None) is not None else np.zeros(bundle.vol_matrix.shape[0], dtype=np.float64)
        self._environment_is_fixed = bundle.environment_is_fixed if bundle.environment_is_fixed is not None else np.zeros(bundle.vol_matrix.shape[0], dtype=np.int64)
        self._environment_pressures_pa = bundle.environment_pressures_pa if bundle.environment_pressures_pa is not None else np.zeros(bundle.vol_matrix.shape[0], dtype=np.float64)
        self._environment_temperatures_K = bundle.environment_temperatures_K if bundle.environment_temperatures_K is not None else np.zeros(bundle.vol_matrix.shape[0], dtype=np.float64)
        self._boundary_pressures_pa = bundle.boundary_pressures_pa if getattr(bundle, 'boundary_pressures_pa', None) is not None else np.zeros(0, dtype=np.float64)
        self._boundary_temperatures_K = bundle.boundary_temperatures_K if getattr(bundle, 'boundary_temperatures_K', None) is not None else np.zeros(0, dtype=np.float64)
        self._combustion_fuel_mass_by_vol = bundle.combustion_fuel_mass_by_vol if getattr(bundle, 'combustion_fuel_mass_by_vol', None) is not None else np.zeros(bundle.vol_matrix.shape[0], dtype=np.float64)
        self._combustion_afr_stoich_by_vol = bundle.combustion_afr_stoich_by_vol if getattr(bundle, 'combustion_afr_stoich_by_vol', None) is not None else np.full(bundle.vol_matrix.shape[0], 14.5, dtype=np.float64)
        self._wall_temperature_state_index_by_vol = (
            bundle.wall_temperature_state_index_by_vol
            if getattr(bundle, 'wall_temperature_state_index_by_vol', None) is not None
            else np.full((bundle.vol_matrix.shape[0], WT_ZONE_COUNT), -1, dtype=np.int64)
        )
        self._wall_temperature_params_by_vol = (
            bundle.wall_temperature_params_by_vol
            if getattr(bundle, 'wall_temperature_params_by_vol', None) is not None
            else np.zeros((bundle.vol_matrix.shape[0], WT_ZONE_COUNT, len(WallTemperatureCol)), dtype=np.float64)
        )
        self._wall_temperature_enabled = 1 if bool(getattr(bundle, 'wall_temperature_enabled', False)) else 0

    def __call__(self, t: float, y: np.ndarray) -> np.ndarray:
        b = self.bundle
        return rhs_thermo_numba(
            t,
            y,
            b.vol_matrix,
            b.kin_matrix,
            b.conn_matrix,
            b.wall_matrix,
            b.comb_matrix,
            b.evap_matrix,
            b.lift_table,
            b.alpha_table,
            b.cd_table,
            b.gas_props,
            b.feature_flags,
            self._wall_bore_by_vol,
            self._wall_ups_by_vol,
            self._wall_temperature_enabled,
            self._wall_temperature_state_index_by_vol,
            self._wall_temperature_params_by_vol,
            self._environment_is_fixed,
            self._environment_pressures_pa,
            self._environment_temperatures_K,
            self._boundary_pressures_pa,
            self._boundary_temperatures_K,
            self._combustion_fuel_mass_by_vol,
            self._combustion_afr_stoich_by_vol,
            float(getattr(b.simulation, 'dt_s', 0.0) or 0.0),
        )

    def rhs_nonflow(self, t: float, y: np.ndarray) -> np.ndarray:
        b = self.bundle
        return rhs_thermo_numba(
            t,
            y,
            b.vol_matrix,
            b.kin_matrix,
            b.conn_matrix,
            b.wall_matrix,
            b.comb_matrix,
            b.evap_matrix,
            b.lift_table,
            b.alpha_table,
            b.cd_table,
            b.gas_props,
            self._feature_flags_nonflow,
            self._wall_bore_by_vol,
            self._wall_ups_by_vol,
            self._wall_temperature_enabled,
            self._wall_temperature_state_index_by_vol,
            self._wall_temperature_params_by_vol,
            self._environment_is_fixed,
            self._environment_pressures_pa,
            self._environment_temperatures_K,
            self._boundary_pressures_pa,
            self._boundary_temperatures_K,
            self._combustion_fuel_mass_by_vol,
            self._combustion_afr_stoich_by_vol,
            float(getattr(b.simulation, 'dt_s', 0.0) or 0.0),
        )

    def jacobian_flow_analytic(self, t: float, y: np.ndarray) -> np.ndarray:
        if y.size != 2 * int(self.bundle.vol_matrix.shape[0]):
            return np.zeros((y.size, y.size), dtype=np.float64)
        return analytic_flow_energy_jacobian(self.bundle, t, y)

    def jacobian(self, t: float, y: np.ndarray, eps: float = 1.0e-8) -> np.ndarray:
        if y.size != 2 * int(self.bundle.vol_matrix.shape[0]):
            return finite_difference_jacobian(self, t, y, eps=eps, sparsity=self.bundle.jac_sparsity)
        jac = self.jacobian_flow_analytic(t, y)
        if np.any(self._feature_flags_nonflow != 0.0):
            jac += finite_difference_jacobian(self.rhs_nonflow, t, y, eps=eps, sparsity=self.bundle.jac_sparsity)
        return jac

    def jacobian_fd(self, t: float, y: np.ndarray, eps: float = 1.0e-8) -> np.ndarray:
        return finite_difference_jacobian(self, t, y, eps=eps, sparsity=self.bundle.jac_sparsity)
