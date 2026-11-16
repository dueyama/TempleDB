# TempleDB UI DSL v2

TempleDB UI DSL v2 is a structured language for AI-assisted UI reconstruction.
It is intentionally closer to a semantic DOM than to prose. A target
implementation may be Django, React, SwiftUI, or another stack, but the same
screen contract should produce the same product shape.

## Reconstruction Layers

Reconstruct in this order:

1. **Domain layer**: screens, workflows, domain concepts, settings, and schema
   metadata.
2. **Semantic UI layer**: `semantic_tree`, regions, actions, state matrix.
3. **Visual layer**: design tokens, density, grids, emphasis, disclosure.
4. **Interaction layer**: route intent, forms, mutations, confirmations.
5. **Evidence layer**: allowlisted Django templates in `source/templates/`.
6. **Acceptance layer**: checks in `acceptance/reconstruction_checks.yaml`.

The DSL is the cross-stack meaning. The template source is the current-UI text
evidence. Use both.

## Screen Grammar

Every screen YAML is a `screen` contract:

```yaml
contract_type: screen
version: 2
dsl_version: 2
screen_id: household_browser
route_name: household_browser
template: office/household_browser.html
semantic_tree:
  node_id: household_browser.page
  kind: page
  children:
    - node_id: household_browser.hero
      kind: hero
```

Required screen sections:

- `layout`: coarse page layout.
- `regions`: business regions visible to the user.
- `actions`: operation intent, route, mutating flag, risk, confirmation.
- `states`: human-readable state descriptions.
- `state_matrix`: machine-oriented state behavior.
- `semantic_tree`: nested reconstruction nodes.
- `visual_signature`: visual constraints.
- `data_bindings`: important data-to-UI mappings.
- `evidence`: current UI source references.

## Node Grammar

`semantic_tree` nodes use these fields:

- `node_id`: stable dot-separated id.
- `kind`: `page`, `hero`, `panel`, `grid`, `form`, `list`, `detail`,
  `card_stack`, `card`, `section`, `summary`, `action_bar`,
  `details_menu`, `callout`, `table`, `field_grid`, or `component_ref`.
- `role`: short business purpose.
- `priority`: `primary`, `secondary`, or `supporting`.
- `component`: optional component id from `components/`.
- `visual`: local visual constraints.
- `bindings`: data references.
- `actions`: action ids exposed inside the node.
- `children`: nested nodes.

Node ids are stable reconstruction anchors. Do not use CSS class names as node
ids unless the class itself is the business anchor.

## Visual Signature

`visual_signature` captures what an AI normally loses:

- density: how much data appears before scrolling.
- rhythm: gaps, panel hierarchy, repeated card/table cadence.
- information_priority: what must be visible first.
- responsive_behavior: what stacks, hides, or collapses.
- disclosure: what is always visible versus hidden in details/help.
- danger_emphasis: how risky actions are visually separated.
- typography: display/body/mono usage.

## Action Contract

Actions are not CRUD specifications. They are operation intent.

Mutating actions must specify:

- `mutating: true`
- `risk_level`: `low`, `medium`, or `high`
- `confirmation`: `inline`, `browser_confirm`, or `server_confirm`
- `result`: expected effect in human terms

Read-only actions use:

- `mutating: false`
- `risk_level: none`
- `confirmation: none`

## Evidence Contract

`evidence` names the source material that should be used to tighten the
reconstruction:

```yaml
evidence:
  source_map_ref: source_map.json#/screens/household_browser
  template_paths:
    - source/templates/office/household_browser.html
    - source/templates/office/_household_browser_detail_content.html
```

The generated handoff package includes those selected templates under
`source/templates/` as part of its allowlisted source snapshot.

## Maintenance Package Boundary

The UI DSL is documentation for maintenance and reconstruction. It is not a
row-level data contract. The AI maintenance handoff package can provide
allowlisted source, documentation, physical schema, migration state, aggregate
model counts, and backup status, but it does not read live household, person,
deceased, service, accounting, or other operational rows. Tracked source/history
may still contain operational PII, tenant identity, paths, endpoints, or connection
defaults and is only for a trusted internal maintainer or AI.

Treat the packaged source snapshot as code evidence for maintenance. Treat
aggregate counts only as a coarse production-shape reference. Neither can be
used to populate or rehydrate a database. Database restoration and private data
migration require separately authorized artifacts and procedures.

## Translation Rule

When translating to another stack:

- Convert `semantic_tree.kind` to target components.
- Convert `actions` to route handlers or form commands.
- Convert `visual_signature` and `design_tokens.json` into theme/layout rules.
- Use `source/templates/` to recover exact labels, grouping, and inline ordering.
- Use `acceptance/` checks to decide whether the reconstruction is acceptable.
- Create synthetic fixtures in the target implementation when interaction needs
  sample records; do not attempt to derive records from package metadata.
