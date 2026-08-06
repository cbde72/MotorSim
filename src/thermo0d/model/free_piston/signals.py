
from __future__ import annotations


def free_piston_signal_names(prefix: str = 'free_piston') -> list[str]:
    root = str(prefix).strip() or 'free_piston'
    return [
        f'{root}_x_m',
        f'{root}_v_m_per_s',
        f'{root}_a_m_per_s2',
        f'{root}_F_gas_N',
        f'{root}_F_bounce_N',
        f'{root}_F_friction_N',
        f'{root}_F_load_N',
        f'{root}_F_net_N',
        f'{root}_generator_power_W',
        f'{root}_generator_electrical_power_W',
        f'{root}_generator_damping_eff_Ns_per_m',
        f'{root}_generator_force_base_N',
        f'{root}_generator_force_power_N',
        f'{root}_generator_assist_force_N',
        f'{root}_generator_assist_torque_Nm',
        f'{root}_generator_force_stop_N',
        f'{root}_generator_distance_to_stop_m',
        f'{root}_generator_midstroke_weight',
        f'{root}_generator_map_angle_deg',
        f'{root}_generator_map_torque_Nm',
        f'{root}_generator_map_no_load_torque_Nm',
        f'{root}_generator_map_load_torque_Nm',
        f'{root}_generator_map_voltage_V',
        f'{root}_generator_map_out_of_range_0to1',
        f'{root}_slot_area_sum_m2',
        f'{root}_combustion_mass_latched_kg',
        f'{root}_combustion_fuel_mass_latched_kg',
        f'{root}_combustion_energy_latched_J',
    ]
