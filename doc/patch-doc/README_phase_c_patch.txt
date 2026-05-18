Phase-C patch for free-piston path.

Included changes:
- Free-piston geometry entries in console/check-report
- Oscillation metrics from turning points
- Check-report/geometry console output enabled for free-piston runs
- Free-piston default plot layouts over time
- Signal catalog support for free-piston signals
- RootConfig accepts versioning metadata
- New example configs: examples/free_piston_phase_a3.yaml and examples/free_piston_phase_c.yaml
- New tests: tests/test_free_piston_phase_c.py

Validated locally with:
PYTHONPATH=src pytest -q tests/test_free_piston_phase_a.py tests/test_free_piston_phase_a2.py tests/test_free_piston_phase_c.py tests/test_gui_signal_catalog.py -q
