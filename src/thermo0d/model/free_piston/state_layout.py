
from __future__ import annotations

from thermo0d.core.state_layout import StateLayout


def build_free_piston_state_layout(n_volumes: int) -> StateLayout:
    return StateLayout.free_piston(n_volumes)
