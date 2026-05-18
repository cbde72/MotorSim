from __future__ import annotations

import math

import numpy as np

from thermo0d.config.constants import AngleReference, KinCol
from thermo0d.physics.flow import de_st_venant_wantzel_signed, interpolate_piecewise
from thermo0d.physics.kinematics import (
    cylinder_volume_and_dvdt,
    global_theta_and_rate_from_time,
    piston_displacement_from_tdc,
    reference_theta_and_zero,
    reference_zero_deg,
    theta_and_rate_from_time,
    wrap_angle_deg,
)


def test_interpolate_piecewise_edges_and_flat_segment():
    table = np.array([
        [0.0, 0.0],
        [1.0, 2.0],
        [1.0, 3.0],
        [2.0, 4.0],
    ], dtype=float)
    assert interpolate_piecewise(-1.0, table, 0, 4, 0, 1) == 0.0
    assert interpolate_piecewise(3.0, table, 0, 4, 0, 1) == 4.0
    assert interpolate_piecewise(1.0, table, 0, 4, 0, 1) == 2.0


def test_de_st_venant_zero_area_and_invalid_upstream():
    assert de_st_venant_wantzel_signed(2.0, 300.0, 1.0, 300.0, 0.0, 1.0, 1.0, 1.4, 287.0) == 0.0
    assert de_st_venant_wantzel_signed(0.0, 300.0, -1.0, 300.0, 1.0, 1.0, 1.0, 1.4, 287.0) == 0.0
    assert de_st_venant_wantzel_signed(2.0, 0.0, 1.0, 300.0, 1.0, 1.0, 1.0, 1.4, 287.0) == 0.0


def test_de_st_venant_reverse_uses_reverse_cd():
    mdot = de_st_venant_wantzel_signed(1.0, 300.0, 2.0, 300.0, 1.0e-4, 0.1, 0.2, 1.4, 287.0)
    mdot2 = de_st_venant_wantzel_signed(1.0, 300.0, 2.0, 300.0, 1.0e-4, 0.1, 0.4, 1.4, 287.0)
    assert mdot < 0.0
    assert abs(mdot2) > abs(mdot)


def _kin_row(cycle_deg=720.0, phase=10.0, speed=3000.0):
    row = np.zeros(max(int(c) for c in KinCol) + 1, dtype=float)
    row[int(KinCol.BORE)] = 0.086
    row[int(KinCol.STROKE)] = 0.086
    row[int(KinCol.CONROD)] = 0.143
    row[int(KinCol.COMPRESSION_RATIO)] = 10.0
    row[int(KinCol.PHASE_DEG)] = phase
    row[int(KinCol.SPEED_RPM)] = speed
    row[int(KinCol.CYCLE_DEG)] = cycle_deg
    return row


def test_wrap_and_reference_zero():
    assert math.isclose(wrap_angle_deg(-10.0, 360.0), 350.0)
    assert reference_zero_deg(720.0, AngleReference.GAS_EXCHANGE_TDC) == 360.0
    assert reference_zero_deg(360.0, AngleReference.GAS_EXCHANGE_TDC) == 0.0


def test_theta_and_rate_from_time_and_piston_motion():
    row = _kin_row()
    theta, rate, cycle = theta_and_rate_from_time(0.01, row)
    assert cycle == 720.0
    assert rate == 18000.0
    assert 0.0 <= theta < 720.0
    x0 = piston_displacement_from_tdc(row, 0.0)
    x180 = piston_displacement_from_tdc(row, 180.0)
    assert abs(x0) < 1.0e-12
    assert x180 > 0.08


def test_cylinder_volume_and_dvdt_sign_change():
    row = _kin_row(cycle_deg=360.0, phase=0.0, speed=1000.0)
    v0, dv0, _ = cylinder_volume_and_dvdt(row, 0.0)
    vq, dvq, _ = cylinder_volume_and_dvdt(row, 0.02)
    assert v0 > 0.0 and vq > 0.0
    assert dv0 >= 0.0
    assert dv0 != dvq



def test_global_theta_and_reference_resolution():
    row = _kin_row(cycle_deg=720.0, phase=180.0, speed=3000.0)
    theta_local, rate_local, cycle_local = theta_and_rate_from_time(0.001, row)
    theta_global, rate_global, cycle_global = global_theta_and_rate_from_time(0.001, row)
    assert cycle_local == cycle_global == 720.0
    assert rate_local == rate_global == 18000.0
    assert theta_local == wrap_angle_deg(theta_global + 180.0, 720.0)
    ref_theta_abs, ref_zero_abs = reference_theta_and_zero(theta_local, theta_global, 720.0, AngleReference.ABSOLUTE)
    assert ref_zero_abs == 0.0
    assert ref_theta_abs == theta_global
    ref_theta_comp, ref_zero_comp = reference_theta_and_zero(theta_local, theta_global, 720.0, AngleReference.COMPRESSION_TDC)
    assert ref_zero_comp == 0.0
    assert ref_theta_comp == theta_local
