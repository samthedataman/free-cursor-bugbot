"use strict";
const kinds = {
  commit: ["Commit", "git"],
  related: ["Related commit", "git"],
  file: ["File", "file"],
  risk: ["Risk signal", "risk"],
  ref: ["Issue / PR reference", "issue"],
  finding: ["Review finding", "shield"],
};

function makeGraph(data, receipt, details = new Map()) {
  const nodes = new Map(),
    edges = new Map();
  const add = (id, kind, label, sub, column, info = {}) => {
    if (!nodes.has(id))
      nodes.set(id, { id, kind, label, sub, column, ...info });
    return id;
  };
  const edge = (from, to, why) => {
    if (from !== to)
      edges.set(JSON.stringify([from, to, why]), { from, to, why });
  };
  const commit = add(
    "c:" + data.head,
    "commit",
    data.commit.short,
    "Selected commit",
    0,
    { body: data.commit.subject },
  );
  const file = (path, changed = false) =>
    add("f:" + path, "file", path.split("/").pop(), path, changed ? 1 : 2, {
      path,
    });
  const reference = (r) => {
    const loaded = details.get(r.id);
    return add(
      "i:" + r.id,
      "ref",
      r.label,
      loaded?.title || r.repo || "Local reference",
      2,
      { ref: r, body: loaded?.title, loaded },
    );
  };
  for (const f of data.files) edge(commit, file(f.path, true), "changed");
  for (const r of data.refs) edge(commit, reference(r), "mentions");
  for (const c of data.related) {
    const id = add("c:" + c.sha, "related", c.short, c.subject, 1, {
      sha: c.sha,
      body: c.subject,
    });
    for (const ref of c.refs) edge(id, "i:" + ref, "mentions");
  }
  for (const [parent, detail] of details) {
    if (!nodes.has("i:" + parent)) continue;
    for (const ref of detail.refs)
      edge("i:" + parent, reference(ref), "mentions in description");
  }
  for (const r of data.risks) {
    const id = add(
      "r:" + r.label,
      "risk",
      r.label,
      r.severity + " · rule match",
      2,
      {
        severity: r.severity,
        body: r.paths.length
          ? "Matched these changed file names."
          : "Matched a pattern in the committed diff.",
      },
    );
    if (r.paths.length)
      for (const p of r.paths) edge(file(p), id, "matches risk rule");
    else edge(commit, id, "diff matches risk rule");
  }
  for (const link of data.connections)
    edge(file(link.source), file(link.target), link.relation);
  for (const [index, f] of (receipt?.findings || []).entries()) {
    const id = add("a:" + index, "finding", f.title, f.file + ":" + f.line, 2, {
      severity: f.severity,
      path: f.file,
      body: f.detail,
      checkers: f.checkers,
      line: f.line,
    });
    edge(file(f.file), id, "finding at line " + f.line);
  }
  return { nodes, edges: [...edges.values()], commit };
}

