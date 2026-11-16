# TempleDB UI Contract v2

This directory is the structured UI maintenance and reconstruction contract for
TempleDB. It is included in the AI maintenance handoff package so Codex can
understand the main product experience without relying on screenshots. It is not
a database export, fixture bundle, or restore input.

## Status

- Contract version: `2`
- Language: `templedb-ui-dsl-v2`
- Scope: representative screens, workflows, and shared components
- Authority: descriptive reconstruction contract, not TempleDB's runtime renderer
- Runtime effect: none. TempleDB continues to render from Django views/templates.

Read `UI_LANGUAGE.md` before editing or consuming the YAML files. Read
`RECONSTRUCTION_GUIDE.md` before using the package for maintenance or asking
Codex to build another implementation.

## v2 Additions

v1 was intentionally simple and is not strong enough for near-UI reproduction.
v2 adds:

- `semantic_tree`: a DOM-like hierarchy of page, panel, form, list, detail,
  card, and action nodes.
- `visual_signature`: density, grid, spacing, disclosure, and emphasis rules
  that matter for visual reconstruction.
- `state_matrix`: the states that must not be lost when recreating a screen.
- `evidence`: source template and partial references used as text authority.
- `source_map.json`: route-to-template-to-contract map.
- `acceptance/reconstruction_checks.yaml`: screen-level checks for generated
  UI.
- `source/templates/` in the generated handoff package: allowlisted current
  template source files for representative screens.

## File Types

### Screen YAML

Screen files live under `screens/` and describe a page-level UI contract.

Required fields:

- `contract_type`: `screen`
- `version`: integer contract version
- `dsl_version`: integer UI DSL version
- `screen_id`: stable screen identifier
- `title`: visible or human-facing screen name
- `route_name`: Django URL name without namespace
- `route_path`: route pattern or concrete path
- `template`: primary Django template path
- `purpose`: concise product purpose
- `primary_models`: canonical data touched or displayed
- `layout`: density, major columns, responsive behavior
- `regions`: ordered UI regions and their role
- `actions`: user commands and navigation affordances
- `states`: empty, unavailable, permission, validation, or error states
- `data_bindings`: important model/field-to-UI bindings
- `workflow_refs`: workflows that include this screen
- `semantic_tree`: DOM-like reconstruction tree
- `visual_signature`: visual constraints that must survive translation
- `state_matrix`: state-by-state reconstruction behavior
- `evidence`: template and source-map references

### Action Objects

Actions describe intent, not a full mutation implementation.

Required fields:

- `action_id`: stable identifier
- `label`: visible label or semantic label
- `intent`: why the user performs the action
- `method`: `GET`, `POST`, or `CLIENT`
- `route_name`: target route when known
- `mutating`: boolean
- `risk_level`: `none`, `low`, `medium`, or `high`
- `confirmation`: `none`, `inline`, `browser_confirm`, or `server_confirm`

Mutating actions must always include `risk_level` and `confirmation`.

### Workflow YAML

Workflow files live under `workflows/` and describe task flow across screens.

Required fields:

- `contract_type`: `workflow`
- `version`: integer contract version
- `workflow_id`: stable workflow identifier
- `title`: human-facing workflow name
- `entry_points`: screen ids where the workflow starts
- `steps`: ordered intent-level steps
- `completion`: expected end state

### Component YAML

Component files live under `components/` and describe reusable UI patterns.

Required fields:

- `contract_type`: `component`
- `version`: integer contract version
- `component_id`: stable component identifier
- `purpose`: role in the product UI
- `structure`: expected parts
- `usage`: screen ids or regions where it appears

## Reconstruction Rules

- Treat `ui_contract/` as the semantic contract.
- Treat `source/templates/` as current-UI textual evidence.
- When the two appear to conflict, preserve the current UI's visible structure
  from `source/` and preserve the intent/action names from `ui_contract/`.
- Preserve Japanese labels and domain terms from the contract unless tenant
  policy explicitly supplies alternate labels.
- Treat `policy/tenant_policy_default/` as the label and rule authority for
  terms such as 法名/戒名.
- Preserve information density. TempleDB is a work application, not a landing
  page.
- Preserve progressive disclosure patterns such as help popovers, collapsed
  related actions, and card expansion.
- Keep destructive and audit-sensitive actions visually distinct.
- Recreate operation meaning before pixel-level styling, then use template/CSS
  evidence to tighten layout, spacing, and disclosure.
- Do not infer database writes from this contract alone. Mutation details must
  come from a separate migration or application design plan.
- Use the packaged physical schema and migration inventory to understand
  database structure. The UI contract does not contain database rows.
- Treat the packaged source snapshot as a maintenance reference, not as a
  database snapshot or fixture source.
- If a separate implementation needs sample records, create synthetic fixtures
  for that implementation. Do not infer or recreate TempleDB's operational
  records from aggregate counts.

## Privacy

The UI contract itself does not contain source credentials, private files, raw
imports, or individual operational rows. The AI maintenance handoff does not
read individual operational database rows, but its Git-tracked source/history
corpus may already contain operational PII, tenant identity, endpoints, paths,
or connection defaults. Credential pattern scanning is not PII anonymization or
proof that all source text is secret-free. Give the package only to a trusted
internal maintainer or AI; it is not a public artifact and cannot rehydrate a
TempleDB database. A backup or an explicitly authorized private migration-data
export is a separate artifact with a different purpose and access policy.
