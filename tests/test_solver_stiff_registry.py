from thermo0d.compute.solvers import SolverFactory


def test_solver_factory_includes_stiff_solvers():
    names = SolverFactory.registered_names()
    assert 'scipy_bdf' in names
    assert 'scipy_radau' in names
