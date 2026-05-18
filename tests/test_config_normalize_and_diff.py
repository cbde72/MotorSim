from thermo0d.config_versioning import diff_config_dicts, migrate_config_data, normalize_config_data


def test_normalize_adds_canonical_blocks_and_versioning():
    raw = {"simulation": {"solver": {"method": "rk4", "rtol": 1e-6, "atol": 1e-9}, "dt_s": 1e-5, "total_cycles": 3, "save_last_cycles": 1}}
    normalized = normalize_config_data(raw)
    assert normalized["preprocessing"]["engine"]["cycle_type"] == "4t"
    assert normalized["simulation"]["solver"]["kind"] == "rk4"
    assert "versioning" in normalized
    assert normalized["postprocessing"]["sampling"]["mode"] == "crank_angle"


def test_diff_reports_changes_compactly():
    old = {"a": 1, "b": {"c": 2}}
    new = {"a": 2, "b": {"c": 2, "d": 3}}
    diff = diff_config_dicts(old, new)
    assert "~ a = 1 -> 2" in diff
    assert "+ b.d = 3" in diff


def test_migrate_then_normalize_keeps_current_names():
    raw = {"postprocessing": {"csv_sep": ";", "sampling": {"mode": "angle", "step_ca_deg": 2.0}}}
    upgraded = migrate_config_data(raw)
    normalized = normalize_config_data(raw)
    assert "csv_separator" in upgraded["postprocessing"]
    assert normalized["postprocessing"]["sampling"]["mode"] == "crank_angle"
    assert normalized["postprocessing"]["sampling"]["step_deg"] == 2.0
