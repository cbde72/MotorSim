from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from thermo0d.config.constants import FeatureCol, VolumeCol, WallCol
from thermo0d.config.models import load_config
from thermo0d.input.model_builder import build_model_bundle
from thermo0d.model.free_piston.geometry import bounce_volume_from_position, cylinder_dvdt_from_velocity, cylinder_volume_from_position
from thermo0d.model.free_piston.combustion_latch import compute_lambda_energy_from_cylinder_mass, update_free_piston_combustion_latch_state
from thermo0d.model.free_piston.rhs import _apply_overlap_scavenging_correction, compute_free_piston_rhs
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


def test_free_piston_v11_initial_rhs_is_finite_with_two_wall_heat_cylinders() -> None:
    cfg_path = Path('Projekte/variants/free_piston_GenSet_V11.yaml')
    cfg = load_config(cfg_path)
    bundle = build_model_bundle(cfg, cfg_path)

    dy = compute_free_piston_rhs(0.0, bundle.y_init.copy(), bundle)

    assert bundle.cylinder_indices == [0, 1]
    assert int(bundle.free_piston.mechanical_dofs) == 1
    assert bundle.free_piston.volume_mechanical_dof.tolist()[:4] == [0, 0, 0, 0]
    assert bundle.free_piston.volume_mechanical_sign.tolist()[:4] == [1.0, -1.0, 1.0, -1.0]
    assert np.all(bundle.wall_bore_by_vol[bundle.cylinder_indices] > 0.0)
    assert np.all(bundle.wall_ups_by_vol[bundle.cylinder_indices] > 0.0)
    assert np.all(np.isfinite(dy))


def test_free_piston_v40_applies_woschni_wall_heat_to_bounce_compressors() -> None:
    cfg_path = Path('Projekte/variants/free_piston_GenSet_V40.yaml')
    cfg = load_config(cfg_path)
    bundle = build_model_bundle(cfg, cfg_path)
    compressor_indices = [bundle.volume_names.index('compressor_1'), bundle.volume_names.index('compressor_2')]

    for idx in compressor_indices:
        wall_idx = int(bundle.vol_matrix[idx, VolumeCol.WALL_ROW])
        assert wall_idx >= 0
        assert bundle.wall_bore_by_vol[idx] == pytest.approx(0.07)
        assert bundle.wall_matrix[wall_idx, WallCol.WALL_TEMP] == pytest.approx(350.0)
        assert bundle.wall_matrix[wall_idx, WallCol.WALL_AREA] == pytest.approx(0.0315)

    y = bundle.y_init.copy()
    dy_with_wall = compute_free_piston_rhs(0.0, y, bundle)
    bundle.feature_flags[FeatureCol.WALL_HEAT] = 0
    dy_without_wall = compute_free_piston_rhs(0.0, y, bundle)

    for idx in compressor_indices:
        energy_idx = bundle.state_layout.energy_index(idx)
        assert dy_with_wall[energy_idx] != pytest.approx(dy_without_wall[energy_idx])


def test_free_piston_v12_latches_each_cylinder_against_its_own_slots() -> None:
    cfg_path = Path('Projekte/variants/free_piston_GenSet_V12.yaml')
    cfg = load_config(cfg_path)
    bundle = build_model_bundle(cfg, cfg_path)
    fp = bundle.free_piston
    y = bundle.y_init.copy()
    x_idx, v_idx = bundle.state_layout.free_piston_indices()
    cyl1, cyl2 = bundle.cylinder_indices[:2]

    # cylinder_1 is near TDC and compressing, while the mirrored cylinder_2 is
    # near BDC with ports open. The latch must only inspect cylinder_1 slots.
    y[x_idx] = 0.010
    y[v_idx] = -1.0
    fp.runtime_slots_were_open_by_vol = np.zeros(bundle.vol_matrix.shape[0], dtype=np.int64)
    fp.runtime_latch_valid_by_vol = np.zeros(bundle.vol_matrix.shape[0], dtype=np.int64)
    fp.runtime_latched_energy_by_vol_J = np.zeros(bundle.vol_matrix.shape[0], dtype=np.float64)
    fp.runtime_slots_were_open_by_vol[cyl1] = 1

    update_free_piston_combustion_latch_state(bundle, 0.02, y)

    assert int(fp.runtime_latch_valid_by_vol[cyl1]) == 1
    assert float(fp.runtime_latched_energy_by_vol_J[cyl1]) > 0.0
    assert int(fp.runtime_latch_valid_by_vol[cyl2]) == 0


