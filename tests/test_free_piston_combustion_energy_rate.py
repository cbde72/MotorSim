from __future__ import annotations

import numpy as np

from thermo0d.config.constants import AngleReference, CombCol
from thermo0d.physics.combustion import vibe_heat_release_rate


def _comb_row(*, start_deg: float, duration_deg: float, q_total: float, ref_type: AngleReference) -> np.ndarray:
    row = np.zeros(len(CombCol), dtype=float)
    row[CombCol.MODEL] = 1.0
    row[CombCol.START_DEG] = float(start_deg)
    row[CombCol.DURATION_DEG] = float(duration_deg)
    row[CombCol.A] = 6.9
    row[CombCol.M] = 2.0
    row[CombCol.FUEL_MASS_PER_CYCLE] = float(q_total)
    row[CombCol.LHV] = 1.0
    row[CombCol.REF_TYPE] = float(ref_type)
    return row


def _integrate_qdot(theta_local: np.ndarray, theta_global: np.ndarray, dtheta_local: float, dtheta_global: float, row: np.ndarray, cycle_deg: float) -> float:
    dt = np.diff(np.linspace(0.0, 1.0, theta_local.size))
    qdot = np.array([
        vibe_heat_release_rate(float(tl), float(tg), float(dtheta_local), float(dtheta_global), row, float(cycle_deg))
        for tl, tg in zip(theta_local, theta_global, strict=False)
    ])
    # scale integration interval so that the driven reference angle traverses the full window
    ref_rate = dtheta_global if int(row[CombCol.REF_TYPE]) == int(AngleReference.ABSOLUTE) else dtheta_local
    duration_s = float(row[CombCol.DURATION_DEG]) / ref_rate
    dt = dt * duration_s
    return float(np.sum(0.5 * (qdot[:-1] + qdot[1:]) * dt))


def test_vibe_uses_local_angle_rate_for_free_piston_referenced_windows() -> None:
    q_total = 420.0
    start_deg = 275.0
    duration_deg = 8.0
    dtheta_local = 2400.0
    dtheta_global = 150.0
    n = 4001
    theta_local = np.linspace(start_deg, start_deg + duration_deg, n)
    theta_global = np.zeros(n, dtype=float)
    row = _comb_row(start_deg=start_deg, duration_deg=duration_deg, q_total=q_total, ref_type=AngleReference.COMPRESSION_TDC)
    released = _integrate_qdot(theta_local, theta_global, dtheta_local, dtheta_global, row, 360.0)
    assert np.isclose(released, q_total, rtol=5.0e-3, atol=5.0e-2)


def test_vibe_keeps_global_rate_for_absolute_reference() -> None:
    q_total = 420.0
    start_deg = 30.0
    duration_deg = 20.0
    dtheta_local = 2400.0
    dtheta_global = 150.0
    n = 4001
    theta_local = np.zeros(n, dtype=float)
    theta_global = np.linspace(start_deg, start_deg + duration_deg, n)
    row = _comb_row(start_deg=start_deg, duration_deg=duration_deg, q_total=q_total, ref_type=AngleReference.ABSOLUTE)
    released = _integrate_qdot(theta_local, theta_global, dtheta_local, dtheta_global, row, 360.0)
    assert np.isclose(released, q_total, rtol=5.0e-3, atol=5.0e-2)