function graphView(data, receipt, state) {
  const graph = makeGraph(data, receipt, state.issueDetails);
  const focus = graph.nodes.get(state.node) || graph.nodes.get(graph.commit);
  const rule = { issues: ["ref", "finding"], risks: ["risk"], files: ["file"] }[
    state.filter
  ];
  let universe = [...graph.nodes.values()];
  if (rule) {
    const selected = new Set(
      universe.filter((n) => rule.includes(n.kind)).map((n) => n.id),
    );
    const keep = new Set([graph.commit, ...selected]);
    for (const e of graph.edges)
      if (selected.has(e.from) || selected.has(e.to)) {
        keep.add(e.from);
        keep.add(e.to);
      }
    universe = universe.filter((n) => keep.has(n.id));
  }
  const priority = {
    finding: 0,
    ref: 1,
    risk: 2,
    related: 3,
    file: 4,
    commit: 0,
  };
  const groups = [0, 1, 2].map((col) =>
    universe
      .filter((n) => n.column === col)
      .sort((a, b) => priority[a.kind] - priority[b.kind]),
  );
  const limit = state.graphLimit;
  const visible = groups.map((list) => {
    // Keep files, issue references and findings discoverable even on busy commits.
    const kindsShown = new Set();
    const firstOfEach = list.filter((n) => {
      if (kindsShown.has(n.kind)) return false;
      kindsShown.add(n.kind);
      return true;
    });
    const order = [...new Set([...firstOfEach, ...list])];
    const section = order.slice(0, limit);
    if (list.includes(focus) && !section.includes(focus))
      section[section.length - 1] = focus;
    return section;
  });
  const rows = Math.max(1, ...visible.map((x) => x.length));
  const height = Math.max(265, rows * 70 + 24),
    width = 770,
    card = 192;
  const positions = new Map();
  for (const [column, nodes] of visible.entries()) {
    nodes.forEach((n, i) =>
      positions.set(n.id, {
        x: 20 + column * 267,
        y: (height - nodes.length * 70) / 2 + i * 70 + 11,
      }),
    );
  }
  const lines = graph.edges
    .filter((e) => positions.has(e.from) && positions.has(e.to))
    .map((e) => {
      const a = positions.get(e.from),
        b = positions.get(e.to);
      const same = a.x === b.x,
        reverse = a.x > b.x;
      const x1 = a.x + (reverse ? 0 : card),
        x2 = b.x + (reverse || same ? card : 0);
      const bend = same ? x1 + 34 : (x1 + x2) / 2;
      const active = e.from === focus.id || e.to === focus.id;
      return `<path class="edge ${active ? "active" : ""}" d="M${x1},${a.y + 23} C${bend},${a.y + 23} ${bend},${b.y + 23} ${x2},${b.y + 23}"><title>${esc(e.why)}</title></path>`;
    })
    .join("");
  const buttons = [...positions]
    .map(([id, pos]) => {
      const n = graph.nodes.get(id);
      return `<button class="node ${n.kind} ${n.id === focus.id ? "selected" : ""}" data-node="${esc(n.id)}" title="${esc(n.label)} · ${esc(n.sub)}" style="left:${pos.x}px;top:${pos.y}px;width:${card}px">
      <span class="node-symbol">${icon(kinds[n.kind][1], 16)}</span><span><b>${esc(n.label)}</b><small>${esc(n.sub)}</small></span></button>`;
    })
    .join("");
  const connections = graph.edges.filter(
    (e) => e.from === focus.id || e.to === focus.id,
  );
  const neighbors = connections
    .map((e) => {
      const n = graph.nodes.get(e.from === focus.id ? e.to : e.from);
      if (!n) return "";
      return `<button class="neighbor" data-node="${esc(n.id)}"><span class="color-${n.kind}">${icon(kinds[n.kind][1], 15)}</span><span><b>${esc(n.label)}</b><small>${esc(e.why)}</small></span>${icon("right", 13)}</button>`;
    })
    .join("");
  const inspector = `<aside class="inspector"><h3>Inspector</h3><div class="inspect-type color-${focus.kind}">${icon(kinds[focus.kind][1])}${esc(focus.loaded?.kind || kinds[focus.kind][0])}</div>
    <h4>${esc(focus.label)}</h4><p>${esc(focus.body || focus.sub)}</p>${focus.severity ? severity(focus.severity) : ""}
    ${focus.checkers ? `<p>Reported by ${esc(focus.checkers.join(", "))}</p>` : ""}
    ${focus.ref?.repo ? `<div class="inspect-actions">${button(focus.loaded ? "Refresh details" : "Load GitHub details", "load-issue", { icon: "refresh" })}${button("Open on GitHub", "open-issue", { icon: "external" })}</div>` : ""}
    ${focus.loaded ? `<small>${esc(focus.loaded.state)}</small>` : ""}
    ${focus.sha ? button("View commit", "related-commit", { icon: "git" }) : ""}
    ${focus.path && data.files.some((f) => f.path === focus.path || f.oldPath === focus.path) ? button("View diff", "node-diff", { icon: "diff" }) : ""}
    <div class="inspector-links"><h3>Connections <span>${connections.length}</span></h3>${neighbors || "<small>No connections</small>"}</div></aside>`;
  const shown = positions.size;
  const zoom = state.zoom;
  return `<div class="graph-layout"><section class="map"><div class="map-toolbar"><div class="map-title">${icon("graph")}<h3>Relationships</h3></div><select id="graph-filter" aria-label="Graph filter">${[
    ["all", "All types"],
    ["issues", "Issues & findings"],
    ["risks", "Risk signals"],
    ["files", "Files"],
  ]
    .map(
      ([v, l]) =>
        `<option value="${v}" ${state.filter === v ? "selected" : ""}>${l}</option>`,
    )
    .join("")}</select></div>
    <div class="graph-scroll"><div class="canvas-size" style="width:${width * zoom}px;height:${height * zoom}px"><div class="canvas" style="width:${width}px;height:${height}px;transform:scale(${zoom})"><svg class="edges" viewBox="0 0 ${width} ${height}">${lines}</svg>${buttons}</div></div></div>
    <div class="map-foot"><span>${num(shown)} of ${num(universe.length)} nodes</span>${shown < universe.length ? '<button class="text-btn" data-do="more-nodes">Show more</button>' : ""}<div class="spacer"></div>
    <button class="icon-btn" data-do="zoom-minus" aria-label="Zoom out">${icon("minus", 14)}</button><button class="zoom-value" data-do="zoom-reset" title="Fit graph">${Math.round(zoom * 100)}%</button><button class="icon-btn" data-do="zoom-plus" aria-label="Zoom in">${icon("plus", 14)}</button></div></section>${inspector}</div>`;
}
