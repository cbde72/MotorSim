from __future__ import annotations

from thermo0d.config.constants import AngleReference


def _clamp_position(x_m: float, x_min_m: float, x_max_m: float) -> float:
    if x_m < x_min_m:
        return float(x_min_m)
    if x_m > x_max_m:
        return float(x_max_m)
    return float(x_m)


def cylinder_stroke_window_m(x_min_m: float, x_max_m: float) -> float:
    return max(float(x_max_m) - float(x_min_m), 0.0)


def cylinder_stroke_fraction_from_tdc(x_m: float, x_min_m: float, x_max_m: float) -> float:
    stroke_m = cylinder_stroke_window_m(x_min_m, x_max_m)
    if stroke_m <= 1.0e-18:
        return 0.0
    x_eff_m = _clamp_position(x_m, x_min_m, x_max_m)
    return float((x_eff_m - x_min_m) / stroke_m)


def free_piston_is_compression_stroke(v_m_per_s: float, x_m: float, x_min_m: float, x_max_m: float, *, velocity_eps_m_per_s: float = 1.0e-12) -> bool:
    if v_m_per_s < -velocity_eps_m_per_s:
        return True
    if v_m_per_s > velocity_eps_m_per_s:
        return False
    # Totpunkt-/Stillstandsfall: TDC dem beendeten Kompressionshub zuordnen,
    # BDC dem beendeten Expansionshub. Damit bleibt der Bereich direkt vor TDC
    # für kompressionsbezogene Trigger stabil und ohne Richtungsflattern.
    return cylinder_stroke_fraction_from_tdc(x_m, x_min_m, x_max_m) <= 0.5


def free_piston_reference_is_active(ref_type: int, x_m: float, v_m_per_s: float, x_min_m: float, x_max_m: float) -> bool:
    # For free-piston combustion we use a stroke-based local angle map where
    # compression-TDC windows already live on the second half-cycle and may wrap
    # smoothly across TDC into the next cycle start. A hard "compression-stroke
    # only" gate would truncate an already started burn exactly at TDC.
    #
    # Therefore, compression-TDC referenced windows stay active here and the
    # actual windowing is handled only by the wrapped Vibe progress function.
    _ = (ref_type, x_m, v_m_per_s, x_min_m, x_max_m)
    return True


def free_piston_local_cycle_angle_deg(x_m: float, v_m_per_s: float, x_min_m: float, x_max_m: float, cycle_deg: float) -> float:
    """Map free-piston position + direction onto a cycle angle.

    The mapping is stroke-based instead of time-based:
      - first half cycle: motion away from TDC (expansion / scavenging)
      - second half cycle: motion toward TDC (compression)

    For a 2T case this yields:
      - TDC -> 0 deg (expansion side) / 360 deg (compression side)
      - BDC -> 180 deg

    For a 4T case the same logic scales to 0..720 deg.
    """
    half_cycle_deg = 0.5 * max(float(cycle_deg), 0.0)
    if half_cycle_deg <= 1.0e-18:
        return 0.0
    stroke_fraction = cylinder_stroke_fraction_from_tdc(x_m, x_min_m, x_max_m)
    if free_piston_is_compression_stroke(v_m_per_s, x_m, x_min_m, x_max_m):
        return float(cycle_deg - half_cycle_deg * stroke_fraction)
    return float(half_cycle_deg * stroke_fraction)




def free_piston_local_cycle_angle_rate_deg_s(v_m_per_s: float, x_min_m: float, x_max_m: float, cycle_deg: float) -> float:
    """Return the instantaneous rate of the stroke-based local free-piston angle.

    The local free-piston cycle angle is mapped from piston travel, not from a
    fixed crank speed. Its magnitude therefore scales with the instantaneous
    piston speed.
    """
    stroke_m = cylinder_stroke_window_m(x_min_m, x_max_m)
    half_cycle_deg = 0.5 * max(float(cycle_deg), 0.0)
    if stroke_m <= 1.0e-18 or half_cycle_deg <= 1.0e-18:
        return 0.0
    return float((half_cycle_deg / stroke_m) * abs(float(v_m_per_s)))

