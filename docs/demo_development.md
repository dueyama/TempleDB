# Demo Development

This folder is intended for local demo changes, AI-assisted feature demonstrations, and disposable experiments.

Use `app/` as the editable TempleDB source tree. Use `datasets/` as the source
of SQLite demo data. The copied workspace should already include
`runtime/demo.sqlite3`, prebuilt from `datasets/synthetic_demo_v1/`, plus the
matching export markers under `app/data/generated/legacy_exports/`.

Do not edit `runtime/demo.sqlite3` or `app/data/generated/legacy_exports/`
directly. Regenerate them with `./bin/reset_demo_db.sh` only after changing
dataset files or when either the database or export markers are missing.

When changing demo source data, preserve production field meanings. In
`datasets/synthetic_demo_v1/service_schedules.json`, `subject_name` should be
the linked person's display name; kaimyo belongs in memorial/person memorial
fields and should not be written into the schedule display name.

For a requested change such as "make an accounting page that collects only selected payment categories", implement it in `app/`, run it against the synthetic SQLite dataset, and keep the result local to this demo workspace unless the user explicitly asks to port it back to the production repository.

The user is not expected to perform environment setup. Codex should prepare
`.venv`, install dependencies, confirm `runtime/demo.sqlite3` and
`app/data/generated/legacy_exports/demo-synthetic-rich/latest.json` exist, and
leave `TempleDB Demo.command` ready for double-click startup.
