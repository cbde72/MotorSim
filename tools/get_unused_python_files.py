import os
import ast
from collections import defaultdict

def get_module_name(file_path, base_dir):
    """Erzeugt den Modulnamen basierend auf dem Pfad relativ zum Basisverzeichnis."""
    rel_path = os.path.relpath(file_path, base_dir)
    if rel_path.endswith('.py'):
        # Entferne .py und wandle Pfad-Trenner in Punkte um
        parts = rel_path[:-3].split(os.sep)
        # __init__ Dateien repräsentieren das Paket selbst
        if parts[-1] == '__init__':
            parts.pop()
        return ".".join(parts)
    return None

def extract_imports_from_file(file_path):
    """Scannt eine Datei nach importierten Modulen."""
    found_imports = set()
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            node = ast.parse(f.read())
            for n in ast.walk(node):
                if isinstance(n, ast.Import):
                    for alias in n.names:
                        found_imports.add(alias.name)
                elif isinstance(n, ast.ImportFrom) and n.module:
                    found_imports.add(n.module)
    except (SyntaxError, UnicodeDecodeError):
        pass
    return found_imports

def run_analysis():
    # Wir starten eine Ebene höher
    base_dir = os.path.abspath(os.path.join(os.getcwd(), ".."))
    src_dir = os.path.join(base_dir, "src")

    if not os.path.exists(src_dir):
        print(f"Fehler: 'src' Ordner wurde nicht gefunden in: {base_dir}")
        return

    print(f"--- Analyse gestartet ---")
    print(f"Basisverzeichnis: {base_dir}")
    print(f"Zielverzeichnis:  {src_dir}\n")

    # 1. Alle Dateien in src erfassen und Modulnamen zuordnen
    module_to_file = {}
    file_to_module = {}

    for root, dirs, files in os.walk(src_dir):
        # Ignoriere Standard-Cache-Ordner
        if "__pycache__" in dirs:
            dirs.remove("__pycache__")

        for file in files:
            if file.endswith('.py'):
                full_path = os.path.join(root, file)
                mod_name = get_module_name(full_path, base_dir)
                if mod_name:
                    module_to_file[mod_name] = full_path
                    file_to_module[full_path] = mod_name

    # 2. Alle Dateien im Projekt scannen, um zu sehen, wer 'src.xxx' importiert
    # Wir scannen hier das GESAMTE Elternverzeichnis (falls Tests außerhalb von src liegen)
    import_map = defaultdict(list)

    for root, dirs, files in os.walk(base_dir):
        if "__pycache__" in dirs: dirs.remove("__pycache__")

        for file in files:
            if file.endswith('.py'):
                current_file = os.path.join(root, file)
                imports = extract_imports_from_file(current_file)

                for imp in imports:
                    # Prüfen, ob der Import auf eines unserer Module in src matched
                    for mod_name in module_to_file:
                        if imp == mod_name or imp.startswith(mod_name + "."):
                            import_map[mod_name].append(current_file)

    # 3. Ausgabe der Ergebnisse
    print(f"{'DATEI (in src)':<45} | {'WIRD IMPORTIERT VON'}")
    print("-" * 110)

    for full_path in sorted(file_to_module.keys()):
        mod_name = file_to_module[full_path]
        rel_to_src = os.path.relpath(full_path, src_dir)

        # Ignoriere reine __init__.py in der Anzeige, falls gewünscht
        if rel_to_src == "__init__.py": continue

        importers = list(set(import_map.get(mod_name, [])))
        # Entferne die Datei selbst aus der Liste der Importer (Selbst-Imports ignorieren)
        if full_path in importers:
            importers.remove(full_path)

        if not importers:
            display_importers = "!!! VERWAIST (KEIN IMPORT GEFUNDEN) !!!"
        else:
            # Zeige nur die Dateinamen der Importer an, um Platz zu sparen
            display_importers = ", ".join([os.path.relpath(i, base_dir) for i in importers])

        print(f"{rel_to_src:<45} | {display_importers}")

if __name__ == "__main__":
    run_analysis()