from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(slots=True, frozen=True)
class StateLayout:
    n_volumes: int
    total_size: int
    x_index: int | None = None
    v_index: int | None = None

    STATES_PER_VOLUME: ClassVar[int] = 6

    @classmethod
    def classic(cls, n_volumes: int) -> "StateLayout":
        n = int(n_volumes)
        return cls(n_volumes=n, total_size=cls.STATES_PER_VOLUME * n)

    @classmethod
    def free_piston(cls, n_volumes: int) -> "StateLayout":
        n = int(n_volumes)
        base = cls.STATES_PER_VOLUME * n
        return cls(n_volumes=n, total_size=base + 2, x_index=base, v_index=base + 1)

    def _base_index(self, volume_index: int) -> int:
        idx = int(volume_index)
        if idx < 0 or idx >= self.n_volumes:
            raise IndexError(f"volume_index out of range: {volume_index}")
        return self.STATES_PER_VOLUME * idx

    def gas_mass_index(self, volume_index: int) -> int:
        return self._base_index(volume_index)

    def mass_index(self, volume_index: int) -> int:
        return self.gas_mass_index(volume_index)

    def energy_index(self, volume_index: int) -> int:
        return self._base_index(volume_index) + 1

    def burned_mass_index(self, volume_index: int) -> int:
        return self._base_index(volume_index) + 2

    def air_mass_index(self, volume_index: int) -> int:
        return self._base_index(volume_index) + 3

    def residual_mass_index(self, volume_index: int) -> int:
        return self._base_index(volume_index) + 4

    def liquid_fuel_mass_index(self, volume_index: int) -> int:
        return self._base_index(volume_index) + 5

    def gas_mass_from_state(self, y, volume_index: int) -> float:
        return max(float(y[self.gas_mass_index(volume_index)]), 0.0)

    def burned_mass_from_state(self, y, volume_index: int) -> float:
        gas = self.gas_mass_from_state(y, volume_index)
        burned = float(y[self.burned_mass_index(volume_index)])
        if burned <= 0.0:
            return 0.0
        if burned >= gas:
            return gas
        return burned

    def air_mass_from_state(self, y, volume_index: int) -> float:
        gas = self.gas_mass_from_state(y, volume_index)
        burned = self.burned_mass_from_state(y, volume_index)
        air = float(y[self.air_mass_index(volume_index)])
        if air <= 0.0:
            return 0.0
        max_air = max(gas - burned, 0.0)
        if air >= max_air:
            return max_air
        return air

    def residual_mass_from_state(self, y, volume_index: int) -> float:
        return self.burned_mass_from_state(y, volume_index)

    def fresh_burned_mass_from_state(self, y, volume_index: int) -> float:
        return 0.0

    def liquid_fuel_mass_from_state(self, y, volume_index: int) -> float:
        liquid = float(y[self.liquid_fuel_mass_index(volume_index)])
        return liquid if liquid > 0.0 else 0.0

    def fuel_vapor_mass_from_state(self, y, volume_index: int) -> float:
        gas = self.gas_mass_from_state(y, volume_index)
        burned = self.burned_mass_from_state(y, volume_index)
        air = self.air_mass_from_state(y, volume_index)
        vapor = gas - burned - air
        return vapor if vapor > 0.0 else 0.0

    def total_fuel_mass_from_state(self, y, volume_index: int) -> float:
        return self.fuel_vapor_mass_from_state(y, volume_index) + self.liquid_fuel_mass_from_state(y, volume_index)

    def unburned_mass_from_state(self, y, volume_index: int) -> float:
        gas = self.gas_mass_from_state(y, volume_index)
        burned = self.burned_mass_from_state(y, volume_index)
        remaining = gas - burned
        return remaining if remaining > 0.0 else 0.0

    @property
    def has_free_piston_states(self) -> bool:
        return self.x_index is not None and self.v_index is not None

    def free_piston_indices(self) -> tuple[int, int]:
        if self.x_index is None or self.v_index is None:
            raise ValueError("This state layout has no free-piston states")
        return int(self.x_index), int(self.v_index)

    def index_of(self, name: str, volume_names: list[str] | tuple[str, ...] | None = None) -> int:
        labels = self.state_labels(volume_names=volume_names)
        try:
            return labels.index(str(name))
        except ValueError as exc:
            raise KeyError(f"Unknown state label: {name}") from exc

    def state_labels(self, volume_names: list[str] | tuple[str, ...] | None = None) -> list[str]:
        labels: list[str] = []
        for i in range(self.n_volumes):
            base = f"vol_{i}" if not volume_names or i >= len(volume_names) else str(volume_names[i])
            labels.append(f"{base}_m_kg")
            labels.append(f"{base}_U_J")
            labels.append(f"{base}_m_burned_kg")
            labels.append(f"{base}_m_air_kg")
            labels.append(f"{base}_m_residual_kg")
            labels.append(f"{base}_m_fuel_liquid_kg")
        if self.has_free_piston_states:
            labels.append("free_piston_x_m")
            labels.append("free_piston_v_m_per_s")
        return labels
