"""Cycle-wise analysis utilities.

This module reduces raw solver time histories to per-cycle summary metrics used
by console logging, batch comparisons and benchmark reports. The implemented
summary currently covers cylinder air mass, simulated cycle runtime, piston work
and peak pressure.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from thermo0d.config.constants import VolumeCol
from thermo0d.physics.kinematics import cylinder_volume_and_dvdt
from thermo0d.physics.quellen_props import properties_from_mass_energy_components_quellen


@dataclass(slots=True)
class CycleSummary:
    cycle_index: int
    air_mass_mg: float
    runtime_s: float
    piston_work_J: float
    pmax_bar: float


class CycleIndexCalculator:
    """Map absolute solver time to integer cycle indices."""

    @staticmethod
    def compute(t: np.ndarray, cycle_period_s: float, total_cycles: int | None = None) -> np.ndarray:
        if cycle_period_s <= 0.0:
            raise ValueError('cycle_period_s must be > 0')
        shifted = np.asarray(t, dtype=np.float64) / float(cycle_period_s) - 1.0e-12
        idx = np.floor(shifted).astype(int)
        idx[idx < 0] = 0
        if total_cycles is not None:
            idx[idx >= int(total_cycles)] = int(total_cycles) - 1
        return idx


class CycleSummaryCalculator:
    """Compute per-cycle summary metrics from raw solver histories."""
    @staticmethod
    def _pressure_pa(mass_kg: float, internal_energy_j: float, volume_m3: float, cv_j_per_kgk: float, gas_constant_j_per_kgk: float) -> float:
        if mass_kg <= 1.0e-18 or volume_m3 <= 1.0e-18:
            return 0.0
        temperature_k = internal_energy_j / (mass_kg * cv_j_per_kgk)
        return mass_kg * gas_constant_j_per_kgk * temperature_k / volume_m3

    @staticmethod
    def _state_pressure_pa(bundle, state: np.ndarray, cyl_idx: int, volume_m3: float) -> float:
        if volume_m3 <= 1.0e-18:
            return 0.0
        state_layout = bundle.state_layout
        mass_kg = float(state_layout.gas_mass_from_state(state, cyl_idx))
        internal_energy_j = float(state[int(state_layout.energy_index(cyl_idx))])
        cv_default = float(bundle.gas_props[1])
        gas_constant_default = float(bundle.gas_props[2])
        use_promo_thermo = bundle.gas_props.shape[0] > 4 and float(bundle.gas_props[4]) >= 0.5
        if use_promo_thermo:
            air_mass_kg = float(state_layout.air_mass_from_state(state, cyl_idx))
            burned_mass_kg = float(state_layout.burned_mass_from_state(state, cyl_idx))
            fuel_vapor_mass_kg = float(state_layout.fuel_vapor_mass_from_state(state, cyl_idx))
            _temp_k, _cp, cv_mix, gas_constant_mix, _kappa = properties_from_mass_energy_components_quellen(
                mass_kg,
                internal_energy_j,
                air_mass_kg,
                fuel_vapor_mass_kg,
                burned_mass_kg,
                cv_default,
            )
            return CycleSummaryCalculator._pressure_pa(mass_kg, internal_energy_j, volume_m3, cv_mix, gas_constant_mix)
        return CycleSummaryCalculator._pressure_pa(mass_kg, internal_energy_j, volume_m3, cv_default, gas_constant_default)

    @classmethod
    def compute_range(cls, bundle, t: np.ndarray, y: np.ndarray, first: int, last: int, cycle_index: int) -> CycleSummary | None:
        if last - first < 1:
            return None
        state_layout = bundle.state_layout
        cycle_runtime_s = float(t[last] - t[first])
        air_mass_mg = 0.0
        piston_work_j = 0.0
        pmax_pa = 0.0
        for cyl_idx in bundle.cylinder_indices:
            air_mass_mg += float(y[int(state_layout.air_mass_index(cyl_idx)), last]) * 1.0e6
            kin_row = bundle.kin_matrix[int(bundle.vol_matrix[cyl_idx, VolumeCol.KIN_ROW])]
            for k in range(first, last):
                v0, _, _ = cylinder_volume_and_dvdt(kin_row, float(t[k]))
                v1, _, _ = cylinder_volume_and_dvdt(kin_row, float(t[k + 1]))
                p0 = cls._state_pressure_pa(bundle, y[:, k], cyl_idx, v0)
                p1 = cls._state_pressure_pa(bundle, y[:, k + 1], cyl_idx, v1)
                pmax_pa = max(pmax_pa, p0, p1)
                p_avg = 0.5 * (p0 + p1)
                piston_work_j += p_avg * (v1 - v0)
        return CycleSummary(
            cycle_index=int(cycle_index),
            air_mass_mg=air_mass_mg,
            runtime_s=cycle_runtime_s,
            piston_work_J=piston_work_j,
            pmax_bar=pmax_pa / 1.0e5,
        )

    @classmethod
    def compute(cls, bundle, t: np.ndarray, y: np.ndarray, cycle_indices: np.ndarray) -> list[CycleSummary]:
        unique_cycles = np.unique(cycle_indices)
        summaries: list[CycleSummary] = []
        for cyc in unique_cycles:
            mask = cycle_indices == cyc
            ids = np.where(mask)[0]
            if ids.size < 2:
                continue
            summary = cls.compute_range(bundle, t, y, int(ids[0]), int(ids[-1]), int(cyc))
            if summary is not None:
                summaries.append(summary)
        return summaries
