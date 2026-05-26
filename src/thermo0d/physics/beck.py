from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BeckCoolFlameFuelParameters:
    name: str
    hot_flame_activation_energy_J_per_kg: float
    hot_flame_activation_std_percent: float
    cool_flame_activation_energy_J_per_kg: float
    cool_flame_activation_std_percent: float
    dqmax: tuple[float, float, float, float, float, float]
    dqmax_r2: float
    duration: tuple[float, float, float, float, float, float]
    duration_r2: float


BECK_COOL_FLAME_FUEL_PARAMETERS: dict[str, BeckCoolFlameFuelParameters] = {
    "CEC-Ref.": BeckCoolFlameFuelParameters("CEC-Ref.", 2298e3, 1.07, 1601e3, 1.93, (0.444, 0.0, -0.373, 1.364, 0.401, 1.4e-3), 0.964, (-0.117, -6.7e-3, 0.039, -0.237, -0.670, 417.6), 0.958),
    "n-Heptan": BeckCoolFlameFuelParameters("n-Heptan", 2205e3, 1.31, 1610e3, 1.55, (0.347, 0.0, -0.241, 1.235, 0.425, 3.0e-3), 0.968, (-0.020, -7.0e-3, 4.5e-3, -0.119, -0.806, 464.6), 0.991),
    "Naphtha 1": BeckCoolFlameFuelParameters("Naphtha 1", 2473e3, 0.72, 1679e3, 1.64, (1.101, 0.0, -0.935, -3.293, -1.149, 6.2e14), 0.927, (-0.254, 9.4e-5, 0.128, -0.189, -0.503, 84.5), 0.987),
    "Naphtha 2": BeckCoolFlameFuelParameters("Naphtha 2", 2322e3, 1.27, 1618e3, 1.88, (0.652, 0.0, -0.388, 1.594, -0.066, 6.6e-3), 0.959, (4.7e-4, -0.019, 0.053, -0.243, -0.547, 154.1), 0.963),
    "Kerosin 1": BeckCoolFlameFuelParameters("Kerosin 1", 2437e3, 0.97, 1643e3, 2.08, (1.148, 0.0, -0.577, 2.266, -0.329, 2.5e-4), 0.977, (-0.348, -2.3e-4, 0.033, -0.402, -0.342, 165.6), 0.938),
    "Kerosin 2": BeckCoolFlameFuelParameters("Kerosin 2", 2276e3, 1.13, 1616e3, 1.57, (0.414, 0.0, -0.369, 1.160, 0.0, 0.118), 0.998, (-0.335, 0.027, 0.018, -0.088, 0.0, 0.928), 0.990),
    "Kerosin 3": BeckCoolFlameFuelParameters("Kerosin 3", 2319e3, 1.04, 1621e3, 1.76, (0.520, 0.0, -0.393, 1.355, -0.095, 0.052), 0.972, (-0.060, -0.019, 3.4e-3, -0.312, -0.628, 584.2), 0.976),
    "Diesel 1": BeckCoolFlameFuelParameters("Diesel 1", 2321e3, 1.07, 1585e3, 2.05, (0.580, 0.0, -0.410, 1.783, 0.058, 1.1e-3), 0.960, (-0.204, -3.3e-3, 0.017, -0.355, -0.474, 243.7), 0.885),
    "Diesel 2": BeckCoolFlameFuelParameters("Diesel 2", 2248e3, 1.23, 1579e3, 1.87, (0.363, 0.0, -0.333, 1.424, 0.155, 7.5e-3), 0.963, (-0.071, -8.5e-3, 0.016, -0.241, -0.645, 340.9), 0.967),
}

BECK_COOL_FLAME_FUEL_NAMES: tuple[str, ...] = tuple(BECK_COOL_FLAME_FUEL_PARAMETERS)


def beck_cool_flame_fuel_parameters(name: str) -> BeckCoolFlameFuelParameters:
    key = str(name).strip()
    if key not in BECK_COOL_FLAME_FUEL_PARAMETERS:
        choices = ", ".join(BECK_COOL_FLAME_FUEL_NAMES)
        raise ValueError(f"Unknown Beck cool-flame fuel '{name}'. Choices: {choices}")
    return BECK_COOL_FLAME_FUEL_PARAMETERS[key]
