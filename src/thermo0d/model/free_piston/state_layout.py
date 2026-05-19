
from __future__ import annotations

from thermo0d.core.state_layout import StateLayout


def build_free_piston_state_layout(n_volumes: int, mechanical_dofs: int = 1) -> StateLayout:
    if int(mechanical_dofs) == 1:
        return StateLayout.free_piston(n_volumes)
    return StateLayout.free_piston_multi(n_volumes, mechanical_dofs)