def cylinder_distance_from_tdc(x_m: float, x_min_m: float, x_max_m: float) -> float:
    """Return free-piston cylinder travel measured from compression TDC.

    User-facing free-piston convention:
      - x_min_m = TDC / smallest cylinder volume
      - x_max_m = BDC / largest cylinder volume

    The slot logic expects piston travel from TDC, so this helper returns the
    bounded travel from the lower bound.
    """
    x_eff_m = _clamp_position(x_m, x_min_m, x_max_m)
    return float(x_eff_m - x_min_m)


def cylinder_volume_from_position(clearance_volume_m3: float, piston_area_m2: float, x_m: float, x_min_m: float, x_max_m: float | None = None) -> float:
    if x_max_m is None:
        x_max_m = x_min_m
        x_min_m = 0.0
    x_eff_m = _clamp_position(x_m, x_min_m, x_max_m)
    volume_m3 = float(clearance_volume_m3 + piston_area_m2 * (x_eff_m - x_min_m))
    if volume_m3 <= 0.0:
        raise ValueError('Computed free-piston cylinder volume must be > 0')
    return volume_m3


def cylinder_dvdt_from_velocity(piston_area_m2: float, v_m_per_s: float) -> float:
    return float(piston_area_m2 * v_m_per_s)


def free_piston_equivalent_linear_kinematics(
    q: float,
    q_dot: float,
    sign: float,
    *,
    kinematics_type: str = 'linear',
    x_min_m: float,
    x_max_m: float,
    angle_min_rad: float = 0.0,
    angle_max_rad: float = 0.0,
    effective_radius_m: float = 1.0,
) -> tuple[float, float]:
    """Return the linear-equivalent piston position and velocity for a DOF.

    The existing free-piston thermodynamics, slots and combustion models consume
    a linear travel from TDC.  For an oscillating rotary piston the mechanical
    state is phi/omega, but the gas side still sees the equivalent arc travel
    r * phi.
    """
    if str(kinematics_type) == 'oscillating_rotary':
        phi = float(q)
        omega = float(q_dot)
        if float(sign) < 0.0:
            phi = float(angle_min_rad + angle_max_rad - phi)
            omega = -omega
        radius = max(float(effective_radius_m), 1.0e-18)
        x_m = float(x_min_m + radius * (phi - float(angle_min_rad)))
        v_m_per_s = float(radius * omega)
        return x_m, v_m_per_s

    q_m = float(q)
    q_v_m_per_s = float(q_dot)
    if float(sign) < 0.0:
        return float(x_min_m + x_max_m - q_m), float(-q_v_m_per_s)
    return q_m, q_v_m_per_s


def free_piston_generalized_initial_state(
    x0_m: float,
    v0_m_per_s: float,
    *,
    kinematics_type: str = 'linear',
    x_min_m: float,
    angle_min_rad: float = 0.0,
    effective_radius_m: float = 1.0,
) -> tuple[float, float]:
    if str(kinematics_type) == 'oscillating_rotary':
        radius = max(float(effective_radius_m), 1.0e-18)
        return (
            float(angle_min_rad + (float(x0_m) - float(x_min_m)) / radius),
            float(float(v0_m_per_s) / radius),
        )
    return float(x0_m), float(v0_m_per_s)


def bounce_volume_from_position(chamber_volume0_m3: float, bounce_area_m2: float, x_m: float, x_min_m: float, x_max_m: float) -> float:
    """Return bounce chamber volume running opposite to the cylinder volume.

    chamber_volume0_m3 is the maximum bounce volume Vmax at x_min_m (cylinder TDC/OT).
    bounce_area_m2 is the effective dV/dx area of the bounce chamber, chosen so
    that the configured bounce swept volume is traversed across the available
    free-piston stroke window from x_min_m (TDC/OT) to x_max_m (BDC/UT).
    The bounce chamber therefore shrinks while the main cylinder expands.
    """
    x_eff_m = _clamp_position(x_m, x_min_m, x_max_m)
    volume_m3 = float(chamber_volume0_m3 - bounce_area_m2 * (x_eff_m - x_min_m))
    if volume_m3 <= 0.0:
        raise ValueError('Computed free-piston bounce volume must be > 0')
    return volume_m3
