"""Combustion source-term models for Thermo0D."""

from __future__ import annotations

import math

import numba as nb
import numpy as np

from thermo0d.config.constants import AngleReference, CombCol, CombDurationMode, CombustionModel
from thermo0d.physics.kinematics import reference_theta_and_zero, wrap_angle_deg

B_MODEL = int(CombCol.MODEL)
B_START = int(CombCol.START_DEG)
B_DURATION = int(CombCol.DURATION_DEG)
B_A = int(CombCol.A)
B_M = int(CombCol.M)
B_FUEL = int(CombCol.FUEL_MASS_PER_CYCLE)
B_LHV = int(CombCol.LHV)
B_REF = int(CombCol.REF_TYPE)
B_START_MODE = int(CombCol.START_MODE)
B_DURATION_MODE = int(CombCol.DURATION_MODE)

MODEL_VIBE = int(CombustionModel.VIBE)
REF_ABSOLUTE = int(AngleReference.ABSOLUTE)
DURATION_MODE_ANGLE = int(CombDurationMode.ANGLE)
DURATION_MODE_COMPRESSION_HUB = int(CombDurationMode.COMPRESSION_HUB)
DURATION_MODE_TIME = int(CombDurationMode.TIME)


@nb.njit(cache=True)
def _comb_duration_mode_from_row(comb_row: np.ndarray) -> int:
    if comb_row.shape[0] <= B_DURATION_MODE:
        return DURATION_MODE_ANGLE
    mode = int(comb_row[B_DURATION_MODE])
    if mode == DURATION_MODE_COMPRESSION_HUB or mode == DURATION_MODE_TIME:
        return mode
    return DURATION_MODE_ANGLE


@nb.njit(cache=True)
def wrapped_window_progress(theta_deg: float, start_deg: float, duration_deg: float, cycle_deg: float) -> float:
    if duration_deg <= 1.0e-18:
        return -1.0
    if duration_deg >= cycle_deg:
        return 0.0
    delta = wrap_angle_deg(theta_deg - start_deg, cycle_deg)
    if delta > duration_deg:
        return -1.0
    return delta / duration_deg


@nb.njit(cache=True)
def _vibe_cumulative_fraction(progress_0to1: float, a: float, m: float) -> float:
    x = min(max(progress_0to1, 0.0), 1.0)
    return 1.0 - math.exp(-a * (x ** (m + 1.0)))


@nb.njit(cache=True)
def _vibe_fraction_derivative_per_progress(progress_0to1: float, a: float, m: float) -> float:
    x = min(max(progress_0to1, 0.0), 1.0)
    return a * (m + 1.0) * (x ** m) * math.exp(-a * (x ** (m + 1.0)))


@nb.njit(cache=True)
def vibe_fraction_and_rate_numba(
    theta_local_deg: float,
    theta_global_deg: float,
    dtheta_local_dt_deg_s: float,
    dtheta_global_dt_deg_s: float,
    start_deg: float,
    duration_deg: float,
    a: float,
    m: float,
    ref_type: int,
    cycle_deg: float,
) -> tuple[float, float]:
    if duration_deg <= 1.0e-18:
        return 0.0, 0.0
    theta_ref_deg, ref_zero_deg = reference_theta_and_zero(
        theta_local_deg,
        theta_global_deg,
        cycle_deg,
        ref_type,
    )
    theta_window_deg = wrap_angle_deg(theta_ref_deg - ref_zero_deg, cycle_deg)
    delta = wrap_angle_deg(theta_window_deg - start_deg, cycle_deg)
    dtheta_ref_dt_deg_s = dtheta_global_dt_deg_s if ref_type == REF_ABSOLUTE else dtheta_local_dt_deg_s
    if delta < 0.0:
        return 0.0, 0.0
    if delta >= duration_deg:
        return 1.0, 0.0
    progress = delta / duration_deg
    xb = _vibe_cumulative_fraction(progress, a, m)
    dxb_dtheta = _vibe_fraction_derivative_per_progress(progress, a, m) / duration_deg
    return xb, dxb_dtheta * dtheta_ref_dt_deg_s


