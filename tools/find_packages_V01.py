import os
import ast
import yaml
import importlib.metadata
import subprocess

# STRENGER STARTPFAD
TARGET_PATH = r"C:\Users\cbuehring\Desktop\Daten\python\projekte\0_Motorsim"

IMPORT_MAPPING = {
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "skimage": "scikit-image",
    "PIL": "Pillow",
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
    "matplotlib": "matplotlib",
    "pd": "pandas",
    "np": "numpy"
}

STDLIB = {
    'os', 'sys', 'time', 'math', 're', 'json', 'ast', 'argparse', 'datetime', 
    'collections', 'pathlib', 'shutil', 'threading', 'multiprocessing', 
    'logging', 'inspect', 'pickle', 'io', 'base64', 'hashlib', 'subprocess',
    'glob', 'copy', 'functools', 'itertools', 'typing', 'abc', 'enum', 'struct'
}

def get_version(package_name):
    """Ermittelt die Version des installierten Pakets."""
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return None

def get_imports_from_file(file_path):
    """Extrahiert Importe aus einer .py Datei via AST."""
    imports = set()
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split('.')[0])
    except Exception as e:
        print(f"  [!] Fehler in: {os.path.basename(file_path)} -> {e}")
    return imports

def generate_env_yaml(root_dir):
    if not os.path.exists(root_dir):
        print(f"FEHLER: Der Pfad '{root_dir}' wurde nicht gefunden.")
        return

    all_imports = set()
    output_file = os.path.join(root_dir, "environment.yaml")
    
    print(f"\n{'='*60}")
    print(f"FOKUSSIERTER SCAN: {os.path.basename(root_dir)}")
    print(f"{'='*60}\n")

    # Rekursiver Scan NUR nach unten
    for root, dirs, files in os.walk(root_dir):
        # Ignoriere System-Ordner
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
        
        rel_path = os.path.relpath(root, root_dir)
        indent = "  " * rel_path.count(os.sep)
        display_name = "STAMMPFAD" if rel_path == "." else rel_path
        
        print(f"{indent}📂 {display_name}")

        for file in files:
            if file.endswith(".py") and file != "create_env.py":
                file_path = os.path.join(root, file)
                print(f"{indent}  📄 {file}")
                all_imports.update(get_imports_from_file(file_path))

    dependencies = set()
    for imp in all_imports:
        if imp in STDLIB:
            continue
        
        # Lokale Module/Dateien ausschließen
        if os.path.exists(os.path.join(root_dir, imp)) or \
           os.path.exists(os.path.join(root_dir, f"{imp}.py")):
            continue
            
        install_name = IMPORT_MAPPING.get(imp, imp.lower())
        version = get_version(install_name)
        
        if version:
            dependencies.add(f"{install_name}=={version}")
        else:
            dependencies.add(install_name)

    # YAML Daten zusammenstellen
    env_data = {
        "name": os.path.basename(root_dir).lower().replace(" ", "_"),
        "channels": ["defaults", "conda-forge"],
        "dependencies": [
            "python",
            "pip",
            {"pip": sorted(list(dependencies))}
        ]
    }

    with open(output_file, "w", encoding="utf-8") as f:
        yaml.dump(env_data, f, default_flow_style=False, sort_keys=False)
    
    print(f"\n{'='*60}")
    print(f"FERTIG: {output_file} wurde erstellt.")
    print(f"{'='*60}\n")

    # Automatisch öffnen
    try:
        os.startfile(output_file)
    except Exception:
        # Fallback für andere Systeme oder falls startfile fehlschlägt
        subprocess.call(['notepad.exe', output_file])

if __name__ == "__main__":
    generate_env_yaml(TARGET_PATH)