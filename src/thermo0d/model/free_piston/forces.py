from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(slots=True)
class LoadModelInfo:
    force_signed_N: float = 0.0
    effective_damping_Ns_per_m: float = 0.0
    mechanical_power_W: float = 0.0
    electrical_power_W: float = 0.0
    base_force_N: float = 0.0
    power_force_N: float = 0.0
    stop_force_N: float = 0.0
    distance_to_stop_m: float = float('nan')
    midstroke_weight_0to1: float = 0.0


def coulomb_viscous_friction(fc_N: float, cv_Ns_per_m: float, v_m_per_s: float) -> float:
    sign = 0.0 if abs(v_m_per_s) < 1.0e-15 else math.copysign(1.0, v_m_per_s)
    return float(fc_N * sign + cv_Ns_per_m * v_m_per_s)


def _clamp(value: float, lo: float, hi: float) -> float:
    return float(max(lo, min(hi, value)))


def _smoothstep01(value: float) -> float:
    z = _clamp(value, 0.0, 1.0)
    return float(z * z * (3.0 - 2.0 * z))


def _generator_controlled_damping(
    *,
    base_damping_Ns_per_m: float,
    max_damping_Ns_per_m: float,
    control_zone_m: float,
    x_m: float,
    x_min_m: float,
    x_max_m: float,
    v_m_per_s: float,
) -> float:
    zone = max(float(control_zone_m), 1.0e-12)
    if abs(v_m_per_s) < 1.0e-15:
        return float(base_damping_Ns_per_m)
    proximity = 0.0
    if v_m_per_s < 0.0:
        distance = max(float(x_m) - float(x_min_m), 0.0)
        if distance < zone:
            proximity = 1.0 - distance / zone
    else:
        distance = max(float(x_max_m) - float(x_m), 0.0)
        if distance < zone:
            proximity = 1.0 - distance / zone
    proximity = max(0.0, min(1.0, proximity))
    return float(base_damping_Ns_per_m + (max_damping_Ns_per_m - base_damping_Ns_per_m) * proximity)


def _linear_generator_midstroke_weight(x_m: float, x_min_m: float, x_max_m: float) -> float:
    stroke = max(float(x_max_m) - float(x_min_m), 1.0e-12)
    s = _clamp((float(x_m) - float(x_min_m)) / stroke, 0.0, 1.0)
    return float(max(0.0, 4.0 * s * (1.0 - s)))


def _linear_generator_distance_to_stop(x_m: float, x_min_m: float, x_max_m: float, v_m_per_s: float) -> float:
    if v_m_per_s < 0.0:
        return float(max(float(x_m) - float(x_min_m), 0.0))
    if v_m_per_s > 0.0:
        return float(max(float(x_max_m) - float(x_m), 0.0))
    return float(min(max(float(x_m) - float(x_min_m), 0.0), max(float(x_max_m) - float(x_m), 0.0)))