def test_overlap_scavenging_correction_can_apply_to_each_cylinder() -> None:
    class FP:
        scavenging_enabled = True
        scavenging_model = 'overlap_short_circuit_0d'
        scavenging_factor = 1.25
        scavenging_max_trapping_efficiency = 0.92
        scavenging_short_circuit_start_ratio = 0.70
        scavenging_short_circuit_slope = 0.35
        scavenging_max_short_circuit_fraction = 0.35
        scavenging_min_residual_fraction = 0.03
        runtime_scavenging_transfer_in_kg_per_s = 0.0
        runtime_scavenging_exhaust_out_kg_per_s = 0.0
        runtime_scavenging_burned_correction_kg_per_s = 0.0
        runtime_scavenging_short_circuit_fraction = 0.0
        runtime_scavenging_transfer_in_by_vol_kg_per_s = np.zeros(2, dtype=np.float64)
        runtime_scavenging_exhaust_out_by_vol_kg_per_s = np.zeros(2, dtype=np.float64)
        runtime_scavenging_burned_correction_by_vol_kg_per_s = np.zeros(2, dtype=np.float64)
        runtime_scavenging_short_circuit_fraction_by_vol = np.zeros(2, dtype=np.float64)

    dy = np.zeros(8, dtype=np.float64)
    y = np.zeros(8, dtype=np.float64)
    mass_indices = np.array([0, 1], dtype=np.int32)
    burned_indices = np.array([2, 3], dtype=np.int32)
    air_indices = np.array([4, 5], dtype=np.int32)
    residual_indices = np.array([6, 7], dtype=np.int32)
    environment_is_fixed = np.zeros(2, dtype=np.int64)
    y[mass_indices] = 1.0
    y[burned_indices] = 0.5
    y[air_indices] = 0.5
    y[residual_indices] = 0.5

    _apply_overlap_scavenging_correction(
        dy,
        FP,
        0,
        y,
        mass_indices,
        burned_indices,
        air_indices,
        residual_indices,
        environment_is_fixed,
        transfer_in_rate_kg_per_s=0.2,
        transfer_air_in_rate_kg_per_s=0.2,
        exhaust_out_by_vol_kg_per_s=np.array([0.0, 0.1]),
    )
    _apply_overlap_scavenging_correction(
        dy,
        FP,
        1,
        y,
        mass_indices,
        burned_indices,
        air_indices,
        residual_indices,
        environment_is_fixed,
        transfer_in_rate_kg_per_s=0.2,
        transfer_air_in_rate_kg_per_s=0.2,
        exhaust_out_by_vol_kg_per_s=np.array([0.1, 0.0]),
    )

    assert dy[air_indices[0]] != pytest.approx(0.0)
    assert dy[air_indices[1]] != pytest.approx(0.0)
    assert FP.runtime_scavenging_transfer_in_by_vol_kg_per_s.tolist() == pytest.approx([0.2, 0.2])
    assert np.count_nonzero(FP.runtime_scavenging_burned_correction_by_vol_kg_per_s) == 2


def test_slot_close_lambda_energy_uses_cylinder_specific_combustion_values() -> None:
    bundle = SimpleNamespace(
        free_piston=SimpleNamespace(
            combustion_lambda_target=1.0,
            combustion_afr_stoich_kg_air_per_kg_fuel=10.0,
            combustion_efficiency_0to1=1.0,
            combustion_lhv_J_per_kg=100.0,
        ),
        combustion_lambda_target_by_vol=np.array([1.0, 2.0], dtype=np.float64),
        combustion_afr_stoich_by_vol=np.array([10.0, 20.0], dtype=np.float64),
        combustion_efficiency_by_vol=np.array([1.0, 0.5], dtype=np.float64),
        combustion_lhv_by_vol=np.array([100.0, 200.0], dtype=np.float64),
    )

    fuel_0, energy_0 = compute_lambda_energy_from_cylinder_mass(0.1, bundle, 0)
    fuel_1, energy_1 = compute_lambda_energy_from_cylinder_mass(0.1, bundle, 1)

    assert fuel_0 == pytest.approx(0.1 / (1.0 * 10.0))
    assert energy_0 == pytest.approx(fuel_0 * 100.0)
    assert fuel_1 == pytest.approx(0.1 / (2.0 * 20.0))
    assert energy_1 == pytest.approx(fuel_1 * 200.0 * 0.5)
