from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / 'src'
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from thermo0d.app.cli import main, run
from thermo0d.app.paths import DEFAULT_PROJECT, DEFAULT_TEST_SPACE, DEFAULT_VARIANTS_DIR

SIMULATED_ARG_PRESETS: dict[str, list[str]] = {
    'project_default': [
        '--config', str(PROJECT_ROOT / 'Projekte' / 'config.yaml'),
        '--project', str(Path(DEFAULT_PROJECT)),
    ],
    'variant_batch': [
        '--project', str(Path(DEFAULT_PROJECT)),
        '--variants-dir', str(Path(DEFAULT_VARIANTS_DIR)),
        '--batch-variants',
        '--continue-on-error',
    ],
    'free_piston_v47': [
        '--config', str(PROJECT_ROOT / 'Projekte' / 'variants' / 'free_piston_GenSet_V53.yaml'),
        '--project', str(Path(DEFAULT_PROJECT)),
    ],
}

# Nur diesen Namen umstellen, wenn du ohne echte CLI-Argumente ein anderes Setup starten willst.
SELECTED_PRESET = 'free_piston_v47'



def _resolve_simulated_args(preset_name: str) -> list[str]:
    simulated_args = SIMULATED_ARG_PRESETS.get(preset_name)
    if simulated_args is None:
        available = ', '.join(sorted(SIMULATED_ARG_PRESETS))
        raise SystemExit(
            f"[ERROR] Unbekanntes simulated_args-Preset: {preset_name!r}. Verfügbar: {available}"
        )
    return list(simulated_args)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(run())

    simulated_args = _resolve_simulated_args(SELECTED_PRESET)
    print(f"[INFO] Keine Terminal-Argumente erkannt. Nutze Preset: {SELECTED_PRESET}")
    print(f"[INFO] simulated_args = {simulated_args}")
    raise SystemExit(main(simulated_args))