def _linear_generator_regulated_info(
    *,
    base_damping_Ns_per_m: float,
    max_damping_Ns_per_m: float,
    power_target_W: float,
    efficiency_0to1: float,
    min_velocity_m_per_s: float,
    control_zone_m: float,
    target_margin_m: float,
    hard_margin_m: float,
    stop_kp: float,
    moving_mass_kg: float,
    max_force_N: float,
    x_m: float,
    x_min_m: float,
    x_max_m: float,
    v_m_per_s: float,
) -> LoadModelInfo:
    v_abs = abs(float(v_m_per_s))
    distance_to_stop_m = _linear_generator_distance_to_stop(x_m, x_min_m, x_max_m, v_m_per_s)
    midstroke_weight = _linear_generator_midstroke_weight(x_m, x_min_m, x_max_m)
    if v_abs < 1.0e-15:
        return LoadModelInfo(distance_to_stop_m=distance_to_stop_m, midstroke_weight_0to1=midstroke_weight)

    max_force_effective_N = float(max_force_N) if math.isfinite(max_force_N) and max_force_N > 0.0 else float('inf')
    force_cap_from_damping_N = max(float(max_damping_Ns_per_m), 0.0) * v_abs
    force_cap_N = min(max_force_effective_N, force_cap_from_damping_N) if force_cap_from_damping_N > 0.0 else max_force_effective_N

    base_force_N = max(float(base_damping_Ns_per_m), 0.0) * v_abs

    mech_power_target_W = max(float(power_target_W), 0.0) / max(float(efficiency_0to1), 1.0e-12)
    power_force_N = midstroke_weight * mech_power_target_W / max(v_abs, float(min_velocity_m_per_s))

    stop_force_N = 0.0
    zone = max(float(control_zone_m), 0.0)
    if zone > 0.0 and distance_to_stop_m < zone:
        stop_zone_weight = _smoothstep01((zone - distance_to_stop_m) / zone)
        distance_after_margin_m = max(distance_to_stop_m - float(target_margin_m), float(hard_margin_m), 1.0e-9)
        stop_force_req_N = float(moving_mass_kg) * v_abs * v_abs / (2.0 * distance_after_margin_m)
        stop_force_N = max(float(stop_kp), 0.0) * stop_zone_weight * stop_force_req_N

    total_force_N = base_force_N + power_force_N + stop_force_N
    if distance_to_stop_m <= float(hard_margin_m):
        total_force_N = force_cap_N
    if math.isfinite(force_cap_N):
        total_force_N = min(total_force_N, force_cap_N)
    total_force_N = max(total_force_N, 0.0)
    effective_damping = total_force_N / v_abs if v_abs > 1.0e-15 else 0.0
    sign = math.copysign(1.0, float(v_m_per_s))
    mechanical_power_W = total_force_N * v_abs
    electrical_power_W = mechanical_power_W * _clamp(float(efficiency_0to1), 0.0, 1.0)
    return LoadModelInfo(
        force_signed_N=float(sign * total_force_N),
        effective_damping_Ns_per_m=float(effective_damping),
        mechanical_power_W=float(mechanical_power_W),
        electrical_power_W=float(electrical_power_W),
        base_force_N=float(base_force_N),
        power_force_N=float(power_force_N),
        stop_force_N=float(stop_force_N),
        distance_to_stop_m=float(distance_to_stop_m),
        midstroke_weight_0to1=float(midstroke_weight),
    )



