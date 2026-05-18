"""Solver registry and concrete integrator backends.

The project supports explicit fixed-step solvers and SciPy IVP methods via a
common registry. Each solver receives the same interface so the surrounding
compute layer can select a method purely from configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
from scipy.integrate import solve_ivp
from scipy.integrate._ivp.bdf import BDF
from scipy.integrate._ivp.radau import Radau
from scipy.integrate._ivp.rk import RK45


RHSCallable = Callable[[float, np.ndarray], np.ndarray]
StepCallback = Callable[[int, np.ndarray, np.ndarray], None]
AcceptedStepCallback = Callable[[float, np.ndarray], None]
_SOLVER_REGISTRY: dict[str, Callable[..., 'SolverResult']] = {}


@dataclass(slots=True)
class SolverResult:
    t: np.ndarray
    y: np.ndarray


class SolverRegistry:
    """Central name-to-solver registry used by configuration-driven execution."""
    @staticmethod
    def register(name: str):
        def decorator(func: Callable[..., SolverResult]):
            _SOLVER_REGISTRY[name] = func
            return func
        return decorator

    @staticmethod
    def create(name: str) -> Callable[..., SolverResult]:
        try:
            return _SOLVER_REGISTRY[name]
        except KeyError as exc:
            raise KeyError(f'Unknown solver: {name}. Registered: {sorted(_SOLVER_REGISTRY)}') from exc

    @staticmethod
    def registered_names() -> list[str]:
        return sorted(_SOLVER_REGISTRY)


register_solver = SolverRegistry.register


@register_solver('euler')
def solve_euler(rhs: RHSCallable, y0: np.ndarray, t_eval: np.ndarray, rtol: float, atol: float, **kwargs) -> SolverResult:
    step_callback = kwargs.pop('step_callback', None)
    y = np.zeros((y0.size, t_eval.size), dtype=np.float64)
    y[:, 0] = y0
    for i in range(t_eval.size - 1):
        dt = t_eval[i + 1] - t_eval[i]
        y[:, i + 1] = y[:, i] + dt * rhs(t_eval[i], y[:, i])
        if step_callback is not None:
            step_callback(i + 1, t_eval, y)
    return SolverResult(t=t_eval, y=y)


@register_solver('rk4')
def solve_rk4(rhs: RHSCallable, y0: np.ndarray, t_eval: np.ndarray, rtol: float, atol: float, **kwargs) -> SolverResult:
    step_callback = kwargs.pop('step_callback', None)
    y = np.zeros((y0.size, t_eval.size), dtype=np.float64)
    y[:, 0] = y0
    y_stage = np.empty_like(y0)
    for i in range(t_eval.size - 1):
        t = t_eval[i]
        dt = t_eval[i + 1] - t_eval[i]
        half_dt = 0.5 * dt
        yi = y[:, i]
        y_next = y[:, i + 1]

        k1 = rhs(t, yi)
        np.multiply(k1, half_dt, out=y_stage)
        y_stage += yi

        k2 = rhs(t + half_dt, y_stage)
        np.multiply(k2, half_dt, out=y_stage)
        y_stage += yi

        k3 = rhs(t + half_dt, y_stage)
        np.multiply(k3, dt, out=y_stage)
        y_stage += yi

        k4 = rhs(t + dt, y_stage)

        np.copyto(y_next, yi)
        y_next += (dt / 6.0) * k1
        y_next += (dt / 3.0) * k2
        y_next += (dt / 3.0) * k3
        y_next += (dt / 6.0) * k4
        if step_callback is not None:
            step_callback(i + 1, t_eval, y)
    return SolverResult(t=t_eval, y=y)



def _solve_scipy_with_accepted_steps(solver_cls, rhs: RHSCallable, y0: np.ndarray, t_eval: np.ndarray, rtol: float, atol: float, **kwargs) -> SolverResult:
    accepted_step_callback = kwargs.pop('accepted_step_callback', None)
    dense_output = bool(kwargs.pop('dense_output', False))
    first_step = kwargs.pop('first_step', None)
    max_step = kwargs.pop('max_step', np.inf)
    vectorized = bool(kwargs.pop('vectorized', False))
    jac = kwargs.pop('jac', None)
    jac_sparsity = kwargs.pop('jac_sparsity', None)
    if kwargs:
        raise TypeError(f'Unsupported SciPy solver kwargs for accepted-step integration: {sorted(kwargs)}')

    solver_kwargs = dict(
        fun=rhs,
        t0=float(t_eval[0]),
        y0=np.asarray(y0, dtype=np.float64),
        t_bound=float(t_eval[-1]),
        first_step=first_step,
        max_step=max_step,
        rtol=rtol,
        atol=atol,
        vectorized=vectorized,
    )
    if solver_cls is not RK45:
        solver_kwargs['jac'] = jac
        solver_kwargs['jac_sparsity'] = jac_sparsity
    solver = solver_cls(**solver_kwargs)

    y_out = np.zeros((y0.size, t_eval.size), dtype=np.float64)
    y_out[:, 0] = np.asarray(y0, dtype=np.float64)
    next_eval_idx = 1
    tol_t = max(1.0e-12, abs(float(t_eval[-1]) - float(t_eval[0])) * 1.0e-12)

    while solver.status == 'running':
        message = solver.step()
        if solver.status == 'failed':
            raise RuntimeError(message or 'SciPy step solver failed.')
        if accepted_step_callback is not None:
            accepted_step_callback(float(solver.t), np.asarray(solver.y, dtype=np.float64).copy())
        interpolant = solver.dense_output()
        while next_eval_idx < t_eval.size and float(t_eval[next_eval_idx]) <= float(solver.t) + tol_t:
            y_out[:, next_eval_idx] = np.asarray(interpolant(float(t_eval[next_eval_idx])), dtype=np.float64)
            next_eval_idx += 1

    if next_eval_idx < t_eval.size:
        y_out[:, next_eval_idx:] = np.asarray(solver.y, dtype=np.float64)[:, None]
    return SolverResult(t=t_eval, y=y_out)


@register_solver('scipy_rk45')
def solve_scipy_rk45(rhs: RHSCallable, y0: np.ndarray, t_eval: np.ndarray, rtol: float, atol: float, **kwargs) -> SolverResult:
    if kwargs.get('accepted_step_callback') is not None:
        kwargs.pop('jac_sparsity', None)
        kwargs.pop('jac', None)
        return _solve_scipy_with_accepted_steps(RK45, rhs, y0, t_eval, rtol, atol, **kwargs)
    kwargs.pop('jac_sparsity', None)
    kwargs.pop('jac', None)
    res = solve_ivp(rhs, (float(t_eval[0]), float(t_eval[-1])), y0, t_eval=t_eval, method='RK45', rtol=rtol, atol=atol, **kwargs)
    if not res.success:
        raise RuntimeError(res.message)
    return SolverResult(t=res.t, y=res.y)


def _solve_scipy_stiff(method: str, solver_cls, rhs: RHSCallable, y0: np.ndarray, t_eval: np.ndarray, rtol: float, atol: float, **kwargs) -> SolverResult:
    if kwargs.get('accepted_step_callback') is not None:
        return _solve_scipy_with_accepted_steps(solver_cls, rhs, y0, t_eval, rtol, atol, **kwargs)
    jac = kwargs.pop('jac', None)
    jac_sparsity = kwargs.pop('jac_sparsity', None)
    res = solve_ivp(
        rhs,
        (float(t_eval[0]), float(t_eval[-1])),
        y0,
        t_eval=t_eval,
        method=method,
        rtol=rtol,
        atol=atol,
        jac=jac,
        jac_sparsity=jac_sparsity,
        **kwargs,
    )
    if not res.success:
        raise RuntimeError(res.message)
    return SolverResult(t=res.t, y=res.y)


@register_solver('scipy_bdf')
def solve_scipy_bdf(rhs: RHSCallable, y0: np.ndarray, t_eval: np.ndarray, rtol: float, atol: float, **kwargs) -> SolverResult:
    return _solve_scipy_stiff('BDF', BDF, rhs, y0, t_eval, rtol, atol, **kwargs)


@register_solver('scipy_radau')
def solve_scipy_radau(rhs: RHSCallable, y0: np.ndarray, t_eval: np.ndarray, rtol: float, atol: float, **kwargs) -> SolverResult:
    return _solve_scipy_stiff('Radau', Radau, rhs, y0, t_eval, rtol, atol, **kwargs)


class SolverFactory:
    @staticmethod
    def create(name: str) -> Callable[..., SolverResult]:
        return SolverRegistry.create(name)

    @staticmethod
    def registered_names() -> list[str]:
        return SolverRegistry.registered_names()
