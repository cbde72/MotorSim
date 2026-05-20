# MotorSim

MotorSim is a Python-based 0D thermodynamic simulation toolkit for engine and
free-piston concepts. The repository contains the simulation core, YAML
configuration variants, postprocessing and plotting utilities, GUI helpers, and
regression tests.

The current focus is on configurable engine topologies and opposed/free-piston
generator variants, including local piston kinematics, slot-close combustion
latches, signal reconstruction, CSV/Excel export, and last-cycle plots.

## Repository Layout

```text
src/thermo0d/        Simulation, configuration, physics, output, and GUI code
scripts/             Convenience launchers for simulations and editors
Projekte/            Project data, variant YAML files, and plot configurations
doc/                 Project notes and browser-based documentation assets
tests/               Pytest regression and contract tests
test_cases/          Fixture-style simulation cases for tests
tools/               Supporting maintenance and helper scripts
```

Generated simulation outputs are intentionally ignored by Git, especially
`Projekte/results/` and `Projekte/variants/results/`.

## Requirements

Use Python 3.12 or newer where possible. The project is currently source-tree
based and does not include a pinned dependency lock file.

Commonly used runtime and test packages include:

```bash
pip install numpy scipy pandas pyyaml matplotlib openpyxl pytest
```

Depending on the workflow, optional GUI or plotting features may require
additional packages available in the local development environment.

## Quick Start

Run a configured simulation from the repository root:

```bash
set PYTHONPATH=src
python scripts/run_simulation.py --config Projekte/variants/free_piston_GenSet_V13.yaml --project Projekte
```

On PowerShell:

```powershell
$env:PYTHONPATH = "src"
python scripts/run_simulation.py --config Projekte/variants/free_piston_GenSet_V13.yaml --project Projekte
```

If `scripts/run_simulation.py` is started without command-line arguments, it
uses the preset selected in that file.

## Batch Runs

Run all YAML variants from the variants directory:

```bash
python scripts/run_simulation.py --project Projekte --variants-dir Projekte/variants --batch-variants --continue-on-error
```

Use `--dry-run` to check which configuration files would be resolved without
starting the simulations:

```bash
python scripts/run_simulation.py --project Projekte --variants-dir Projekte/variants --batch-variants --dry-run
```

## Tests

Run the test suite with:

```bash
set PYTHONPATH=src
pytest tests
```

Targeted Free-Piston tests:

```bash
pytest tests/test_free_piston_phase_a2.py tests/test_free_piston_reconstruction_local_kinematics.py
```

## Outputs

Typical simulation artifacts include:

- CSV time series
- optional Excel exports
- plot images
- geometry and last-cycle reports
- run and failure logs

Output folders are created below the configured project result directories and
are excluded from version control.

## Free-Piston Notes

The opposed/free-piston variants in `Projekte/variants/` use cylinder-local
signals such as:

- `cylinder_1_piston_x_m`
- `cylinder_2_piston_x_m`
- `cylinder_1_combustion_energy_latched_J`
- `cylinder_2_combustion_energy_latched_J`
- `cylinder_1_indicated_power_W`
- `cylinder_2_indicated_power_W`

Detailed signal documentation is maintained in `doc/README.md`.

## Documentation

The `doc/` directory contains additional engineering notes and a static
browser-based documentation/editor surface. It can be opened directly from the
filesystem or served locally when the helper script is available.

## Development Notes

- Keep generated result files out of commits.
- Prefer adding focused regression tests when changing simulation behavior.
- Variant YAML files in `Projekte/variants/` are part of the tracked examples.
- Use the existing configuration and reconstruction helpers before adding new
  ad-hoc output logic.
