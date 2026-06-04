from __future__ import annotations

import numpy as np

from thermo0d.model.free_piston.builder import _load_hcci_ignition_delay_table
from thermo0d.model.free_piston.combustion_latch import _tabulated_hcci_ignition_delay_s


class _FakeNpz:
    def __init__(self, payload):
        self._payload = payload

    def __contains__(self, key):
        return key in self._payload

    def __getitem__(self, key):
        return self._payload[key]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_tabulated_hcci_delay_loads_flat_npz_and_interpolates(monkeypatch):
    temperatures = np.array([800.0, 1000.0])
    pressures = np.array([20.0, 40.0])
    lambdas = np.array([1.0, 2.0])
    egr_rates = np.array([0.0, 20.0])
    points = np.meshgrid(temperatures, pressures, lambdas, egr_rates, indexing="ij")
    delay = (
        1.0e-3
        + points[0] * 1.0e-7
        + points[1] * 1.0e-5
        + points[2] * 2.0e-4
        + points[3] * 5.0e-4
    )
    def fake_load(_path):
        return _FakeNpz(
            {
                "temperatures": points[0].reshape(-1),
                "pressures": points[1].reshape(-1),
                "lambdas": points[2].reshape(-1),
                "Phi": (1.0 / points[2]).reshape(-1),
                "egr_rates": points[3].reshape(-1),
                "zuendverzug_s": delay.reshape(-1),
            }
        )

    monkeypatch.setattr("thermo0d.model.free_piston.builder.np.load", fake_load)
    table = _load_hcci_ignition_delay_table(__file__)
    tau = _tabulated_hcci_ignition_delay_s(
        table,
        temp_K=900.0,
        pressure_Pa=30.0e5,
        lam=1.5,
        residual_fraction=0.1,
    )

    expected = 1.0e-3 + 900.0 * 1.0e-7 + 30.0 * 1.0e-5 + 1.5 * 2.0e-4 + 10.0 * 5.0e-4
    assert np.isclose(tau, expected)


def test_tabulated_hcci_delay_clamps_outside_axes(monkeypatch):
    def fake_load(_path):
        return _FakeNpz(
            {
                "Temperatur_K": np.array([800.0, 1000.0]),
                "Druck_bar": np.array([20.0, 40.0]),
                "Lambda": np.array([1.0]),
                "EGR_Rate": np.array([0.0]),
                "Zuendverzug_s": np.array([[[[0.004]], [[0.003]]], [[[0.002]], [[0.001]]]]),
            }
        )

    monkeypatch.setattr("thermo0d.model.free_piston.builder.np.load", fake_load)
    table = _load_hcci_ignition_delay_table(__file__)
    tau = _tabulated_hcci_ignition_delay_s(
        table,
        temp_K=1200.0,
        pressure_Pa=50.0e5,
        lam=2.0,
        residual_fraction=0.5,
    )

    assert tau == 0.001
