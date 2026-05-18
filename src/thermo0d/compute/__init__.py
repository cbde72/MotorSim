"""Public compute-layer exports.

Keeps the compute package entry point compact while re-exporting the analysis,
executor and solver symbols used by higher layers.
"""

from thermo0d.compute.analysis import CycleIndexCalculator, CycleSummary, CycleSummaryCalculator
from thermo0d.compute.executor import SimulationExecutionResult, SimulationExecutor
from thermo0d.compute.solvers import SolverFactory, SolverRegistry, SolverResult, register_solver

__all__ = [
    "CycleIndexCalculator",
    "CycleSummary",
    "CycleSummaryCalculator",
    "SimulationExecutionResult",
    "SimulationExecutor",
    "SolverFactory",
    "SolverRegistry",
    "SolverResult",
    "register_solver",
]
