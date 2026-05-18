from thermo0d.config.schema_meta import meta_for


def test_expected_editor_field_metadata_exists():
    assert meta_for("simulation.solver.kind") is not None
    assert meta_for("simulation.solver.kind").choices
    assert meta_for("initial_pressure_Pa").help_text
    assert meta_for("postprocessing.sampling.step_deg").default == 1.0
