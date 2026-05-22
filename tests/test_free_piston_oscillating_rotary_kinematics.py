import math

from thermo0d.model.free_piston.geometry import free_piston_equivalent_linear_kinematics


def test_linear_equivalent_kinematics_keeps_existing_sign_convention() -> None:
    x, v = free_piston_equivalent_linear_kinematics(
        0.03,
        -2.0,
        -1.0,
        x_min_m=0.0,
        x_max_m=0.10,
    )

    assert x == 0.07
    assert v == 2.0


def test_oscillating_rotary_maps_angle_to_equivalent_stroke() -> None:
    angle_min = math.radians(-9.0)
    angle_max = math.radians(9.0)
    radius = 0.10 / (angle_max - angle_min)

    x_min, v_min = free_piston_equivalent_linear_kinematics(
        angle_min,
        0.0,
        1.0,
        kinematics_type='oscillating_rotary',
        x_min_m=0.0,
        x_max_m=0.10,
        angle_min_rad=angle_min,
        angle_max_rad=angle_max,
        effective_radius_m=radius,
    )
    x_mid, v_mid = free_piston_equivalent_linear_kinematics(
        0.0,
        10.0,
        1.0,
        kinematics_type='oscillating_rotary',
        x_min_m=0.0,
        x_max_m=0.10,
        angle_min_rad=angle_min,
        angle_max_rad=angle_max,
        effective_radius_m=radius,
    )
    x_mirror, v_mirror = free_piston_equivalent_linear_kinematics(
        0.0,
        10.0,
        -1.0,
        kinematics_type='oscillating_rotary',
        x_min_m=0.0,
        x_max_m=0.10,
        angle_min_rad=angle_min,
        angle_max_rad=angle_max,
        effective_radius_m=radius,
    )

    assert abs(x_min - 0.0) < 1.0e-12
    assert v_min == 0.0
    assert abs(x_mid - 0.05) < 1.0e-12
    assert abs(v_mid - radius * 10.0) < 1.0e-12
    assert abs(x_mirror - 0.05) < 1.0e-12
    assert abs(v_mirror + radius * 10.0) < 1.0e-12
