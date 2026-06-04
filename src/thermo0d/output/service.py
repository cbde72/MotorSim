from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

import numpy as np

from thermo0d.output.pipeline import PipelinePostprocessingService


@dataclass(slots=True)
class PostprocessingArtifacts:
    csv_path: str | None
    excel_path: str | None
    rhs_derivatives_csv_path: str | None
    export_rows: list[dict[str, float | int]]
    summary_path: str | None = None
    summary_text_path: str | None = None
    summary_markdown_path: str | None = None
    last_cycle_uniform_csv_path: str | None = None
    last_cycle_uniform_rows: list[dict[str, float | int]] | None = None
    free_piston_last_ut_ot_ut_csv_path: str | None = None
    free_piston_last_ut_ot_ut_rows: list[dict[str, float | int]] | None = None
    check_report_csv_path: str | None = None
    check_report_html_path: str | None = None
    check_report_metrics: list[object] | None = None
    generated_plot_paths: list[str] = field(default_factory=list)
    plot_layout_paths: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)


class PostprocessingService:
    def __init__(self, bundle, config_path: str | Path):
        self.bundle = bundle
        self.config_path = Path(config_path).resolve()

    def run(self, t: np.ndarray, y: np.ndarray, cycle_indices: np.ndarray, *, excel: bool | None = None) -> PostprocessingArtifacts:
        del excel
        mode = str(getattr(self.bundle.postprocessing, "mode", "pipeline") or "pipeline").strip().lower()
        if mode != "pipeline":
            raise RuntimeError(
                "Der Legacy-Postprocessing-Pfad ist deaktiviert. "
                "Bitte postprocessing.mode auf 'pipeline' setzen."
            )

        started = perf_counter()
        pipeline_artifacts = PipelinePostprocessingService(self.bundle, self.config_path).run(t, y, cycle_indices)
        timings = dict(pipeline_artifacts.timings)
        timings["postprocessing"] = perf_counter() - started
        return PostprocessingArtifacts(
            csv_path=pipeline_artifacts.csv_path,
            excel_path=None,
            rhs_derivatives_csv_path=None,
            export_rows=[],
            summary_path=pipeline_artifacts.summary_path,
            summary_text_path=pipeline_artifacts.summary_text_path,
            summary_markdown_path=pipeline_artifacts.summary_markdown_path,
            free_piston_last_ut_ot_ut_csv_path=pipeline_artifacts.last_ut_ot_ut_csv_path,
            generated_plot_paths=list(pipeline_artifacts.generated_plot_paths),
            plot_layout_paths=list(pipeline_artifacts.plot_layout_paths),
            timings=timings,
        )
