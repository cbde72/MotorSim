from __future__ import annotations

import matplotlib.pyplot as plt

from thermo0d.output.plot_layout import _apply_x_axis_layout, _apply_y_axis_layout, _draw_vertical_lines


def test_apply_y_axis_layout_supports_log_scale() -> None:
    figure, axis = plt.subplots()
    try:
        _apply_y_axis_layout(
            axis,
            {
                "scale": "log",
                "limit_mode": "manual",
                "y_min": 0.01,
                "y_max": 1000.0,
            },
        )
        assert axis.get_yscale() == "log"
        lower, upper = axis.get_ylim()
        assert lower == 0.01
        assert upper == 1000.0
    finally:
        plt.close(figure)


def test_time_axis_start_at_zero_uses_full_export_range() -> None:
    figure, axis = plt.subplots()
    try:
        _apply_x_axis_layout(
            axis,
            {
                "x_signal": "last_cycle_time_s",
                "x_limit_mode": "auto",
                "x_start_at_zero": True,
            },
            [
                {"last_cycle_time_s": 0.0},
                {"last_cycle_time_s": 0.012},
                {"last_cycle_time_s": 0.025},
            ],
        )
        lower, upper = axis.get_xlim()
        assert lower == 0.0
        assert upper == 0.025
    finally:
        plt.close(figure)


def test_draw_vertical_lines_supports_x_line_and_label_formatting() -> None:
    figure, axis = plt.subplots()
    try:
        _draw_vertical_lines(
            axis,
            {
                "x_lines": [
                    {
                        "x": 5.0,
                        "label": "Inlet opens",
                        "color": "#175CD3",
                        "line_style": "--",
                        "line_width": 1.25,
                        "alpha": 0.7,
                        "label_y": 0.8,
                        "label_rotation": 45.0,
                        "label_font_size": 9.0,
                        "label_bg_color": "#ffffff",
                        "label_border_color": "#111111",
                        "label_bg_alpha": 0.6,
                        "label_ha": "left",
                        "label_va": "top",
                    },
                    {"x": 7.0, "visible": False},
                ]
            },
        )
        assert len(axis.lines) == 1
        assert list(axis.lines[0].get_xdata()) == [5.0, 5.0]
        assert axis.lines[0].get_color() == "#175CD3"
        assert axis.lines[0].get_linewidth() == 1.25
        assert len(axis.texts) == 1
        assert axis.texts[0].get_text() == "Inlet opens"
        assert axis.texts[0].get_position() == (5.0, 0.8)
        assert axis.texts[0].get_rotation() == 45.0
    finally:
        plt.close(figure)