def compute_load_info(
    load_model: str,
    damping_Ns_per_m: float,
    v_m_per_s: float,
    *,
    x_m: float | None = None,
    x_min_m: float | None = None,
    x_max_m: float | None = None,
    max_damping_Ns_per_m: float | None = None,
    control_zone_m: float | None = None,
    power_target_W: float | None = None,
    efficiency_0to1: float | None = None,
    min_velocity_m_per_s: float | None = None,
    target_margin_m: float | None = None,
    hard_margin_m: float | None = None,
    stop_kp: float | None = None,
    moving_mass_kg: float | None = None,
    max_force_N: float | None = None,
) -> LoadModelInfo:
    model = str(load_model).strip().lower()
    if model == 'none':
        return LoadModelInfo()
    if model in {'viscous', 'electromagnetic_linear'}:
        force = float(damping_Ns_per_m * v_m_per_s)
        return LoadModelInfo(
            force_signed_N=force,
            effective_damping_Ns_per_m=float(damping_Ns_per_m),
            mechanical_power_W=float(max(force * v_m_per_s, 0.0)),
            electrical_power_W=float(max(force * v_m_per_s, 0.0)),
            base_force_N=float(abs(force)),
        )
    if model == 'generator_controlled':
        if x_m is None or x_min_m is None or x_max_m is None or max_damping_Ns_per_m is None or control_zone_m is None:
            raise ValueError('generator_controlled load requires position bounds, max_damping_Ns_per_m and control_zone_m')
        c_eff = _generator_controlled_damping(
            base_damping_Ns_per_m=float(damping_Ns_per_m),
            max_damping_Ns_per_m=float(max_damping_Ns_per_m),
            control_zone_m=float(control_zone_m),
            x_m=float(x_m),
            x_min_m=float(x_min_m),
            x_max_m=float(x_max_m),
            v_m_per_s=float(v_m_per_s),
        )
        force = float(c_eff * v_m_per_s)
        return LoadModelInfo(
            force_signed_N=force,
            effective_damping_Ns_per_m=float(c_eff),
            mechanical_power_W=float(max(force * v_m_per_s, 0.0)),
            electrical_power_W=float(max(force * v_m_per_s, 0.0)),
            base_force_N=float(abs(force)),
            distance_to_stop_m=_linear_generator_distance_to_stop(float(x_m), float(x_min_m), float(x_max_m), float(v_m_per_s)),
            midstroke_weight_0to1=_linear_generator_midstroke_weight(float(x_m), float(x_min_m), float(x_max_m)),
        )
    if model == 'linear_generator_regulated':
        required = [x_m, x_min_m, x_max_m, max_damping_Ns_per_m, control_zone_m, power_target_W, efficiency_0to1, min_velocity_m_per_s, target_margin_m, hard_margin_m, stop_kp, moving_mass_kg]
        if any(v is None for v in required):
            raise ValueError('linear_generator_regulated load requires position bounds, damping limit, power target and stop-control parameters')
        return _linear_generator_regulated_info(
            base_damping_Ns_per_m=float(damping_Ns_per_m),
            max_damping_Ns_per_m=float(max_damping_Ns_per_m),
            power_target_W=float(power_target_W),
            efficiency_0to1=float(efficiency_0to1),
            min_velocity_m_per_s=float(min_velocity_m_per_s),
            control_zone_m=float(control_zone_m),
            target_margin_m=float(target_margin_m),
            hard_margin_m=float(hard_margin_m),
            stop_kp=float(stop_kp),
            moving_mass_kg=float(moving_mass_kg),
            max_force_N=float(max_force_N) if max_force_N is not None else float('inf'),
            x_m=float(x_m),
            x_min_m=float(x_min_m),
            x_max_m=float(x_max_m),
            v_m_per_s=float(v_m_per_s),
        )
    raise ValueError(f'unsupported free-piston load model: {load_model!r}')



def compute_load_force(
    load_model: str,
    damping_Ns_per_m: float,
    v_m_per_s: float,
    *,
    x_m: float | None = None,
    x_min_m: float | None = None,
    x_max_m: float | None = None,
    max_damping_Ns_per_m: float | None = None,
    control_zone_m: float | None = None,
    power_target_W: float | None = None,
    efficiency_0to1: float | None = None,
    min_velocity_m_per_s: float | None = None,
    target_margin_m: float | None = None,
    hard_margin_m: float | None = None,
    stop_kp: float | None = None,
    moving_mass_kg: float | None = None,
    max_force_N: float | None = None,
) -> float:
    return float(compute_load_info(
        load_model,
        damping_Ns_per_m,
        v_m_per_s,
        x_m=x_m,
        x_min_m=x_min_m,
        x_max_m=x_max_m,
        max_damping_Ns_per_m=max_damping_Ns_per_m,
        control_zone_m=control_zone_m,
        power_target_W=power_target_W,
        efficiency_0to1=efficiency_0to1,
        min_velocity_m_per_s=min_velocity_m_per_s,
        target_margin_m=target_margin_m,
        hard_margin_m=hard_margin_m,
        stop_kp=stop_kp,
        moving_mass_kg=moving_mass_kg,
        max_force_N=max_force_N,
    ).force_signed_N)



def viscous_load_force(damping_Ns_per_m: float, v_m_per_s: float) -> float:
    return compute_load_force('viscous', damping_Ns_per_m, v_m_per_s)



def gas_pressure_force(pressure_Pa: float, piston_area_m2: float) -> float:
    return float(pressure_Pa * piston_area_m2)



def compute_generator_power_W(load_force_signed_N: float, v_m_per_s: float) -> float:
    return float(max(load_force_signed_N * v_m_per_s, 0.0))
