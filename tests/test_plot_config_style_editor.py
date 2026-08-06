from pathlib import Path

from thermo0d.gui.plot_config_style_editor import SeriesRef, apply_rules, default_template_document, iter_series, rule_matches


def test_iter_series_finds_nested_plot_series() -> None:
    document = {
        "figures": [
            {
                "title": "Overview",
                "subplots": [
                    {
                        "title": "Pressure",
                        "series": [{"signal_key": "cylinder_1_p_pa", "label": "Cylinder 1"}],
                    }
                ],
            }
        ]
    }
    refs = list(iter_series(Path("plot.yaml"), document))
    assert len(refs) == 1
    assert refs[0].figure_title == "Overview"
    assert refs[0].series["signal_key"] == "cylinder_1_p_pa"


def test_higher_priority_component_rule_overrides_generic_pressure() -> None:
    series = {"signal_key": "cylinder_1_pressure_pa", "label": "Cylinder 1 pressure"}
    ref = SeriesRef(Path("plot.yaml"), 0, 0, 0, "Pressure", "Cylinder pressure", series)
    rules = default_template_document()["templates"][0]["rules"]
    changed = apply_rules(ref, rules)
    assert "color" in changed
    assert series["color"] == "#93C5FD"


def test_compressor_and_transfer_pressure_shades_are_distinct() -> None:
    rules = default_template_document()["templates"][0]["rules"]
    compressor = {"signal_key": "compressor_1_pressure_pa"}
    transfer = {"signal_key": "transfer_pressure_pa"}
    apply_rules(SeriesRef(Path("a.yaml"), 0, 0, 0, "", "", compressor), rules)
    apply_rules(SeriesRef(Path("a.yaml"), 0, 0, 1, "", "", transfer), rules)
    assert compressor["color"] == "#DBEAFE"
    assert transfer["color"] == "#172554"


def test_mass_flow_rule_sets_dash_dot() -> None:
    series = {"signal_key": "intake_mass_flow_kg_s"}
    rules = default_template_document()["templates"][0]["rules"]
    apply_rules(SeriesRef(Path("a.yaml"), 0, 0, 0, "", "", series), rules)
    assert series["line_style"] == "-."


def test_simple_contains_and_wildcard_rules_need_no_regex() -> None:
    text = "cylinder_1_pressure_pa cylinder pressure"
    assert rule_matches({"pattern": "cylinder_1", "match_mode": "contains"}, text)
    assert rule_matches({"pattern": "*pressure_pa*", "match_mode": "wildcard"}, text)
