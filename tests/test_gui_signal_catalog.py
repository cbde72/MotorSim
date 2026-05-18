from __future__ import annotations

from pathlib import Path

from thermo0d.gui.signal_catalog import (
    build_signal_catalog_for_project,
    generate_signal_alias_file,
    generate_signal_catalog_file,
)


def test_build_signal_catalog_for_project_has_current_outputs() -> None:
    project_dir = Path(__file__).resolve().parents[1] / "Projekte"
    catalog = build_signal_catalog_for_project(project_dir)
    full = catalog["full"]
    assert "cylinder_p_Pa" in full
    assert "intake_valve_mdot_kg_per_s" in full
    assert "transfer_slot_A_eff_forward_m2" in full
    assert "plotting_series_aliases" in catalog
    assert "signal_metadata" in catalog
    assert catalog["signal_metadata"]["cylinder_T_K"]["unit"] == "K"


def test_generate_signal_catalog_file_writes_yaml_and_alias_file(tmp_path: Path) -> None:
    project_dir = Path(__file__).resolve().parents[1] / "Projekte"
    out_path = tmp_path / "signals.yaml"
    alias_path = tmp_path / "aliases.yaml"
    generated = generate_signal_catalog_file(project_dir, out_path)
    generated_alias = generate_signal_alias_file(project_dir, alias_path)
    assert generated.exists()
    assert generated_alias.exists()
    text = generated.read_text(encoding="utf-8")
    alias_text = generated_alias.read_text(encoding="utf-8")
    assert "full:" in text
    assert "cylinder_theta_deg" in text
    assert "signals:" in alias_text
    assert "display_name:" in alias_text


def test_signal_catalog_marks_energy_rate_and_cumulative_metadata() -> None:
    project_dir = Path(__file__).resolve().parents[1] / "Projekte"
    catalog = build_signal_catalog_for_project(project_dir)
    meta = catalog["signal_metadata"]
    assert meta["cylinder_wall_heat_W"]["signal_kind"] == "rate"
    assert meta["cylinder_wall_heat_cycle_J"]["signal_kind"] == "cumulative"
    assert meta["cylinder_wall_heat_cycle_J"]["signal_family"] == "energy"
