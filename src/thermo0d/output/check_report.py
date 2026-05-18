from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
import math

from thermo0d.model.free_piston.cycle_metrics import summarize_oscillation
from thermo0d.output.exporters import CsvExporter
from thermo0d.output.geometry_report import build_geometry_entries


@dataclass(slots=True)
class CheckThresholdProfile:
    case_class: str
    cycle_type: str
    fired: bool
    gas_exchange_active: bool
    pmin_ok: tuple[float, float]
    pmin_warn: tuple[float, float]
    pmax_ok: tuple[float, float]
    pmax_warn: tuple[float, float]
    Tmin_ok: tuple[float, float]
    Tmin_warn: tuple[float, float]
    Tmax_ok: tuple[float, float]
    Tmax_warn: tuple[float, float]
    mass_residual_green_rel: float
    mass_residual_yellow_rel: float
    energy_residual_green_rel: float
    energy_residual_yellow_rel: float


@dataclass(slots=True)
class CheckMetric:
    name: str
    value: float | int | str
    unit: str
    status: str
    details: str = ""


@dataclass(slots=True)
class CheckReportArtifacts:
    csv_path: str | None
    html_path: str | None
    metrics: list[CheckMetric]


class LastCycleCheckReportBuilder:
    @staticmethod
    def _infer_profile(rows: list[dict[str, float | int]], prefix: str | None, cycle_deg: float | None = None) -> CheckThresholdProfile:
        last_row = rows[-1] if rows else {}
        q_add = abs(float(last_row.get(f'{prefix}_added_energy_cycle_J', 0.0))) if prefix else 0.0
        m_in = abs(float(last_row.get(f'{prefix}_mdot_in_cycle_kg', 0.0))) if prefix else 0.0
        m_out = abs(float(last_row.get(f'{prefix}_mdot_out_cycle_kg', 0.0))) if prefix else 0.0
        gas_exchange_active = (m_in + m_out) > 1.0e-12
        fired = q_add > 1.0e-6
        cycle_type = '2T' if (cycle_deg is not None and float(cycle_deg) <= 360.5) else '4T'

        if fired and gas_exchange_active:
            if cycle_type == '2T':
                return CheckThresholdProfile(
                    case_class='fired_scavenged_2T', cycle_type=cycle_type, fired=True, gas_exchange_active=True,
                    pmin_ok=(0.2, 8.0), pmin_warn=(0.05, 15.0),
                    pmax_ok=(5.0, 220.0), pmax_warn=(1.0, 320.0),
                    Tmin_ok=(220.0, 1200.0), Tmin_warn=(120.0, 1800.0),
                    Tmax_ok=(600.0, 3800.0), Tmax_warn=(300.0, 4800.0),
                    mass_residual_green_rel=2.0e-5, mass_residual_yellow_rel=2.0e-3,
                    energy_residual_green_rel=5.0e-5, energy_residual_yellow_rel=2.0e-3,
                )
            return CheckThresholdProfile(
                case_class='fired_gas_exchange_4T', cycle_type=cycle_type, fired=True, gas_exchange_active=True,
                pmin_ok=(0.2, 5.0), pmin_warn=(0.05, 10.0),
                pmax_ok=(10.0, 260.0), pmax_warn=(1.0, 360.0),
                Tmin_ok=(220.0, 1200.0), Tmin_warn=(120.0, 1800.0),
                Tmax_ok=(800.0, 4200.0), Tmax_warn=(350.0, 5200.0),
                mass_residual_green_rel=1.0e-5, mass_residual_yellow_rel=1.0e-3,
                energy_residual_green_rel=2.0e-5, energy_residual_yellow_rel=1.0e-3,
            )
        if gas_exchange_active:
            return CheckThresholdProfile(
                case_class='coldflow_gas_exchange', cycle_type=cycle_type, fired=False, gas_exchange_active=True,
                pmin_ok=(0.2, 5.0), pmin_warn=(0.05, 10.0),
                pmax_ok=(0.5, 80.0), pmax_warn=(0.1, 150.0),
                Tmin_ok=(180.0, 900.0), Tmin_warn=(100.0, 1600.0),
                Tmax_ok=(220.0, 1400.0), Tmax_warn=(120.0, 2200.0),
                mass_residual_green_rel=1.0e-6, mass_residual_yellow_rel=1.0e-4,
                energy_residual_green_rel=2.0e-6, energy_residual_yellow_rel=2.0e-4,
            )
        return CheckThresholdProfile(
            case_class='closed_or_settling', cycle_type=cycle_type, fired=fired, gas_exchange_active=False,
            pmin_ok=(0.2, 20.0), pmin_warn=(0.05, 50.0),
            pmax_ok=(0.5, 120.0), pmax_warn=(0.1, 200.0),
            Tmin_ok=(180.0, 1200.0), Tmin_warn=(80.0, 2000.0),
            Tmax_ok=(220.0, 1800.0 if not fired else 3200.0), Tmax_warn=(120.0, 2600.0 if not fired else 4200.0),
            mass_residual_green_rel=1.0e-8, mass_residual_yellow_rel=1.0e-5,
            energy_residual_green_rel=1.0e-7, energy_residual_yellow_rel=1.0e-4,
        )

    @staticmethod
    def _status_abs(value: float, green: float, yellow: float) -> str:
        mag = abs(float(value))
        if mag <= green:
            return 'green'
        if mag <= yellow:
            return 'yellow'
        return 'red'

    @staticmethod
    def _status_range(value: float, min_ok: float, max_ok: float, min_warn: float | None = None, max_warn: float | None = None) -> str:
        v = float(value)
        if min_ok <= v <= max_ok:
            return 'green'
        if min_warn is not None and max_warn is not None and min_warn <= v <= max_warn:
            return 'yellow'
        return 'red'

    @staticmethod
    def _last_cycle_rows(rows: list[dict[str, float | int]]) -> list[dict[str, float | int]]:
        if not rows:
            return []
        last_cycle = int(rows[-1].get('cycle_index', 0))
        return [row for row in rows if int(row.get('cycle_index', 0)) == last_cycle]

    @staticmethod
    def _find_primary_prefix(last_row: dict[str, float | int]) -> str | None:
        prefixes = []
        for key in last_row:
            if key.endswith('_p_Pa'):
                prefixes.append(key[:-len('_p_Pa')])
        if not prefixes:
            return None
        for prefix in prefixes:
            if prefix.startswith('cyl') or 'cylinder' in prefix:
                return prefix
        return prefixes[0]

    @classmethod
    def _free_piston_metrics(cls, rows: list[dict[str, float | int]]) -> list[CheckMetric]:
        if not rows:
            return []
        try:
            t_s = [float(row.get('t_s', 0.0)) for row in rows]
            x_m = [float(row.get('free_piston_x_m')) for row in rows if 'free_piston_x_m' in row]
            v_m_per_s = [float(row.get('free_piston_v_m_per_s')) for row in rows if 'free_piston_v_m_per_s' in row]
        except Exception:
            return []
        if not x_m or not v_m_per_s or len(t_s) != len(x_m) or len(t_s) != len(v_m_per_s):
            return []
        summary = summarize_oscillation(t_s, x_m, v_m_per_s)
        if summary is None:
            return []
        metrics = [
            CheckMetric('free_piston_x_min_m', summary.x_min_m, 'm', 'green', 'Kleinste Kolbenposition im ausgewerteten Zeitfenster.'),
            CheckMetric('free_piston_x_max_m', summary.x_max_m, 'm', 'green', 'Größte Kolbenposition im ausgewerteten Zeitfenster.'),
            CheckMetric('free_piston_x_mean_m', summary.x_mean_m, 'm', 'green', 'Mittlere Kolbenposition im ausgewerteten Zeitfenster.'),
            CheckMetric('free_piston_stroke_window_m', summary.stroke_window_m, 'm', 'green' if summary.stroke_window_m > 0.0 else 'red', 'Tatsächlich durchlaufener Hubbereich im ausgewerteten Zeitfenster.'),
            CheckMetric('free_piston_turning_points_count', summary.turning_points_count, 'count', 'green' if summary.turning_points_count >= 2 else 'yellow', 'Anzahl erkannter Umkehrpunkte aus dem Bewegungsverlauf.'),
            CheckMetric('free_piston_oscillation_count', summary.oscillation_count, 'count', 'green' if summary.oscillation_count >= 1 else 'yellow', 'Anzahl geschlossener Schwingungsperioden aus den Umkehrpunkten.'),
        ]
        if summary.mean_period_s is not None:
            metrics.append(CheckMetric('free_piston_mean_period_s', summary.mean_period_s, 's', 'green', 'Mittlere Schwingungsperiode aus Umkehrpunkten.'))
        if summary.mean_frequency_Hz is not None:
            metrics.append(CheckMetric('free_piston_mean_frequency_Hz', summary.mean_frequency_Hz, 'Hz', 'green', 'Mittlere Schwingungsfrequenz aus Umkehrpunkten.'))
        if summary.last_period_s is not None:
            metrics.append(CheckMetric('free_piston_last_period_s', summary.last_period_s, 's', 'green', 'Letzte vollständig erkannte Schwingungsperiode.'))
        if summary.last_frequency_Hz is not None:
            metrics.append(CheckMetric('free_piston_last_frequency_Hz', summary.last_frequency_Hz, 'Hz', 'green', 'Frequenz der letzten vollständig erkannten Schwingungsperiode.'))
        if summary.last_halfstroke_m is not None:
            metrics.append(CheckMetric('free_piston_last_halfstroke_m', summary.last_halfstroke_m, 'm', 'green', 'Abstand zwischen den beiden letzten Umkehrpunkten.'))
        return metrics

    @classmethod
    def build_metrics(cls, rows: list[dict[str, float | int]], *, cycle_deg: float | None = None, bundle=None) -> list[CheckMetric]:
        cycle_rows = cls._last_cycle_rows(rows)
        if not cycle_rows:
            return []
        first_row = cycle_rows[0]
        last_row = cycle_rows[-1]
        metrics: list[CheckMetric] = []
        prefix = cls._find_primary_prefix(last_row)
        profile = cls._infer_profile(cycle_rows, prefix, cycle_deg=cycle_deg)

        metrics.append(CheckMetric('check_case_class', profile.case_class, '-', 'green', 'Automatisch erkannte Fallklasse für die Ampelbewertung.'))
        metrics.append(CheckMetric('check_cycle_type', profile.cycle_type, '-', 'green', 'Aus dem Modell abgeleiteter Zyklustyp für die Bewertung.'))
        metrics.append(CheckMetric('last_cycle_points', len(cycle_rows), 'count', 'green', 'Anzahl Stützstellen im letzten Zyklus.'))
        if bundle is not None:
            for entry in build_geometry_entries(bundle):
                metrics.append(CheckMetric(entry.key, entry.value, entry.unit, 'green', entry.details))
        if len(cycle_rows) >= 2:
            theta_first = float(first_row.get('theta_local_deg', 0.0))
            theta_last = float(last_row.get('theta_local_deg', 0.0))
            metrics.append(CheckMetric('theta_first_deg', theta_first, 'deg', 'green', 'Erster lokaler Kurbelwinkel des Prüfzyklus.'))
            metrics.append(CheckMetric('theta_last_deg', theta_last, 'deg', 'green', 'Letzter lokaler Kurbelwinkel des Prüfzyklus.'))

        if bundle is not None and getattr(bundle, 'architecture', 'classic') == 'free_piston':
            metrics.extend(cls._free_piston_metrics(rows))

        if prefix is None:
            return metrics

        pmax_bar = max(float(row.get(f'{prefix}_p_Pa', 0.0)) for row in cycle_rows) / 1.0e5
        pmin_bar = min(float(row.get(f'{prefix}_p_Pa', 0.0)) for row in cycle_rows) / 1.0e5
        Tmax_K = max(float(row.get(f'{prefix}_T_K', 0.0)) for row in cycle_rows)
        Tmin_K = min(float(row.get(f'{prefix}_T_K', 0.0)) for row in cycle_rows)
        mmax_kg = max(float(row.get(f'{prefix}_m_kg', 0.0)) for row in cycle_rows)
        mmin_kg = min(float(row.get(f'{prefix}_m_kg', 0.0)) for row in cycle_rows)

        if bundle is not None and getattr(bundle, 'architecture', 'classic') == 'free_piston':
            metric_block = [
                CheckMetric('pmin_bar', pmin_bar, 'bar', cls._status_range(pmin_bar, profile.pmin_ok[0], profile.pmin_ok[1], profile.pmin_warn[0], profile.pmin_warn[1]), 'Minimaler Zylinderdruck im ausgewerteten Zeitfenster.'),
                CheckMetric('pmax_bar', pmax_bar, 'bar', cls._status_range(pmax_bar, profile.pmax_ok[0], profile.pmax_ok[1], profile.pmax_warn[0], profile.pmax_warn[1]), 'Maximaler Zylinderdruck im ausgewerteten Zeitfenster.'),
                CheckMetric('Tmin_K', Tmin_K, 'K', cls._status_range(Tmin_K, profile.Tmin_ok[0], profile.Tmin_ok[1], profile.Tmin_warn[0], profile.Tmin_warn[1]), 'Minimale Zylindertemperatur im ausgewerteten Zeitfenster.'),
                CheckMetric('Tmax_K', Tmax_K, 'K', cls._status_range(Tmax_K, profile.Tmax_ok[0], profile.Tmax_ok[1], profile.Tmax_warn[0], profile.Tmax_warn[1]), 'Maximale Zylindertemperatur im ausgewerteten Zeitfenster.'),
                CheckMetric('mmin_kg', mmin_kg, 'kg', 'green' if mmin_kg > 0.0 else 'red', 'Minimale Zylindermasse im ausgewerteten Zeitfenster.'),
                CheckMetric('mmax_kg', mmax_kg, 'kg', 'green' if mmax_kg > 0.0 else 'red', 'Maximale Zylindermasse im ausgewerteten Zeitfenster.'),
            ]
            status_order = {'green': 0, 'yellow': 1, 'red': 2}
            overall_status = 'green'
            for metric in metric_block:
                if status_order.get(metric.status, 0) > status_order.get(overall_status, 0):
                    overall_status = metric.status
            metrics.append(CheckMetric('overall_status', overall_status, '-', overall_status, 'Gesamtampel für den aktuellen Phase-C-Freikolben-Diagnosestand.'))
            metrics.extend(metric_block)
            return metrics

        delta_m = float(last_row.get(f'{prefix}_m_kg', 0.0)) - float(first_row.get(f'{prefix}_m_kg', 0.0))
        mdot_in_cycle = float(last_row.get(f'{prefix}_mdot_in_cycle_kg', 0.0))
        mdot_out_cycle = float(last_row.get(f'{prefix}_mdot_out_cycle_kg', 0.0))
        mass_residual = float(last_row.get(f'{prefix}_mass_balance_residual_kg', delta_m - (mdot_in_cycle - mdot_out_cycle)))
        dU_cycle = float(last_row.get(f'{prefix}_delta_U_cycle_J', 0.0))
        h_in = float(last_row.get(f'{prefix}_enthalpy_in_cycle_J', 0.0))
        h_out = float(last_row.get(f'{prefix}_enthalpy_out_cycle_J', 0.0))
        q_wall = float(last_row.get(f'{prefix}_wall_heat_cycle_J', 0.0))
        q_add = float(last_row.get(f'{prefix}_added_energy_cycle_J', 0.0))
        q_evap = float(last_row.get(f'{prefix}_evaporation_sink_cycle_J', 0.0))
        w_pv = float(last_row.get(f'{prefix}_piston_work_cycle_J', 0.0))
        energy_residual = float(last_row.get(f'{prefix}_energy_balance_residual_J', 0.0))
        mass_scale = max(1.0e-12, abs(mmax_kg), abs(delta_m), abs(mdot_in_cycle), abs(mdot_out_cycle))
        mass_residual_rel = mass_residual / mass_scale
        denom = max(1.0e-12, abs(dU_cycle), abs(q_add) + abs(h_in) + abs(h_out) + abs(q_wall) + abs(q_evap) + abs(w_pv))
        energy_residual_rel = energy_residual / denom
        metric_block = [
            CheckMetric('pmin_bar', pmin_bar, 'bar', cls._status_range(pmin_bar, profile.pmin_ok[0], profile.pmin_ok[1], profile.pmin_warn[0], profile.pmin_warn[1]), f'Minimaler Zylinderdruck im letzten Zyklus ({profile.case_class}).'),
            CheckMetric('pmax_bar', pmax_bar, 'bar', cls._status_range(pmax_bar, profile.pmax_ok[0], profile.pmax_ok[1], profile.pmax_warn[0], profile.pmax_warn[1]), f'Maximaler Zylinderdruck im letzten Zyklus ({profile.case_class}).'),
            CheckMetric('Tmin_K', Tmin_K, 'K', cls._status_range(Tmin_K, profile.Tmin_ok[0], profile.Tmin_ok[1], profile.Tmin_warn[0], profile.Tmin_warn[1]), f'Minimale Zylindertemperatur im letzten Zyklus ({profile.case_class}).'),
            CheckMetric('Tmax_K', Tmax_K, 'K', cls._status_range(Tmax_K, profile.Tmax_ok[0], profile.Tmax_ok[1], profile.Tmax_warn[0], profile.Tmax_warn[1]), f'Maximale Zylindertemperatur im letzten Zyklus ({profile.case_class}).'),
            CheckMetric('mmin_kg', mmin_kg, 'kg', 'green' if mmin_kg > 0.0 else 'red', 'Minimale Zylindermasse im letzten Zyklus.'),
            CheckMetric('mmax_kg', mmax_kg, 'kg', 'green' if mmax_kg > 0.0 else 'red', 'Maximale Zylindermasse im letzten Zyklus.'),
            CheckMetric('delta_m_cycle_kg', delta_m, 'kg', 'green', 'Massenänderung des Zylinders über den letzten Zyklus.'),
            CheckMetric('mdot_in_cycle_kg', mdot_in_cycle, 'kg', 'green', 'Integrierte Einströmmasse über den letzten Zyklus.'),
            CheckMetric('mdot_out_cycle_kg', mdot_out_cycle, 'kg', 'green', 'Integrierte Ausströmmasse über den letzten Zyklus.'),
            CheckMetric('mass_balance_residual_kg', mass_residual, 'kg', cls._status_abs(mass_residual_rel, profile.mass_residual_green_rel, profile.mass_residual_yellow_rel), 'Sollte nahe 0 liegen: Δm - (m_in - m_out), bewertet relativ zur durchgesetzten bzw. gespeicherten Masse.'),
            CheckMetric('mass_balance_residual_rel', mass_residual_rel, '-', cls._status_abs(mass_residual_rel, profile.mass_residual_green_rel, profile.mass_residual_yellow_rel), 'Normierte Massenbilanzrestgröße für die Fallklassen-Ampel.'),
            CheckMetric('delta_U_cycle_J', dU_cycle, 'J', 'green', 'Änderung der inneren Energie im letzten Zyklus.'),
            CheckMetric('enthalpy_in_cycle_J', h_in, 'J', 'green', 'Integrierte Enthalpie in den Zylinder.'),
            CheckMetric('enthalpy_out_cycle_J', h_out, 'J', 'green', 'Integrierte Enthalpie aus dem Zylinder.'),
            CheckMetric('wall_heat_cycle_J', q_wall, 'J', 'green', 'Integrierte Wandwärme.'),
            CheckMetric('added_energy_cycle_J', q_add, 'J', 'green', 'Integrierte zugeführte Energie/Verbrennung.'),
            CheckMetric('evaporation_sink_cycle_J', q_evap, 'J', 'green', 'Integrierte Verdampfungsenthalpie-Senke.'),
            CheckMetric('piston_work_cycle_J', w_pv, 'J', 'green', 'Integrierte p*dV-Arbeit.'),
            CheckMetric('energy_balance_residual_J', energy_residual, 'J', cls._status_abs(energy_residual_rel, profile.energy_residual_green_rel, profile.energy_residual_yellow_rel), 'Sollte nahe 0 liegen: ΔU - (H_net + Q_wall + Q_add - Q_evap - W_pv).'),
            CheckMetric('energy_balance_residual_rel', energy_residual_rel, '-', cls._status_abs(energy_residual_rel, profile.energy_residual_green_rel, profile.energy_residual_yellow_rel), 'Normierte Energiebilanzrestgröße für die Fallklassen-Ampel.'),
        ]
        status_order = {'green': 0, 'yellow': 1, 'red': 2}
        overall_status = 'green'
        for metric in metric_block:
            if status_order.get(metric.status, 0) > status_order.get(overall_status, 0):
                overall_status = metric.status
        metrics.append(CheckMetric('overall_status', overall_status, '-', overall_status, f'Gesamtampel für {profile.case_class}.'))
        metrics.extend(metric_block)
        return metrics

    @staticmethod
    def write_csv(path: str | Path, separator: str, metrics: list[CheckMetric]) -> str:
        rows = [
            {
                'metric': metric.name,
                'value': metric.value,
                'unit': metric.unit,
                'status': metric.status,
                'details': metric.details,
            }
            for metric in metrics
        ]
        CsvExporter.write(path, separator, rows)
        return str(Path(path).resolve())

    @staticmethod
    def write_html(path: str | Path, metrics: list[CheckMetric], title: str = 'Last Cycle Check Report') -> str:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        def _display_value_and_unit(metric: CheckMetric) -> tuple[str, str]:
            value = metric.value
            unit = str(metric.unit)
            name = str(metric.name)
            if isinstance(value, bool):
                return str(value), unit
            if isinstance(value, int) and not isinstance(value, bool):
                value = float(value)
            if isinstance(value, float) and math.isfinite(value):
                display_value = value
                display_unit = unit

                if unit == 'kg' or name.endswith('_kg'):
                    display_value = value * 1.0e6
                    display_unit = 'mg'
                elif unit == 'K' or name.endswith('_K'):
                    display_value = value - 273.15
                    display_unit = '°C'
                elif unit == 'm³' or unit == 'm^3' or name.endswith('_m3'):
                    display_value = value * 1.0e6
                    display_unit = 'cm³'
                elif unit == 'm' or name.endswith('_m'):
                    display_value = value * 1.0e3
                    display_unit = 'mm'
                elif unit == 'm²' or unit == 'm^2' or name.endswith('_m2'):
                    display_value = value * 1.0e6
                    display_unit = 'mm²'
                elif unit == 'Pa' or name.endswith('_Pa'):
                    display_value = value / 1.0e5
                    display_unit = 'bar'
                elif unit == 'bar' or name.endswith('_bar'):
                    display_value = value
                    display_unit = 'bar'
                elif unit == 'cm³' or name.endswith('_cm3'):
                    display_value = value
                    display_unit = 'cm³'
                elif unit == 'mm²' or name.endswith('_mm2'):
                    display_value = value
                    display_unit = 'mm²'
                elif unit == 'mm' or name.endswith('_mm'):
                    display_value = value
                    display_unit = 'mm'
                elif unit == 'J' or name.endswith('_J'):
                    display_value = value
                    display_unit = 'J'
                elif unit == '-' or unit == 'count' or unit == 'deg' or unit == 'Hz' or unit == 's':
                    display_value = value
                    display_unit = unit

                return f'{display_value:.1f}', display_unit
            return str(value), unit

        summary_names = {'overall_status', 'check_case_class', 'check_cycle_type', 'last_cycle_points', 'theta_first_deg', 'theta_last_deg'}
        geometry_metrics = [metric for metric in metrics if ('geometrie' in metric.details.lower()) or any(metric.name.endswith(suffix) for suffix in ('bore_mm', 'stroke_mm', 'conrod_mm', 'bore_area_mm2', 'swept_cm3', 'clearance_cm3', 'lift_max_mm', 'A_ref_mm2', 'A_eff_forward_max_mm2', 'A_eff_reverse_max_mm2', 'slot_height_max_mm', 'A_geom_max_mm2', 'piston_area_mm2', 'x_min_mm', 'x_max_mm', 'stroke_window_mm', 'initial_cylinder_volume_cm3', 'bounce_volume0_cm3'))]
        summary_metrics = [metric for metric in metrics if metric.name in summary_names]
        check_metrics = [metric for metric in metrics if metric not in geometry_metrics and metric not in summary_metrics]

        def _build_rows(items: list[CheckMetric]) -> str:
            rows_html: list[str] = []
            for metric in items:
                display_value, display_unit = _display_value_and_unit(metric)
                rows_html.append(
                    '<tr>'
                    f'<td>{escape(metric.name)}</td>'
                    f'<td>{escape(display_value)}</td>'
                    f'<td>{escape(display_unit)}</td>'
                    f'<td class="status {escape(metric.status)}">{escape(metric.status)}</td>'
                    f'<td>{escape(metric.details)}</td>'
                    '</tr>'
                )
            return ''.join(rows_html)

        metric_by_name = {metric.name: metric for metric in metrics}
        overall = metric_by_name.get('overall_status')
        case_class = metric_by_name.get('check_case_class')
        cycle_type = metric_by_name.get('check_cycle_type')
        points = metric_by_name.get('last_cycle_points')
        cards_html = ''.join([
            f'<div class="card status-card {escape(str(overall.status if overall else "green"))}"><div class="label">Overall</div><div class="value">{escape(str(overall.value) if overall else "-")}</div></div>',
            f'<div class="card"><div class="label">Fallklasse</div><div class="value">{escape(str(case_class.value) if case_class else "-")}</div></div>',
            f'<div class="card"><div class="label">Zyklus</div><div class="value">{escape(str(cycle_type.value) if cycle_type else "-")}</div></div>',
            f'<div class="card"><div class="label">Punkte</div><div class="value">{escape(str(points.value) if points else "-")}</div></div>',
        ])

        html = (
            '<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">'
            f'<title>{escape(title)}</title>'
            '<style>'
            'body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#1f2937;background:#f8fafc;}'
            'h1,h2{margin:0 0 12px 0;}'
            '.cards{display:grid;grid-template-columns:repeat(4,minmax(180px,1fr));gap:12px;margin:18px 0 24px 0;}'
            '.card{background:#fff;border:1px solid #d0d5dd;border-radius:12px;padding:14px 16px;box-shadow:0 1px 2px rgba(16,24,40,.04);}'
            '.card .label{font-size:12px;color:#475467;text-transform:uppercase;letter-spacing:.04em;margin-bottom:4px;}'
            '.card .value{font-size:24px;font-weight:700;color:#101828;}'
            '.status-card.green{border-color:#12b76a;background:#ecfdf3;}'
            '.status-card.yellow{border-color:#f79009;background:#fffaeb;}'
            '.status-card.red{border-color:#f04438;background:#fef3f2;}'
            'table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #d0d5dd;border-radius:12px;overflow:hidden;margin-bottom:20px;}'
            'th,td{padding:10px 12px;border-bottom:1px solid #eaecf0;text-align:left;vertical-align:top;font-size:14px;}'
            'th{background:#f9fafb;color:#344054;font-weight:600;}'
            '.status{font-weight:700;text-transform:uppercase;}'
            '.status.green{color:#027a48;}.status.yellow{color:#b54708;}.status.red{color:#b42318;}'
            '</style></head><body>'
            f'<h1>{escape(title)}</h1>'
            f'<div class="cards">{cards_html}</div>'
            '<h2>Zusammenfassung</h2>'
            '<table><thead><tr><th>Metric</th><th>Wert</th><th>Einheit</th><th>Status</th><th>Beschreibung</th></tr></thead>'
            f'<tbody>{_build_rows(summary_metrics)}</tbody></table>'
            '<h2>Geometrie</h2>'
            '<table><thead><tr><th>Metric</th><th>Wert</th><th>Einheit</th><th>Status</th><th>Beschreibung</th></tr></thead>'
            f'<tbody>{_build_rows(geometry_metrics)}</tbody></table>'
            '<h2>Checks</h2>'
            '<table><thead><tr><th>Metric</th><th>Wert</th><th>Einheit</th><th>Status</th><th>Beschreibung</th></tr></thead>'
            f'<tbody>{_build_rows(check_metrics)}</tbody></table>'
            '</body></html>'
        )
        path.write_text(html, encoding='utf-8')
        return str(path.resolve())
