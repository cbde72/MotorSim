from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from thermo0d.compute.executor import TimeGridBuilder, build_rhs_for_bundle, integrate_prebuilt_system


def build_time_grid(dt_s: float, t_end_s: float) -> np.ndarray:
    return TimeGridBuilder.build(dt_s, t_end_s)


@dataclass(slots=True)
class FreePistonSimulationResult:
    t: np.ndarray
    y: np.ndarray
    solver_kind: str


def make_free_piston_rhs_closure(bundle):
    return build_rhs_for_bundle(bundle)


def simulate_free_piston(bundle) -> FreePistonSimulationResult:
    result = integrate_prebuilt_system(bundle, make_free_piston_rhs_closure(bundle), enable_cycle_reporting=False)
    return FreePistonSimulationResult(t=result.t, y=result.y, solver_kind=result.solver_kind)
