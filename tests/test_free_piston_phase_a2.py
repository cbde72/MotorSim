from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from thermo0d.config.models import load_config
from thermo0d.input.model_builder import build_model_bundle
from thermo0d.model.free_piston.geometry import bounce_volume_from_position, cylinder_dvdt_from_velocity, cylinder_volume_from_position
from thermo0d.model.free_piston.rhs import compute_free_piston_rhs
from thermo0d.model.free_piston.simulator import simulate_free_piston
from thermo0d.model.free_piston.thermo import mass_from_pTV, pressure_from_state, specific_internal_energy_from_temperature, temperature_from_state


def _bundle() -> object:
    cfg = load_config(Path('Projekte/variants/free_piston_phase_a2.yaml'))
    return build_model_bundle(cfg, Path('Projekte/variants/free_piston_phase_a2.yaml'))


def test_free_piston_geometry_relations() -> None:
    assert cylinder_volume_from_position(2.5e-5, 0.00436, -0.008, 0.04) > 0.0
    assert cylinder_dvdt_from_velocity(0.00436, 2.0) == pytest.approx(-0.00872)
    assert bounce_volume_from_position(3.0e-4, 0.00436, -0.008, -0.04, 0.04) > 0.0


def test_free_piston_thermo_roundtrip() -> None:
    volume = 1.0e-4
    mass = mass_from_pTV(pressure_Pa=2.0e5, temperature_K=600.0, volume_m3=volume, gas_constant_J_per_kgK=287.0)
    u = specific_internal_energy_from_temperature(600.0, 718.0)
    T = temperature_from_state(mass, mass * u, 718.0)
    p = pressure_from_state(mass, mass * u, volume, 287.0, 718.0)
    assert T == pytest.approx(600.0)
    assert p == pytest.approx(2.0e5)


def test_free_piston_rhs_returns_finite_and_dxdt_equals_v() -> None:
    bundle = _bundle()
    dy = compute_free_piston_rhs(0.0, bundle.y_init.copy(), bundle)
    x_idx, v_idx = bundle.state_layout.free_piston_indices()
    assert np.all(np.isfinite(dy))
    assert dy[x_idx] == pytest.approx(bundle.y_init[v_idx])
    assert dy[bundle.state_layout.mass_index(bundle.cylinder_indices[0])] == pytest.approx(0.0)


def test_free_piston_simulation_runs() -> None:
    bundle = _bundle()
    result = simulate_free_piston(bundle)
    assert result.t.size > 2
    assert result.y.shape[1] == result.t.size
    assert np.all(np.isfinite(result.y))
    x_idx, _ = bundle.state_layout.free_piston_indices()
    x = result.y[x_idx, :]
    assert np.min(x) >= bundle.free_piston.x_min_m - 1.0e-12
    assert np.max(x) <= bundle.free_piston.x_max_m + 1.0e-12



def test_free_piston_a2_runs_without_classic_cylinder_placeholder() -> None:
    bundle = _bundle()
    assert bundle.cylinder_indices == [0]
    assert bundle.volume_names == ['cylinder']
    assert bundle.kin_matrix.shape[0] == 0
