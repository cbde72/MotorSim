from thermo0d.compute.solvers import SolverFactory


def test_solver_factory_lists_registered_names():
    names = SolverFactory.registered_names()
    assert 'euler' in names
    assert 'rk4' in names
