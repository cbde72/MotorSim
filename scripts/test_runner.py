from __future__ import annotations

import html
import json
import re
import subprocess
import sys
import importlib.util
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_CASES_DIR = PROJECT_ROOT / "test_cases"
TEST_CASES_DIR.mkdir(parents=True, exist_ok=True)


_ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub('', text).replace('#x1B', '')


def _collect_artifacts() -> list[Path]:
    items: list[Path] = []
    for path in sorted(TEST_CASES_DIR.rglob('*')):
        if path.is_file() and path.name not in {'pytest_results.xml', 'pytest_stdout.txt', 'pytest_stderr.txt', 'index.html'}:
            items.append(path.relative_to(TEST_CASES_DIR))
    return items




def _read_coverage_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}
def _write_fail_log(xml_path: Path, stdout_path: Path, stderr_path: Path, returncode: int) -> Path:
    fail_path = TEST_CASES_DIR / 'fail.log'
    entries = []
    if xml_path.exists():
        root = ET.parse(xml_path).getroot()
        for case in root.iter('testcase'):
            failure = case.find('failure')
            error = case.find('error')
            if failure is None and error is None:
                continue
            node = failure if failure is not None else error
            detail = ((node.attrib.get('message', '') if node is not None else '') + '\n' + ((node.text or '') if node is not None else '')).strip()
            entries.append(f"{case.attrib.get('classname', '')}::{case.attrib.get('name', '')}\n{detail}\n")
    stdout_text = _strip_ansi(stdout_path.read_text(encoding='utf-8', errors='replace')) if stdout_path.exists() else ''
    stderr_text = _strip_ansi(stderr_path.read_text(encoding='utf-8', errors='replace')) if stderr_path.exists() else ''
    if returncode == 0 and not entries:
        fail_path.write_text('', encoding='utf-8')
        return fail_path
    content = [f"Returncode: {returncode}"]
    if entries:
        content.append('\n\n'.join(entries))
    if stdout_text:
        content.append('=== stdout ===\n' + stdout_text)
    if stderr_text:
        content.append('=== stderr ===\n' + stderr_text)
    fail_path.write_text('\n\n'.join(content), encoding='utf-8')
    return fail_path

