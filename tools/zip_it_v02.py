# -*- coding: utf-8 -*-
"""
Created on Sat Mar 14 11:47:31 2026
    IGNORE_DIRS = {'.git', '__pycache__', '.venv', 'venv', '.vscode', '.idea', 'out', '.pytest_cache', 'htmlcov'}
@author: CBUEHRING
"""
'''
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    TEST_CASES_DIR = PROJECT_ROOT / "test_cases"
    CONFIGS_DIR = TEST_CASES_DIR / "configs"

    simulated_args = [
        "--batch-variants",
        "--continue-on-error",
        "--variants-dir", str(CONFIGS_DIR),
        "--project", str(PROJECT_ROOT / "Projekte"),
        "--no-excel",
    ]
'''
import os
import zipfile
from pathlib import Path

'''
Gib ausschließlich den vollständigen Python-Code der finalen Datei aus.
Keine Erklärung vorab.
Keine Nachbemerkung.   stell durch mehrere überprüfungen fest, das der fertige code aller punkte berücksichtigt. die
'''

import re
from pathlib import Path


# -*- coding: utf-8 -*-
"""
Created on Sat Mar 14 11:47:31 2026
@author: CBUEHRING
"""

import os
import zipfile
import re
import time
from pathlib import Path

def bump_version(version_file: Path):
    """
    Liest die Version aus der Datei, erhöht den Patch-Level und schreibt sie zurück.
    Erwartet Format: VERSION = (x, y, z)
    """
    if not version_file.exists():
        raise FileNotFoundError(f"Versionsdatei nicht gefunden: {version_file}")

    text = version_file.read_text(encoding="utf-8")
    match = re.search(r"VERSION\s*=\s*\((\d+),\s*(\d+),\s*(\d+)\)", text)

    if not match:
        raise RuntimeError("VERSION-Tupel im Format (x, y, z) nicht gefunden.")

    major, minor, patch = map(int, match.groups())
    patch += 1

    new_tuple = f"VERSION = ({major}, {minor}, {patch})"
    old_tuple = match.group(0)

    text = text.replace(old_tuple, new_tuple)
    version_file.write_text(text, encoding="utf-8")

    return f"{major}-{minor}-{patch}"


def get_zip_path(root_dir, current_version):
    """
    Erstellt den Zielpfad: ../versionen/Ordnername_Zeitstempel_VVersion.zip
    """
    versions_dir = root_dir.parent / "versionen"
    versions_dir.mkdir(exist_ok=True)

    timestamp = time.strftime("%y%m%d_%H%M")
    folder_name = root_dir.name

    filename = f"{folder_name}_{timestamp}_V{current_version}.zip"
    return versions_dir / filename


def backup_with_filters():
    # --- KONFIGURATION ---
    EBENEN_HOCH = 1  # Wie viele Ebenen über dem Skript liegt das Projekt-Root?

    # Erlaubte Dateiendungen
    EXTENSIONS = ('.py', '.md', '.json', '.yaml', '.txt', '.html', '.css')

    # Ordner, die komplett ignoriert werden
    IGNORE_DIRS = {'tests','test_cases','Results','results','.git', '__pycache__', '.venv', 'venv', '.vscode', '.idea', 'out', '.pytest_cache', 'htmlcov'}

    # Spezifische Dateinamen, die ignoriert werden
    IGNORE_FILES = {'.DS_Store', 'report.html', '.env', 'geheim.txt'}
    # ---------------------

    # 1. Pfade bestimmen
    script_path = Path(__file__).resolve()
    root_dir = script_path.parents[EBENEN_HOCH]

    # Pfad zur version.py (basierend auf deiner Struktur)
    version_file = root_dir / "src" / "thermo0d" / "version.py"

    try:
        # 2. Version aktualisieren
        current_version = bump_version(version_file)

        # 3. Ziel-Zip-Pfad generieren
        zip_path = get_zip_path(root_dir, current_version)

        files_to_add = []

        print(f"--- Backup-Vorgang gestartet ---")
        print(f"Projekt-Root: {root_dir}")
        print(f"Version:      {current_version.replace('-', '.')}")
        print(f"Ziel-Archiv:  {zip_path.name}")

        # 4. Dateien sammeln
        for root, dirs, files in os.walk(root_dir):
            # Verzeichnisse filtern
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

            for file in files:
                # Prüfen, ob Dateiname ignoriert werden soll
                if file in IGNORE_FILES:
                    continue

                # Prüfen, ob Endung erlaubt ist
                if file.lower().endswith(EXTENSIONS):
                    full_path = Path(root) / file

                    # Sicherheitscheck: Nicht das Archiv selbst einpacken
                    if full_path != zip_path:
                        files_to_add.append(full_path)

        if not files_to_add:
            print("\nKeine passenden Dateien zum Sichern gefunden.")
            return

        # 5. Archiv erstellen
        print(f"\nPacke {len(files_to_add)} Dateien...")

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file in files_to_add:
                arcname = file.relative_to(root_dir)
                zipf.write(file, arcname=arcname)

        print(f"\nERFOLG!")
        print(f"Archiv erstellt in: {zip_path}")

    except Exception as e:
        print(f"\nFEHLER: {e}")


if __name__ == "__main__":
    backup_with_filters()