@nb.njit(cache=True)
def vibe_time_fraction_and_rate_numba(
    t_s: float,
    soc_time_s: float,
    duration_s: float,
    a: float,
    m: float,
) -> tuple[float, float]:
    if duration_s <= 1.0e-18:
        return 0.0, 0.0
    tau = (t_s - soc_time_s) / duration_s
    if tau < 0.0:
        return 0.0, 0.0
    if tau >= 1.0:
        return 1.0, 0.0
    xb = _vibe_cumulative_fraction(tau, a, m)
    dxb_dt = _vibe_fraction_derivative_per_progress(tau, a, m) / duration_s
    return xb, dxb_dt


@nb.njit(cache=True)
def _vibe_heat_release_rate_impl(
    theta_local_deg: float,
    theta_global_deg: float,
    dtheta_local_dt_deg_s: float,
    dtheta_global_dt_deg_s: float,
    comb_row: np.ndarray,
    cycle_deg: float,
) -> float:
    if int(comb_row[B_MODEL]) != MODEL_VIBE:
        return 0.0
    if _comb_duration_mode_from_row(comb_row) == DURATION_MODE_TIME:
        return 0.0
    xb, dxb_dt = vibe_fraction_and_rate_numba(
        theta_local_deg,
        theta_global_deg,
        dtheta_local_dt_deg_s,
        dtheta_global_dt_deg_s,
        comb_row[B_START],
        comb_row[B_DURATION],
        comb_row[B_A],
        comb_row[B_M],
        int(comb_row[B_REF]),
        cycle_deg,
    )
    _ = xb
    q_total = comb_row[B_FUEL] * comb_row[B_LHV]
    return q_total * dxb_dt


def vibe_heat_release_rate(*args) -> float:
    """Compatibility wrapper.

    Supported signatures:
    - (theta_local_deg, theta_global_deg, dtheta_local_dt_deg_s, dtheta_global_dt_deg_s, comb_row, cycle_deg)
    - (theta_local_deg, theta_global_deg, dtheta_local_dt_deg_s, comb_row, cycle_deg)
      -> uses local angle rate for the reference rate as legacy behavior.
    """
    if len(args) == 6:
        theta_local_deg, theta_global_deg, dtheta_local_dt_deg_s, dtheta_global_dt_deg_s, comb_row, cycle_deg = args
    elif len(args) == 5:
        theta_local_deg, theta_global_deg, dtheta_local_dt_deg_s, comb_row, cycle_deg = args
        dtheta_global_dt_deg_s = dtheta_local_dt_deg_s
    else:
        raise TypeError("vibe_heat_release_rate expects 5 or 6 positional arguments")
    return _vibe_heat_release_rate_impl(
        float(theta_local_deg),
        float(theta_global_deg),
        float(dtheta_local_dt_deg_s),
        float(dtheta_global_dt_deg_s),
        np.asarray(comb_row, dtype=np.float64),
        float(cycle_deg),
    )


vibe_heat_release_rate.py_func = vibe_heat_release_rate


@nb.njit(cache=True)
def vibe_heat_release_rate_with_total_energy_numba(
    theta_local_deg: float,
    theta_global_deg: float,
    dtheta_local_dt_deg_s: float,
    dtheta_global_dt_deg_s: float,
    start_deg: float,
    duration_deg: float,
    a: float,
    m: float,
    q_total_J: float,
    ref_type: int,
    cycle_deg: float,
) -> float:
    if q_total_J <= 0.0:
        return 0.0
    _xb, dxb_dt = vibe_fraction_and_rate_numba(
        theta_local_deg,
        theta_global_deg,
        dtheta_local_dt_deg_s,
        dtheta_global_dt_deg_s,
        start_deg,
        duration_deg,
        a,
        m,
        ref_type,
        cycle_deg,
    )
    return q_total_J * dxb_dt


def vibe_heat_release_rate_with_total_energy(
    theta_local_deg: float,
    theta_global_deg: float,
    dtheta_local_dt_deg_s: float,
    dtheta_global_dt_deg_s: float,
    start_deg: float,
    duration_deg: float,
    a: float,
    m: float,
    q_total_J: float,
    ref_type: int,
    cycle_deg: float,
) -> float:
    return vibe_heat_release_rate_with_total_energy_numba(
        float(theta_local_deg),
        float(theta_global_deg),
        float(dtheta_local_dt_deg_s),
        float(dtheta_global_dt_deg_s),
        float(start_deg),
        float(duration_deg),
        float(a),
        float(m),
        float(q_total_J),
        int(ref_type),
        float(cycle_deg),
    )