def _generate_html_report(xml_path: Path, stdout_path: Path, stderr_path: Path, returncode: int, coverage_json: Path | None = None) -> Path:
    tests = []
    totals = {'tests': 0, 'failures': 0, 'errors': 0, 'skipped': 0}
    if xml_path.exists():
        root = ET.parse(xml_path).getroot()
        totals['tests'] = int(root.attrib.get('tests', 0) or 0)
        totals['failures'] = int(root.attrib.get('failures', 0) or 0)
        totals['errors'] = int(root.attrib.get('errors', 0) or 0)
        totals['skipped'] = int(root.attrib.get('skipped', 0) or 0)
        for case in root.iter('testcase'):
            status = 'passed'
            detail = ''
            failure = case.find('failure')
            error = case.find('error')
            skipped = case.find('skipped')
            if failure is not None:
                status = 'failed'
                detail = (failure.attrib.get('message', '') + '\n' + (failure.text or '')).strip()
            elif error is not None:
                status = 'error'
                detail = (error.attrib.get('message', '') + '\n' + (error.text or '')).strip()
            elif skipped is not None:
                status = 'skipped'
                detail = (skipped.attrib.get('message', '') + '\n' + (skipped.text or '')).strip()
            tests.append({
                'name': f"{case.attrib.get('classname', '')}::{case.attrib.get('name', '')}",
                'time': case.attrib.get('time', ''),
                'status': status,
                'detail': detail,
            })
    artifacts = _collect_artifacts()
    stdout_text = _strip_ansi(stdout_path.read_text(encoding='utf-8', errors='replace')) if stdout_path.exists() else ''
    stderr_text = _strip_ansi(stderr_path.read_text(encoding='utf-8', errors='replace')) if stderr_path.exists() else ''
    coverage = _read_coverage_json(coverage_json or Path())
    coverage_pct = coverage.get('totals', {}).get('percent_covered_display')
    report_path = TEST_CASES_DIR / 'index.html'
    rows = []
    for t in tests:
        rows.append(
            f"<tr><td>{html.escape(t['name'])}</td><td>{html.escape(t['status'])}</td>"
            f"<td>{html.escape(t['time'])}</td><td><pre>{html.escape(t['detail'])}</pre></td></tr>"
        )
    artifact_rows = ''.join(
        f'<li><a href="{html.escape(str(p).replace(chr(92), "/"))}">{html.escape(str(p))}</a></li>'
        for p in artifacts
    )
    report_path.write_text(
        f'''<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Thermo0D Testbericht</title>
<style>
body{{font-family:Inter,Arial,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:24px}}
h1,h2{{margin:0 0 12px}}
main{{display:grid;gap:20px}}
section{{background:#111827;border:1px solid #334155;border-radius:14px;padding:18px}}
table{{width:100%;border-collapse:collapse}}
th,td{{border:1px solid #334155;padding:8px;vertical-align:top}}
th{{background:#1e293b}}
pre{{white-space:pre-wrap;margin:0}}
.ok{{color:#4ade80}}
.bad{{color:#f87171}}
</style></head><body>
<h1>Thermo0D Testbericht</h1><p>Erzeugt: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
<main>
<section><h2>Zusammenfassung</h2><p>Returncode: <strong class="{'ok' if returncode == 0 else 'bad'}">{returncode}</strong></p><ul>
<li>Tests: {totals['tests']}</li><li>Failures: {totals['failures']}</li><li>Errors: {totals['errors']}</li><li>Skipped: {totals['skipped']}</li><li>Coverage: {coverage_pct if coverage_pct is not None else 'n/a'}%</li></ul></section>
<section><h2>Testergebnisse</h2><table><thead><tr><th>Test</th><th>Status</th><th>Zeit [s]</th><th>Details</th></tr></thead><tbody>{''.join(rows)}</tbody></table></section>
<section><h2>Artefakte in test_cases</h2><ul>{artifact_rows or '<li>Keine zusätzlichen Artefakte erzeugt.</li>'}</ul></section>
<section><h2>Pytest stdout</h2><pre>{html.escape(stdout_text)}</pre></section>
<section><h2>Pytest stderr</h2><pre>{html.escape(stderr_text)}</pre></section>
</main></body></html>''',
        encoding='utf-8',
    )
    return report_path


def _has_pytest_cov() -> bool:
    return importlib.util.find_spec('pytest_cov') is not None


if __name__ == "__main__":
    simulated_args = [
        'tests',
        '--continue-on-collection-errors',
        '--maxfail=999999',
        '-ra',
        f'--junitxml={TEST_CASES_DIR / "pytest_results.xml"}',
    ]
    if _has_pytest_cov():
        simulated_args.extend([
            '--cov=src/thermo0d',
            f'--cov-report=html:{TEST_CASES_DIR / "coverage_html"}',
            f'--cov-report=json:{TEST_CASES_DIR / "coverage.json"}',
        ])
    else:
        print('[WARN] pytest-cov ist nicht installiert. Coverage-Berichte werden übersprungen.')

    cmd = [sys.executable, '-m', 'pytest']
    if len(sys.argv) > 1:
        cmd.extend(sys.argv[1:])
    else:
        print(f"[INFO] Keine Terminal-Argumente erkannt. Nutze simulierte Argumente: {simulated_args}")
        cmd.extend(simulated_args)

    stdout_path = TEST_CASES_DIR / 'pytest_stdout.txt'
    stderr_path = TEST_CASES_DIR / 'pytest_stderr.txt'
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, text=True, capture_output=True)
    stdout_path.write_text(_strip_ansi(proc.stdout), encoding='utf-8')
    stderr_path.write_text(_strip_ansi(proc.stderr), encoding='utf-8')
    fail_path = _write_fail_log(TEST_CASES_DIR / 'pytest_results.xml', stdout_path, stderr_path, proc.returncode)
    report_path = _generate_html_report(TEST_CASES_DIR / 'pytest_results.xml', stdout_path, stderr_path, proc.returncode, TEST_CASES_DIR / 'coverage.json')
    print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    print(f'[INFO] HTML-Testbericht: {report_path}')
    if proc.returncode != 0:
        print(f'[WARN] Fehlgeschlagene Tests protokolliert in: {fail_path}')
    raise SystemExit(proc.returncode)
