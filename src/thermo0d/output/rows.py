from __future__ import annotations

import re

import numpy as np

from thermo0d.output.reconstruction import ReconstructedSeries, SignalReconstructionService


class ResultRowBuilder:
    _GROUP_RANK = {
        'cylinder': 10,
        'compressor': 20,
        'bounce': 30,
        'receiver': 40,
        'exhaust_plenum': 50,
        'ambient_in': 60,
        'ambient_out': 61,
        'free_piston': 70,
        'transfer_slot': 80,
        'exhaust_slot': 81,
    }

    @staticmethod
    def _natural_parts(text: str) -> tuple[tuple[int, object], ...]:
        parts: list[tuple[int, object]] = []
        for part in re.split(r'(\d+)', str(text)):
            if part.isdigit():
                parts.append((1, int(part)))
            elif part:
                parts.append((0, part))
        return tuple(parts)

    @classmethod
    def _entity_prefix(cls, key: str) -> tuple[str, str]:
        parts = str(key).split('_')
        if len(parts) >= 2 and parts[1].isdigit():
            return f'{parts[0]}_{parts[1]}', '_'.join(parts[2:])
        if len(parts) >= 3 and parts[2].isdigit():
            two = f'{parts[0]}_{parts[1]}'
            if two in cls._GROUP_RANK:
                return f'{two}_{parts[2]}', '_'.join(parts[3:])
        if len(parts) >= 2:
            two = f'{parts[0]}_{parts[1]}'
            if two in cls._GROUP_RANK:
                return two, '_'.join(parts[2:])
        if parts and parts[0] in cls._GROUP_RANK:
            return parts[0], '_'.join(parts[1:])
        return str(key), ''

    @classmethod
    def _group_sort_key(cls, key: str, original_index: int) -> tuple[object, ...]:
        prefix, suffix = cls._entity_prefix(key)
        prefix_base = re.sub(r'_\d+$', '', prefix)
        rank = cls._GROUP_RANK.get(prefix_base, 500)
        return (
            rank,
            cls._natural_parts(prefix),
            cls._natural_parts(suffix),
            original_index,
        )

    @staticmethod
    def _ordered_keys(series: ReconstructedSeries) -> list[str]:
        keys: list[str] = []
        seen: set[str] = set()
        for key in ('t_s', 'theta_local_deg', 'theta_deg', 'cycle_index'):
            if key not in seen:
                keys.append(key)
                seen.add(key)
        grouped: list[tuple[int, str]] = []
        for idx, key in enumerate(series.columns.keys()):
            if key in seen:
                continue
            grouped.append((idx, key))
            seen.add(key)
        for original_index, key in sorted(grouped, key=lambda item: ResultRowBuilder._group_sort_key(item[1], item[0])):
            keys.append(key)
        return keys

    @staticmethod
    def from_reconstructed(series: ReconstructedSeries) -> list[dict[str, float | int]]:
        if series.n_samples <= 0:
            return []
        columns = series.as_columns()
        ordered_keys = ResultRowBuilder._ordered_keys(series)
        n_samples = int(series.n_samples)
        rows: list[dict[str, float | int]] = []
        for idx in range(n_samples):
            row: dict[str, float | int] = {}
            for key in ordered_keys:
                arr = columns.get(key)
                if arr is None:
                    continue
                value = arr[idx]
                if key == 'cycle_index':
                    row[key] = int(value)
                elif np.issubdtype(np.asarray(arr).dtype, np.integer):
                    row[key] = int(value)
                else:
                    row[key] = float(value)
            rows.append(row)
        return rows

    @staticmethod
    def build(bundle, t: np.ndarray, y: np.ndarray, cycle_indices: np.ndarray) -> list[dict[str, float | int]]:
        series = SignalReconstructionService.build(bundle, t, y, cycle_indices)
        return ResultRowBuilder.from_reconstructed(series)
