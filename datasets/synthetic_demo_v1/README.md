# synthetic_demo_v1

Aggregate-profile synthetic dataset for TempleDB demos.

- Generated records are fully fictional.
- Real names, addresses, notes, and row-level source records are not copied.
- `profile.json` keeps only coarse aggregate hints used for reproducible generation.
- The JSON records are deterministic demo source data, not runtime state. The
  portable demo SQLite database is generated from these JSON files.
- `service_schedules.json` follows the production field semantics:
  `subject_name` is the linked person's display name, while kaimyo belongs in
  `memorials.json` and the loaded person's memorial fields.
- `sample_postal_scans/2026/demo-postal-scan-aoyama.pdf` is a fully synthetic
  PDF for trying the annual membership fee postal-scan workflow. It is
  hand-built test content, not a randomized export, and contains no real names
  or source records.