@nb.njit(cache=True)
def vibe_time_heat_release_rate_with_total_energy_numba(
    t_s: float,
    soc_time_s: float,
    duration_s: float,
    a: float,
    m: float,
    q_total_J: float,
) -> float:
    if q_total_J <= 0.0 or duration_s <= 1.0e-18:
        return 0.0
    _xb, dxb_dt = vibe_time_fraction_and_rate_numba(
        t_s,
        soc_time_s,
        duration_s,
        a,
        m,
    )
    return q_total_J * dxb_dt


def vibe_time_heat_release_rate_with_total_energy(
    t_s: float,
    soc_time_s: float,
    duration_s: float,
    a: float,
    m: float,
    q_total_J: float,
) -> float:
    return vibe_time_heat_release_rate_with_total_energy_numba(
        float(t_s),
        float(soc_time_s),
        float(duration_s),
        float(a),
        float(m),
        float(q_total_J),
    )


@nb.njit(cache=True)
def vibe_beck_time_fraction_and_rate_numba(
    t_s: float,
    soc_time_s: float,
    duration_s: float,
    a: float,
    m: float,
) -> tuple[float, float]:
    return vibe_time_fraction_and_rate_numba(t_s, soc_time_s, duration_s, a, m)


@nb.njit(cache=True)
def vibe_beck_time_heat_release_rate_with_total_energy_numba(
    t_s: float,
    soc_time_s: float,
    duration_s: float,
    a: float,
    m: float,
    q_total_J: float,
) -> float:
    if q_total_J <= 0.0 or duration_s <= 1.0e-18:
        return 0.0
    _xb, dxb_dt = vibe_beck_time_fraction_and_rate_numba(
        t_s,
        soc_time_s,
        duration_s,
        a,
        m,
    )
    return q_total_J * dxb_dt


def vibe_beck_time_heat_release_rate_with_total_energy(
    t_s: float,
    soc_time_s: float,
    duration_s: float,
    a: float,
    m: float,
    q_total_J: float,
) -> float:
    return vibe_beck_time_heat_release_rate_with_total_energy_numba(
        float(t_s),
        float(soc_time_s),
        float(duration_s),
        float(a),
        float(m),
        float(q_total_J),
    )


def vibe_beck_time_fraction_and_rate(
    t_s: float,
    soc_time_s: float,
    duration_s: float,
    a: float,
    m: float,
) -> tuple[float, float]:
    return vibe_beck_time_fraction_and_rate_numba(
        float(t_s),
        float(soc_time_s),
        float(duration_s),
        float(a),
        float(m),
    )


def vibe_fraction_and_rate(
    theta_local_deg: float,
    theta_global_deg: float,
    dtheta_local_dt_deg_s: float,
    dtheta_global_dt_deg_s: float,
    start_deg: float,
    duration_deg: float,
    a: float,
    m: float,
    ref_type: int,
    cycle_deg: float,
) -> tuple[float, float]:
    return vibe_fraction_and_rate_numba(
        float(theta_local_deg),
        float(theta_global_deg),
        float(dtheta_local_dt_deg_s),
        float(dtheta_global_dt_deg_s),
        float(start_deg),
        float(duration_deg),
        float(a),
        float(m),
        int(ref_type),
        float(cycle_deg),
    )


def vibe_time_fraction_and_rate(
    t_s: float,
    soc_time_s: float,
    duration_s: float,
    a: float,
    m: float,
) -> tuple[float, float]:
    return vibe_time_fraction_and_rate_numba(
        float(t_s),
        float(soc_time_s),
        float(duration_s),
        float(a),
        float(m),
    )


def combustion_duration_mode_from_row(comb_row) -> int:
    row = np.asarray(comb_row, dtype=np.float64)
    return int(_comb_duration_mode_from_row(row))
