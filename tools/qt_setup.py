import PySide6
import pkgutil
from pathlib import Path

print("PySide6 Version:", PySide6.__version__)
print("Location:", PySide6.__file__)

mods = sorted([m.name for m in pkgutil.iter_modules(PySide6.__path__)])

print("\nInstalled Qt Modules:")
for m in mods:
    print(" -", m)

base = Path(PySide6.__file__).parent

print("\nPlugin directories:")
for p in base.iterdir():
    if p.is_dir():
        print(" -", p)