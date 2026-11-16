(() => {
  "use strict";

  const explorer = document.querySelector("[data-schema-explorer]");
  const dataElement = document.getElementById("database-schema-data");
  if (!explorer || !dataElement) return;

  let schema;
  try {
    schema = JSON.parse(dataElement.textContent);
  } catch (_error) {
    return;
  }

  const searchInput = explorer.querySelector("#schema-search");
  const groupControls = Array.from(explorer.querySelectorAll("[data-schema-group-control]"));
  const tableCards = Array.from(explorer.querySelectorAll("[data-schema-table]"));
  const relationRows = Array.from(explorer.querySelectorAll("[data-schema-relation]"));
  const groupPanels = Array.from(explorer.querySelectorAll("[data-schema-group-panel]"));
  const status = explorer.querySelector("[data-schema-status]");
  const noResults = explorer.querySelector("[data-schema-no-results]");
  const graph = explorer.querySelector("[data-schema-graph]");
  const graphShell = explorer.querySelector("[data-schema-graph-shell]");
  const resetButton = explorer.querySelector("[data-schema-reset]");
  const expandButton = explorer.querySelector("[data-schema-expand]");
  const collapseButton = explorer.querySelector("[data-schema-collapse]");
  const tableAnchor = new Map();

  tableCards.forEach((card) => {
    tableAnchor.set(card.dataset.tableName, card.id);
  });

  function normalized(value) {
    return String(value || "").toLocaleLowerCase("ja").normalize("NFKC");
  }

  function activeGroups() {
    return new Set(groupControls.filter((control) => control.checked).map((control) => control.value));
  }

  function updateFilters() {
    const query = normalized(searchInput ? searchInput.value.trim() : "");
    const enabledGroups = activeGroups();
    const visibleTableNames = new Set();

    tableCards.forEach((card) => {
      const groupMatches = enabledGroups.has(card.dataset.schemaGroup);
      const searchMatches = !query || normalized(card.textContent).includes(query);
      const visible = groupMatches && searchMatches;
      card.hidden = !visible;
      if (visible) {
        visibleTableNames.add(card.dataset.tableName);
        if (query) card.open = true;
      }
    });

    groupPanels.forEach((panel) => {
      panel.hidden = !Array.from(panel.querySelectorAll("[data-schema-table]")).some((card) => !card.hidden);
    });

    let visibleRelationCount = 0;
    relationRows.forEach((row) => {
      const fromVisible = visibleTableNames.has(row.dataset.fromTable);
      const toVisible = visibleTableNames.has(row.dataset.toTable);
      const visible = fromVisible && toVisible;
      row.hidden = !visible;
      if (visible) visibleRelationCount += 1;
    });

    if (status) {
      status.textContent = `テーブル・ビュー ${visibleTableNames.size} 件・外部キー ${visibleRelationCount} 件を表示`;
    }
    if (noResults) noResults.hidden = visibleTableNames.size !== 0;
    drawGraph(visibleTableNames);
  }

  function relationList() {
    if (Array.isArray(schema.relations) && schema.relations.length) return schema.relations;
    const collected = [];
    const seen = new Set();
    (schema.groups || []).forEach((group) => {
      (group.tables || []).forEach((table) => {
        (table.outgoing_relations || []).forEach((relation) => {
          const key = JSON.stringify([
            relation.source_table,
            relation.source_columns,
            relation.target_table,
            relation.target_columns,
          ]);
          if (!seen.has(key)) {
            seen.add(key);
            collected.push(relation);
          }
        });
      });
    });
    return collected;
  }

  function svgElement(tagName, attributes = {}) {
    const element = document.createElementNS("http://www.w3.org/2000/svg", tagName);
    Object.entries(attributes).forEach(([name, value]) => element.setAttribute(name, String(value)));
    return element;
  }

  function appendText(parent, value) {
    parent.textContent = String(value || "");
    return parent;
  }

  function listLabel(value) {
    return Array.isArray(value) ? value.join(", ") : String(value || "");
  }

  function drawGraph(visibleTableNames) {
    if (!graph || !graphShell) return;
    while (graph.firstChild) graph.removeChild(graph.firstChild);

    const graphTitle = appendText(
      svgElement("title", {id: "schema-graph-title"}),
      "データベースの物理外部キー関係図",
    );
    const graphDescription = appendText(
      svgElement("desc", {id: "schema-graph-description"}),
      "現在接続中のデータベースに実在する外部キーだけを線で結んだ関係図です。",
    );
    graph.appendChild(graphTitle);
    graph.appendChild(graphDescription);

    const groups = (schema.groups || []).map((group) => ({
      key: group.key,
      label: group.label,
      tables: (group.tables || []).filter((table) => visibleTableNames.has(table.name)),
    })).filter((group) => group.tables.length);

    if (!groups.length) {
      graph.setAttribute("viewBox", "0 0 720 260");
      graph.setAttribute("width", "720");
      graph.setAttribute("height", "260");
      graph.appendChild(appendText(
        svgElement("text", {x: 360, y: 130, "text-anchor": "middle", class: "schema-graph-group-label"}),
        "条件に一致するテーブルはありません。",
      ));
      return;
    }

    const laneWidth = 282;
    const nodeWidth = 226;
    const nodeHeight = 34;
    const nodeGap = 9;
    const groupPadding = 18;
    const groupHeader = 40;
    const rowGap = 24;
    const columns = Math.min(4, Math.max(1, groups.length));
    const rows = [];

    for (let index = 0; index < groups.length; index += columns) {
      rows.push(groups.slice(index, index + columns));
    }

    const rowHeights = rows.map((row) => Math.max(...row.map((group) =>
      groupHeader + groupPadding + group.tables.length * nodeHeight + Math.max(0, group.tables.length - 1) * nodeGap
    )));
    const width = Math.max(720, columns * laneWidth + groupPadding * 2);
    const height = Math.max(260, rowHeights.reduce((sum, value) => sum + value, 0) + rowGap * (rows.length + 1));
    graph.setAttribute("viewBox", `0 0 ${width} ${height}`);
    graph.setAttribute("width", String(width));
    graph.setAttribute("height", String(height));

    const defs = svgElement("defs");
    const marker = svgElement("marker", {
      id: "schema-arrow",
      viewBox: "0 0 10 10",
      refX: 8,
      refY: 5,
      markerWidth: 6,
      markerHeight: 6,
      orient: "auto-start-reverse",
    });
    marker.appendChild(svgElement("path", {d: "M 0 0 L 10 5 L 0 10 z", fill: "var(--accent)"}));
    defs.appendChild(marker);
    graph.appendChild(defs);

    const groupLayer = svgElement("g");
    const edgeLayer = svgElement("g");
    const nodeLayer = svgElement("g");
    const positions = new Map();
    let rowY = rowGap;

    rows.forEach((row, rowIndex) => {
      row.forEach((group, columnIndex) => {
        const x = groupPadding + columnIndex * laneWidth;
        const groupHeight = rowHeights[rowIndex];
        groupLayer.appendChild(svgElement("rect", {
          x,
          y: rowY,
          width: laneWidth - groupPadding,
          height: groupHeight,
          rx: 7,
          class: "schema-graph-group-box",
        }));
        groupLayer.appendChild(appendText(
          svgElement("text", {
            x: x + 12,
            y: rowY + 25,
            class: "schema-graph-group-label",
          }),
          `${group.label}（${group.tables.length}）`,
        ));

        group.tables.forEach((table, tableIndex) => {
          positions.set(table.name, {
            x: x + 14,
            y: rowY + groupHeader + tableIndex * (nodeHeight + nodeGap),
            table,
          });
        });
      });
      rowY += rowHeights[rowIndex] + rowGap;
    });

    relationList().filter((relation) => positions.has(relation.source_table) && positions.has(relation.target_table)).forEach((relation) => {
      const source = positions.get(relation.source_table);
      const target = positions.get(relation.target_table);
      let startX;
      let endX;
      let controlOffset;
      let pathData;
      if (source === target) {
        startX = source.x + nodeWidth;
        endX = source.x + nodeWidth;
        const startY = source.y + nodeHeight * .7;
        const endY = source.y + nodeHeight * .3;
        pathData = `M ${startX} ${startY} C ${startX + 52} ${startY}, ${endX + 52} ${endY - 36}, ${endX} ${endY}`;
      } else if (source.x === target.x) {
        startX = source.x + nodeWidth;
        endX = target.x + nodeWidth;
        controlOffset = 42 + Math.min(90, Math.abs(source.y - target.y) / 3);
      } else if (source.x < target.x) {
        startX = source.x + nodeWidth;
        endX = target.x;
        controlOffset = Math.max(38, Math.abs(endX - startX) * .45);
      } else {
        startX = source.x;
        endX = target.x + nodeWidth;
        controlOffset = -Math.max(38, Math.abs(endX - startX) * .45);
      }
      const startY = source.y + nodeHeight / 2;
      const endY = target.y + nodeHeight / 2;
      if (!pathData) {
        pathData = `M ${startX} ${startY} C ${startX + controlOffset} ${startY}, ${endX - controlOffset} ${endY}, ${endX} ${endY}`;
      }
      const path = svgElement("path", {
        d: pathData,
        class: `schema-graph-edge${relation.required ? "" : " is-optional"}${relation.unique ? " is-unique" : ""}`,
        "marker-end": "url(#schema-arrow)",
        "data-from-table": relation.source_table,
        "data-to-table": relation.target_table,
      });
      const title = svgElement("title");
      appendText(
        title,
        `${relation.source_table} (${listLabel(relation.source_columns)}) → ${relation.target_table} (${listLabel(relation.target_columns)})`,
      );
      path.appendChild(title);
      edgeLayer.appendChild(path);
    });

    positions.forEach(({x, y, table}, tableName) => {
      const node = svgElement("a", {
        href: `#${tableAnchor.get(tableName) || "schema-table-catalog"}`,
        class: "schema-graph-node",
        "data-table-name": tableName,
        "aria-label": `${tableName} の定義へ移動`,
      });
      node.appendChild(svgElement("rect", {x, y, width: nodeWidth, height: nodeHeight, rx: 4}));
      node.appendChild(appendText(
        svgElement("text", {x: x + 9, y: y + 21, class: "schema-graph-node-name"}),
        tableName.length > 27 ? `${tableName.slice(0, 25)}…` : tableName,
      ));
      node.appendChild(appendText(
        svgElement("text", {x: x + nodeWidth - 8, y: y + 21, class: "schema-graph-node-count"}),
        `${table.column_count}列`,
      ));
      const title = svgElement("title");
      appendText(title, `${tableName}：${table.column_count}カラム、外向${table.outgoing_relation_count}、内向${table.incoming_relation_count}`);
      node.appendChild(title);
      ["mouseenter", "focus"].forEach((eventName) => node.addEventListener(eventName, () => highlightConnections(tableName)));
      ["mouseleave", "blur"].forEach((eventName) => node.addEventListener(eventName, clearConnectionHighlight));
      nodeLayer.appendChild(node);
    });

    graph.appendChild(groupLayer);
    graph.appendChild(edgeLayer);
    graph.appendChild(nodeLayer);
  }

  function highlightConnections(tableName) {
    const edges = Array.from(graph.querySelectorAll(".schema-graph-edge"));
    const connectedNames = new Set([tableName]);
    edges.forEach((edge) => {
      const connected = edge.dataset.fromTable === tableName || edge.dataset.toTable === tableName;
      edge.classList.toggle("is-connected", connected);
      edge.classList.toggle("is-dimmed", !connected);
      if (connected) {
        connectedNames.add(edge.dataset.fromTable);
        connectedNames.add(edge.dataset.toTable);
      }
    });
    graph.querySelectorAll(".schema-graph-node").forEach((node) => {
      node.classList.toggle("is-connected", connectedNames.has(node.dataset.tableName));
      node.classList.toggle("is-dimmed", !connectedNames.has(node.dataset.tableName));
    });
  }

  function clearConnectionHighlight() {
    graph.querySelectorAll(".schema-graph-edge, .schema-graph-node").forEach((element) => {
      element.classList.remove("is-connected", "is-dimmed");
    });
  }

  if (searchInput) searchInput.addEventListener("input", updateFilters);
  groupControls.forEach((control) => control.addEventListener("change", updateFilters));
  if (resetButton) {
    resetButton.addEventListener("click", () => {
      if (searchInput) searchInput.value = "";
      groupControls.forEach((control) => { control.checked = true; });
      updateFilters();
      if (searchInput) searchInput.focus();
    });
  }
  if (expandButton) {
    expandButton.addEventListener("click", () => {
      tableCards.filter((card) => !card.hidden).forEach((card) => { card.open = true; });
    });
  }
  if (collapseButton) {
    collapseButton.addEventListener("click", () => {
      tableCards.forEach((card) => { card.open = false; });
    });
  }

  updateFilters();
})();
