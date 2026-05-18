window.THERMO0D_DOC_DATA = {
  "version": 4,
  "sections": [
    {
      "title": "Versionierung",
      "body": "Konfigurationsdateien werden über den Top-Level-Block versioning beschrieben. Ältere Dateien können beim Laden migriert werden."
    },
    {
      "title": "Preprocessing",
      "body": "Dieser Bereich enthält Gasdaten, Features, Engine-Geometrie, Volumes und Connections."
    },
    {
      "title": "Simulation",
      "body": "Hier liegen Integrationsparameter, Zyklenzahl und Solver-Einstellungen wie euler, rk4, scipy_rk45, scipy_bdf oder scipy_radau."
    },
    {
      "title": "Postprocessing",
      "body": "Sampling, CSV-Separator, finaler Last-Cycle-Export und Plot-Vorlagen werden hier beschrieben."
    }
  ],
  "exampleYaml": "versioning:\n  package_version: 7.1.56\n  config_schema_version: 4\npreprocessing:\n  engine:\n    cycle_type: 4t\nsimulation:\n  solver:\n    kind: rk4\npostprocessing:\n  sampling:\n    mode: crank_angle\n    step_deg: 1.0\n"
};
