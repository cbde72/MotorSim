# Free-Piston Single-Instance Compatibility Aliases

## Zweck

Free-Piston-Ausgaben koennen mehrere lokale Volumen-/Connection-Instanzen enthalten, z. B. `cylinder_1`, `cylinder_2`, `transfer_slot_1`, `transfer_slot_2`. Neue Plot-Konfigurationen sollen diese expliziten Signalnamen verwenden.

Damit bestehende Ein-Kolben-/Ein-Seiten-Varianten und alte Plot-YAMLs kurzfristig weiterlaufen, erzeugt die Reconstruction temporaer Singular-Aliase, wenn ein Signal eindeutig ist.

## Verhalten

Wenn genau eine Instanz vorhanden ist:

- `cylinder_1_*` wird zusaetzlich als `cylinder_*` exportiert.
- `transfer_slot_1_*` wird zusaetzlich als `transfer_slot_*` exportiert.
- eine einzelne Bounce-Chamber wird zusaetzlich als `bounce_*` exportiert, auch wenn sie intern z. B. `compressor_1` heisst.
- Connections einer einzelnen Bounce-Chamber wie `compressor_1_in_cv_*` werden zusaetzlich als `bounce_in_cv_*` exportiert.

Wenn mehrere Instanzen vorhanden sind, werden keine mehrdeutigen Singular-Aliase erzeugt. Bei V11 mit `cylinder_1` und `cylinder_2` gibt es daher bewusst kein `cylinder_*`.

## TODO

- Plot-YAMLs schrittweise auf explizite Instanznamen umstellen.
- Alte Singular-Signale nach einer Uebergangsphase entfernen oder hinter eine Config-Option legen.
- Fuer opposed Varianten eigene Default-Plots pflegen, die beide Seiten explizit darstellen.
