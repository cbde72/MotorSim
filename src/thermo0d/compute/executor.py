"""Execution layer for time integration.

The executor builds the fixed output time grid, instantiates the wrapped RHS and
selects the configured solver from the registry. For stiff SciPy solvers it also
passes sparsity and Jacobian callbacks so the compute layer remains the only
place where integration strategy is decided.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import numpy as np

from thermo0d.compute.analysis import CycleIndexCalculator, CycleSummaryCalculator
from thermo0d.compute.solvers import SolverFactory
from thermo0d.output.console import ConsoleCycleReporter
from thermo0d.physics.rhs import RHSWrapper
from thermo0d.model.free_piston.combustion_latch import free_piston_uses_slot_closure_lambda, free_piston_uses_time_vibe, free_piston_uses_vapor_injector, update_free_piston_combustion_latch_state
from thermo0d.model.wall_temperature import apply_wall_temperature_cycle_update, build_fixed_step_wall_temperature_callback, has_wall_temperature_model, wall_temperature_cycle_period_s


@dataclass(slots=True)
class SimulationExecutionResult:
    t: np.ndarray
    y: np.ndarray
    wall_clock_s: float
    solver_kind: str
    live_cycle_summaries_printed: bool = False


class TimeGridBuilder:
    """Create the fixed output/integration time grid for the configured dt."""

    @staticmethod
    def build(dt_s: float, t_end_s: float) -> np.ndarray:
        dt_s = float(dt_s)
        t_end_s = float(t_end_s)
        if dt_s <= 0.0:
            raise ValueError('dt_s must be > 0')
        if t_end_s < 0.0:
            raise ValueError('t_end_s must be >= 0')
        n_full_steps = int(np.floor(t_end_s / dt_s + 1.0e-12))
        grid = dt_s * np.arange(n_full_steps + 1, dtype=np.float64)
        if grid.size == 0:
            grid = np.array([0.0], dtype=np.float64)
        if abs(grid[-1] - t_end_s) > max(1.0e-12, abs(dt_s) * 1.0e-9):
            grid = np.concatenate((grid, np.array([t_end_s], dtype=np.float64)))
        else:
            grid[-1] = t_end_s
        return grid


def configured_end_time(bundle) -> float:
    t_end_configured = getattr(bundle.simulation, 'simulationtime_s', None)
    if t_end_configured is None:
        return float(bundle.simulation.total_cycles) * float(bundle.cycle_period_s)
    return float(t_end_configured)


def build_time_grid_for_bundle(bundle) -> np.ndarray:
    return TimeGridBuilder.build(bundle.simulation.dt_s, configured_end_time(bundle))


def build_rhs_for_bundle(bundle):
    architecture = getattr(bundle, 'architecture', 'classic')
    if architecture == 'free_piston':
        from thermo0d.model.free_piston.rhs import compute_free_piston_rhs

        def rhs(t_s: float, y: np.ndarray) -> np.ndarray:
            return compute_free_piston_rhs(t_s, y, bundle)

        return rhs
    return RHSWrapper(bundle)


def build_solver_kwargs(bundle, rhs) -> dict:
    solver_kwargs: dict = {}
    if str(bundle.simulation.solver_kind) in {'scipy_bdf', 'scipy_radau'} and hasattr(rhs, 'jacobian') and bundle.jac_sparsity is not None:
        solver_kwargs['jac_sparsity'] = bundle.jac_sparsity
        solver_kwargs['jac'] = rhs.jacobian
    return solver_kwargs


def integrate_prebuilt_system(bundle, rhs, *, enable_cycle_reporting: bool) -> SimulationExecutionResult:
    t_eval = build_time_grid_for_bundle(bundle)
    solver = SolverFactory.create(bundle.simulation.solver_kind)
    solver_kwargs = build_solver_kwargs(bundle, rhs)

    started = perf_counter()
    live_cycle_summaries_printed = False
    cycle_summary_enabled = bool(getattr(bundle.postprocessing, 'console_cycle_summary_enabled', True)) and bool(enable_cycle_reporting)
    solver_kind = str(bundle.simulation.solver_kind)

    if solver_kind.startswith('scipy_') and has_wall_temperature_model(bundle) and getattr(bundle, 'architecture', 'classic') != 'free_piston':
        t_res, y_res = _run_scipy_with_wall_temperature_segments(bundle, solver, rhs, t_eval, dict(solver_kwargs))
    elif cycle_summary_enabled and solver_kind.startswith('scipy_'):
        t_res, y_res, live_cycle_summaries_printed = _run_scipy_with_live_cycle_reporting(bundle, solver, rhs, t_eval, dict(solver_kwargs))
    else:
        runtime_callback = _build_free_piston_runtime_callback(bundle)
        if solver_kind in {'euler', 'rk4'}:
            cycle_callback = _build_fixed_step_cycle_callback(bundle, t_eval) if cycle_summary_enabled else None
            wall_temperature_callback = build_fixed_step_wall_temperature_callback(bundle, t_eval)
            solver_kwargs['step_callback'] = _compose_step_callbacks(runtime_callback, wall_temperature_callback, cycle_callback)
            live_cycle_summaries_printed = cycle_callback is not None
        elif solver_kind.startswith('scipy_') and runtime_callback is not None:
            solver_kwargs['accepted_step_callback'] = _build_free_piston_accepted_step_callback(bundle)
        result = solver(rhs, bundle.y_init.copy(), t_eval, bundle.simulation.rtol, bundle.simulation.atol, **solver_kwargs)
        t_res = result.t
        y_res = result.y

    elapsed = perf_counter() - started
    return SimulationExecutionResult(
        t=t_res,
        y=y_res,
        wall_clock_s=elapsed,
        solver_kind=str(bundle.simulation.solver_kind),
        live_cycle_summaries_printed=live_cycle_summaries_printed,
    )


def _compose_step_callbacks(*callbacks):
    active = [cb for cb in callbacks if cb is not None]
    if not active:
        return None

    def step_callback(step_idx: int, t_hist: np.ndarray, y_hist: np.ndarray) -> None:
        for cb in active:
            cb(step_idx, t_hist, y_hist)

    return step_callback


def _build_free_piston_runtime_callback(bundle):
    if getattr(bundle, 'architecture', 'classic') != 'free_piston':
        return None
    if not (free_piston_uses_slot_closure_lambda(bundle) or free_piston_uses_vapor_injector(bundle) or free_piston_uses_time_vibe(bundle)):
        return None

    def step_callback(step_idx: int, t_hist: np.ndarray, y_hist: np.ndarray) -> None:
        idx = int(step_idx)
        update_free_piston_combustion_latch_state(bundle, float(t_hist[idx]), y_hist[:, idx])

    return step_callback


def _build_free_piston_accepted_step_callback(bundle):
    if getattr(bundle, 'architecture', 'classic') != 'free_piston':
        return None
    if not (free_piston_uses_slot_closure_lambda(bundle) or free_piston_uses_vapor_injector(bundle) or free_piston_uses_time_vibe(bundle)):
        return None

    def accepted_step_callback(t_s: float, y_state: np.ndarray) -> None:
        update_free_piston_combustion_latch_state(bundle, float(t_s), np.asarray(y_state, dtype=np.float64))

    return accepted_step_callback


def _build_fixed_step_cycle_callback(bundle, t_eval: np.ndarray):
    cycle_indices_eval = CycleIndexCalculator.compute(
        t_eval,
        bundle.cycle_period_s,
        bundle.simulation.total_cycles,
    )
    if t_eval.size <= 1:
        return None
    transition_ids = np.flatnonzero(np.diff(cycle_indices_eval) != 0)
    cycle_start_ids = np.concatenate(([0], transition_ids + 1))
    cycle_stop_ids = np.concatenate((transition_ids + 1, [t_eval.size - 1]))
    next_cycle_ptr = 0

    def step_callback(step_idx: int, t_hist: np.ndarray, y_hist: np.ndarray) -> None:
        nonlocal next_cycle_ptr
        while next_cycle_ptr < int(cycle_stop_ids.size) and int(step_idx) >= int(cycle_stop_ids[next_cycle_ptr]):
            first = int(cycle_start_ids[next_cycle_ptr])
            last = int(cycle_stop_ids[next_cycle_ptr])
            cyc = int(cycle_indices_eval[first])
            summary = CycleSummaryCalculator.compute_range(bundle, t_hist, y_hist, first, last, cyc)
            if summary is not None:
                ConsoleCycleReporter.print_one(summary)
            next_cycle_ptr += 1

    return step_callback


def _run_scipy_with_live_cycle_reporting(bundle, solver, rhs, t_eval: np.ndarray, solver_kwargs: dict) -> tuple[np.ndarray, np.ndarray, bool]:
    cycle_indices_eval = CycleIndexCalculator.compute(t_eval, bundle.cycle_period_s, bundle.simulation.total_cycles)
    if t_eval.size <= 1:
        result = solver(rhs, bundle.y_init.copy(), t_eval, bundle.simulation.rtol, bundle.simulation.atol, **solver_kwargs)
        return result.t, result.y, False

    transition_ids = np.flatnonzero(np.diff(cycle_indices_eval) != 0)
    cycle_start_ids = np.concatenate(([0], transition_ids + 1))
    cycle_stop_ids = np.concatenate((transition_ids + 1, [t_eval.size - 1]))

    y_start = bundle.y_init.copy()
    t_parts: list[np.ndarray] = []
    y_parts: list[np.ndarray] = []
    printed = False

    for part_idx, (start_id, stop_id) in enumerate(zip(cycle_start_ids, cycle_stop_ids, strict=False)):
        start_idx = int(start_id)
        stop_idx = int(stop_id)
        seg_t_eval = t_eval[start_idx:stop_idx + 1]
        if seg_t_eval.size < 2:
            continue

        seg_result = solver(rhs, y_start.copy(), seg_t_eval, bundle.simulation.rtol, bundle.simulation.atol, **solver_kwargs)
        local_last = int(seg_result.t.size - 1)
        if part_idx < int(cycle_start_ids.size - 1):
            local_last = max(0, local_last - 1)
        cycle_index = int(cycle_indices_eval[start_idx])
        summary = CycleSummaryCalculator.compute_range(bundle, seg_result.t, seg_result.y, 0, local_last, cycle_index)
        if summary is not None:
            ConsoleCycleReporter.print_one(summary)
            printed = True

        if part_idx == 0:
            t_parts.append(seg_result.t)
            y_parts.append(seg_result.y)
        else:
            t_parts.append(seg_result.t[1:])
            y_parts.append(seg_result.y[:, 1:])
        y_start = seg_result.y[:, -1]

    if not t_parts:
        result = solver(rhs, bundle.y_init.copy(), t_eval, bundle.simulation.rtol, bundle.simulation.atol, **solver_kwargs)
        return result.t, result.y, False

    return np.concatenate(t_parts), np.concatenate(y_parts, axis=1), printed


def _run_scipy_with_wall_temperature_segments(bundle, solver, rhs, t_eval: np.ndarray, solver_kwargs: dict) -> tuple[np.ndarray, np.ndarray]:
    wall_period_s = wall_temperature_cycle_period_s(bundle)
    if wall_period_s <= 1.0e-15 or t_eval.size <= 1:
        result = solver(rhs, bundle.y_init.copy(), t_eval, bundle.simulation.rtol, bundle.simulation.atol, **solver_kwargs)
        return result.t, result.y

    t_start = float(t_eval[0])
    t_end = float(t_eval[-1])
    boundaries = [t_start]
    next_boundary = wall_period_s * (np.floor(t_start / wall_period_s) + 1.0)
    while next_boundary < t_end - 1.0e-12:
        boundaries.append(float(next_boundary))
        next_boundary += wall_period_s
    boundaries.append(t_end)

    y_start = bundle.y_init.copy()
    t_parts: list[np.ndarray] = []
    y_parts: list[np.ndarray] = []
    for part_idx in range(len(boundaries) - 1):
        a = float(boundaries[part_idx])
        b = float(boundaries[part_idx + 1])
        inner = t_eval[(t_eval > a + 1.0e-12) & (t_eval < b - 1.0e-12)]
        seg_t_eval = np.concatenate((np.array([a], dtype=np.float64), inner, np.array([b], dtype=np.float64)))
        seg_result = solver(rhs, y_start.copy(), seg_t_eval, bundle.simulation.rtol, bundle.simulation.atol, **solver_kwargs)
        if float(seg_result.t[-1] - seg_result.t[0]) >= 0.999 * wall_period_s:
            apply_wall_temperature_cycle_update(bundle, seg_result.t, seg_result.y, 0, int(seg_result.t.size - 1))
        if part_idx == 0:
            t_parts.append(seg_result.t)
            y_parts.append(seg_result.y)
        else:
            t_parts.append(seg_result.t[1:])
            y_parts.append(seg_result.y[:, 1:])
        y_start = seg_result.y[:, -1].copy()

    return np.concatenate(t_parts), np.concatenate(y_parts, axis=1)


class SimulationExecutor:
    """Run one configured simulation case through the selected solver."""

    def __init__(self, bundle):
        self.bundle = bundle

    def run(self) -> SimulationExecutionResult:
        rhs = build_rhs_for_bundle(self.bundle)
        enable_cycle_reporting = getattr(self.bundle, 'architecture', 'classic') != 'free_piston'
        return integrate_prebuilt_system(self.bundle, rhs, enable_cycle_reporting=enable_cycle_reporting)
