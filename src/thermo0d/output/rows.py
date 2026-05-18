from __future__ import annotations

import numpy as np

from thermo0d.output.reconstruction import ReconstructedSeries, SignalReconstructionService


class ResultRowBuilder:
    @staticmethod
    def _ordered_keys(series: ReconstructedSeries) -> list[str]:
        keys: list[str] = []
        seen: set[str] = set()
        for key in ('t_s', 'theta_local_deg', 'theta_deg', 'cycle_index'):
            if key not in seen:
                keys.append(key)
                seen.add(key)
        for key in series.columns.keys():
            if key in seen:
                continue
            keys.append(key)
            seen.add(key)
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
