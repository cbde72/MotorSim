from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from thermo0d.output.geometry_report import build_geometry_markdown, build_last_cycle_entries


def _free_piston_rows() -> list[dict[str, float]]:
    times = np.array([0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45], dtype=float)
    xpos = np.array([1.0, 0.5, 0.0, 0.5, 1.0, 0.5, 0.0, 0.5, 1.0, 0.5], dtype=float)
    vel = np.array([0.0, -10.0, -1.0, 10.0, 1.0, -10.0, -1.0, 10.0, 1.0, -10.0], dtype=float)
    vol = np.array([1.0, 2.0, 3.0, 2.0, 1.0, 2.0, 3.0, 2.0, 1.0, 2.0], dtype=float) * 1.0e-4
    mass = np.array([1.0, 1.1, 1.2, 1.1, 1.0, 1.1, 1.2, 1.1, 1.0, 1.1], dtype=float) * 1.0e-6
    rows: list[dict[str, float]] = []
    for idx, t_s in enumerate(times):
        rows.append({
            't_s': float(t_s),
            'cycle_index': float(idx // 5),
            'free_piston_x_m': float(xpos[idx]),
            'free_piston_v_m_per_s': float(vel[idx]),
            'cylinder_p_Pa': 2.0e5,
            'cylinder_V_m3': float(vol[idx]),
            'cylinder_m_kg': float(mass[idx]),
            'cylinder_piston_work_W': 1000.0,
            'cylinder_wall_heat_W': -50.0,
            'cylinder_added_energy_W': 200.0,
        })
    return rows


def _bundle_for_last_cycle() -> SimpleNamespace:
    return SimpleNamespace(
        architecture='free_piston',
        free_piston=SimpleNamespace(
            piston_area_m2=1.0e-4,
            moving_mass_kg=1.0,
            piston_diameter_m=0.08,
            compression_ratio=10.0,
            clearance_volume_m3=1.0e-5,
            x_min_m=0.0,
            x_max_m=1.0,
            initial_cylinder_volume_m3=2.0e-4,
            bounce_chamber_diameter_m=0.05,
            bounce_chamber_length_m=0.08,
            bounce_compression_ratio=5.0,
            bounce_chamber_cross_section_m2=2.0e-3,
            bounce_swept_volume_m3=1.0e-4,
            bounce_area_m2=2.0e-3,
            bounce_chamber_min_volume_m3=5.0e-5,
            bounce_chamber_volume0_m3=1.5e-4,
        ),
        volume_names=['cylinder'],
        cylinder_indices=[],
        vol_matrix=np.zeros((0, 8), dtype=float),
        conn_matrix=np.zeros((0, 20), dtype=float),
    )


def test_build_last_cycle_entries_uses_last_full_ut_ot_ut_window_for_free_piston() -> None:
    entries = build_last_cycle_entries(_bundle_for_last_cycle(), _free_piston_rows())
    data = {entry.metric_name: entry.value for entry in entries}

    assert data['time_start_s'] == 0.20
    assert data['time_end_s'] == 0.40
    assert data['time_duration_s'] == 0.20
    assert data['time_duration_ms'] == 200.0
    assert data['frequency_Hz'] == 5.0
    assert data['piston_work_Nm'] == 200.0
    assert data['wall_heat_loss_J'] == 10.0
    assert data['added_energy_J'] == 40.0
    assert data['imep_bar'] == pytest.approx(10.0)
    assert data['cylinder_mass_min_mg'] == 1.0
    assert data['cylinder_mass_max_mg'] == 1.2
    assert data['cylinder_mass_mean_mg'] == 1.08
    assert data['last_stroke_mm'] == 1000.0
    assert data['last_half_stroke_plus_mm'] == 500.0
    assert data['last_half_stroke_minus_mm'] == -500.0
    assert data['piston_speed_max_m_per_s'] == 10.0
    assert data['piston_speed_min_m_per_s'] == -10.0
    assert data['piston_speed_mean_m_per_s'] == 0.2


def test_geometry_markdown_appends_last_cycle_section_after_geometry_overview() -> None:
    markdown = build_geometry_markdown(_bundle_for_last_cycle(), rows=_free_piston_rows())
    geom_pos = markdown.index('# Geometrie-Übersicht')
    cycle_pos = markdown.index('# Last-Cycle')
    assert cycle_pos > geom_pos
    assert 'Zyklusdefinition: letztes vollständiges Kolbenfenster UT → OT → UT.' in markdown
    assert '| time_start_s | 0.2 | s |' in markdown
    assert '| imep_bar | 10.0 | bar |' in markdown
    assert '| piston_work_Nm | 200.0 | Nm |' in markdown
    assert '| wall_heat_loss_J | 10.0 | J |' in markdown
    assert '| added_energy_J | 40.0 | J |' in markdown
    assert '| cylinder_mass_mean_mg | 1.1 | mg |' in markdown
    assert '| last_stroke_mm | 1000.0 | mm |' in markdown
    assert '| last_half_stroke_plus_mm | 500.0 | mm |' in markdown
    assert '| last_half_stroke_minus_mm | -500.0 | mm |' in markdown
