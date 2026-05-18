from __future__ import annotations


def test_import_core_modules():
    import thermo0d.config.constants  # noqa: F401
    import thermo0d.config.models  # noqa: F401
    import thermo0d.physics.flow  # noqa: F401
    import thermo0d.physics.kinematics  # noqa: F401
    import thermo0d.input.model_builder  # noqa: F401
    import thermo0d.physics.rhs  # noqa: F401
    import thermo0d.app.runner  # noqa: F401
    import thermo0d.compute.solvers  # noqa: F401
