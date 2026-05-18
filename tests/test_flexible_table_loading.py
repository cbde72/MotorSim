from pathlib import Path

from thermo0d.input.model_builder import MatrixModelBuilder


def test_model_builder_loads_header_and_tabbed_alpha_k(tmp_path: Path):
    path = tmp_path / "alpha_k.tsv"
    path.write_text(
        "# lift_mm  alphaK_in  alphaK_ex\n"
        "0.0\t0.0\t0.0\n"
        "1.0\t0.012432841\t0.012432841\n"
        "2.0\t0.02206704\t0.02206704\n",
        encoding="utf-8",
    )
    data = MatrixModelBuilder._load_csv_table(path, expected_cols=3)
    assert data.shape == (3, 3)
    assert float(data[1, 0]) == 1.0
    assert float(data[1, 1]) == 0.012432841
    assert float(data[1, 2]) == 0.012432841


def test_model_builder_loads_headered_lift_file(tmp_path: Path):
    path = tmp_path / "lift.tsv"
    path.write_text(
        "theta_deg_in\tlift_ex_mm\n"
        "0\t0\n"
        "1\t0.002970277\n"
        "2\t0.008970162\n",
        encoding="utf-8",
    )
    data = MatrixModelBuilder._load_csv_table(path, expected_cols=2)
    assert data.shape == (3, 2)
    assert float(data[2, 1]) == 0.008970162



def test_valve_lift_mm_header_format_is_auto_converted_to_m(tmp_path):
    from thermo0d.input.model_builder import MatrixModelBuilder

    path = tmp_path / "A156A1_IntakeVL.txt"
    path.write_text(
        "# theta_deg_in   lift\n"
        "0\t0\n"
        "1\t0.002394685\n"
        "120\t8.96424253\n"
        "143\t8.9625\t143\n"
        "286\t0\n",
        encoding="utf-8",
    )
    data = MatrixModelBuilder._load_csv_table(path, expected_cols=2, table_kind="valve_lift")
    assert data.shape[1] == 2
    assert abs(float(data[:, 1].max()) - 8.96424253e-3) < 1e-12


def test_gui_editor_profile_metrics_accepts_mm_lift_format(tmp_path):
    import pytest
    pytest.importorskip("PySide6")
    from thermo0d.gui.engine_gasexchange_editor import _editor_profile_metrics

    path = tmp_path / "A156A1_IntakeVL.txt"
    path.write_text(
        "# theta_deg_in   lift\n"
        "0 0\n"
        "1 0.002394685\n"
        "120 8.96424253\n"
        "286 0\n",
        encoding="utf-8",
    )
    duration_deg, max_lift_m = _editor_profile_metrics(path, "cam", "4T")
    assert duration_deg > 0.0
    assert abs(max_lift_m - 8.96424253e-3) < 1e-12


def test_valve_alpha_k_mm_header_format_is_auto_converted_to_m(tmp_path: Path):
    path = tmp_path / "alpha_k.tsv"
    path.write_text(
        "# lift_mm  alphaK_forward  alphaK_reverse\n"
        "0.0\t0.0\t0.0\n"
        "1.0\t0.016191683\t0.016191683\n"
        "10.0\t0.106298427\t0.106298427\n",
        encoding="utf-8",
    )
    data = MatrixModelBuilder._load_csv_table(path, expected_cols=3, table_kind="valve_alpha")
    assert data.shape == (3, 3)
    assert abs(float(data[1, 0]) - 1.0e-3) < 1e-12
    assert abs(float(data[2, 0]) - 10.0e-3) < 1e-12
    assert abs(float(data[2, 1]) - 0.106298427) < 1e-12


def test_valve_alpha_k_mm_without_header_is_inferred_and_auto_converted_to_m(tmp_path: Path):
    path = tmp_path / "alpha_k_plain.tsv"
    path.write_text(
        "0.0 0.0 0.0\n"
        "1.0 0.016191683 0.016191683\n"
        "10.0 0.106298427 0.106298427\n",
        encoding="utf-8",
    )
    data = MatrixModelBuilder._load_csv_table(path, expected_cols=3, table_kind="valve_alpha")
    assert data.shape == (3, 3)
    assert abs(float(data[1, 0]) - 1.0e-3) < 1e-12
    assert abs(float(data[2, 0]) - 10.0e-3) < 1e-12


def test_gui_editor_alpha_k_mm_header_format_is_auto_converted_to_m(tmp_path):
    import pytest
    pytest.importorskip("PySide6")
    from thermo0d.gui.engine_gasexchange_editor import _editor_load_csv_table

    path = tmp_path / "alpha_k_gui.tsv"
    path.write_text(
        "# lift_mm  alphaK_forward  alphaK_reverse\n"
        "0.0\t0.0\t0.0\n"
        "1.0\t0.016191683\t0.016191683\n"
        "10.0\t0.106298427\t0.106298427\n",
        encoding="utf-8",
    )
    rows = _editor_load_csv_table(path, expected_cols=3, table_kind="valve_alpha")
    assert abs(float(rows[1][0]) - 1.0e-3) < 1e-12
    assert abs(float(rows[2][0]) - 10.0e-3) < 1e-12
