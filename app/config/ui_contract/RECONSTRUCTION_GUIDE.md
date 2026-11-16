# UI Maintenance and Reconstruction Guide for Codex

Use this guide when an AI maintenance handoff package is given to Codex and the
task is to understand, maintain, or reconstruct TempleDB's UI. The exporter does
not read live individual database rows and cannot rehydrate a TempleDB database.
Tracked source/history may nevertheless contain operational PII or tenant details,
so the package is only for a trusted internal maintainer or AI.

## Read Order

1. `AI_HANDOFF.md` and the package manifest
2. `checks/verification.md`
3. `ui_contract/UI_LANGUAGE.md`
4. `ui_contract/design_tokens.json` and `ui_contract/source_map.json`
5. `ui_contract/screens/*.yaml`, `components/*.yaml`, and `workflows/*.yaml`
6. the allowlisted source snapshot under `source/`, especially current Django
   templates and route/view code
7. `schema/physical_schema.json` and `runtime/migrations.json`
8. `runtime/model_counts.json` and `runtime/backup_status.json`
9. `ui_contract/acceptance/reconstruction_checks.yaml`

## Build Strategy

1. Confirm the package manifest and verification result before trusting its
   snapshot.
2. Use the physical schema and migration inventory to understand structure,
   without treating either as data to import.
3. Create a small component library from `components/*.yaml`.
4. Implement routes from `source_map.json`.
5. For each screen, implement `semantic_tree` first.
6. Apply `visual_signature` and `design_tokens.json`.
7. Compare against the allowlisted template source for visible order, labels,
   grouped actions, disclosure, and empty-state wording.
8. Create synthetic fixtures separately if the target UI needs sample records.
9. Run or manually satisfy `acceptance/reconstruction_checks.yaml`.

## Important Rules

- Do not turn TempleDB into a landing page. It is a dense work application.
- Preserve Japanese operational labels.
- Preserve help popovers and collapsed related-action menus.
- Preserve soft-delete, restore, audit note, and destructive-action separation.
- Treat Google Calendar as downstream; TempleDB remains source of truth.
- Treat the source snapshot as maintenance evidence, not as code to execute
  blindly in the target app.
- Treat model counts as aggregate context only; they do not identify or recreate
  any record.
- Treat backup status as status evidence only. It is not the backup payload.
- Do not look for fixture JSONL or private operational rows in this package.
  Database restore and private migration-data export are separate workflows.

## When Output Is Poor

If the generated UI looks wrong:

- Re-read the screen's `semantic_tree`.
- Check the selected template in `source/templates/`.
- Add missing nodes to the screen YAML before restyling.
- Add an acceptance check for the lost behavior or region.
- Avoid solving missing structure with colors or screenshots.
