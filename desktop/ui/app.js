"use strict";
const api = window.bugbot;
const state = {
  history: null,
  branch: "",
  commits: [],
  selected: "",
  data: null,
  tab: "graph",
  settings: null,
  filter: "all",
  node: "",
  graphLimit: 4,
  zoom: 1,
  issueDetails: new Map(),
  runId: "",
  file: "",
  diff: null,
};
let repoEpoch = 0,
  historyTicket = 0,
  detailTicket = 0,
  diffTicket = 0;
const running = new Set();
const key = () => repoEpoch + "/" + state.selected;
function errorText(e) {
  return String(e?.message || e).replace(
    /^Error invoking remote method '[^']+': (?:Error: )?/,
    "",
  );
}
let noticeTimer;
function notice(message) {
  $("#notice").textContent = message;
  $("#notice").hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => {
    $("#notice").hidden = true;
  }, 6500);
}
function severity(value) {
  return `<span class="severity ${["critical", "high", "medium", "low"].includes(value) ? value : "low"}">${esc(value)}</span>`;
}
function selectedRun() {
  return (
    state.data?.runs.find((r) => r.id === state.runId) || state.data?.runs[0]
  );
}
function toolbar() {
  const busy = running.has(key());
  $("#run-btn").disabled = !state.data || !state.settings || busy;
  $("#run-label").textContent = busy ? "Review running…" : "Run review";
  $("#checker-count").textContent = state.settings?.checkers.length ?? "…";
}
function intro(message) {
  $("#main").innerHTML = emptyState(
    "graph",
    "Open a repository",
    message ||
      "Explore Git history and review changes with your own model checkers.",
    button("Open repository", "open", { primary: true, icon: "folder" }),
  );
  toolbar();
}
function renderHistory() {
  const filter = $("#search").value.trim().toLowerCase();
  const rows = state.commits.filter((c) =>
    (c.subject + " " + c.author + " " + c.sha).toLowerCase().includes(filter),
  );
  let previous = "";
  const items = rows.map((c) => {
    const day = shortDate(c.date) + ", " + new Date(c.date).getFullYear();
    const header = day !== previous ? `<div class="day">${esc(day)}</div>` : "";
    previous = day;
    return (
      header +
      `<button class="commit-row ${c.sha === state.selected ? "active" : ""}" data-commit="${esc(c.sha)}" aria-pressed="${c.sha === state.selected}">
      <span class="timeline-dot"></span><span class="commit-content"><b>${esc(c.subject || "(untitled commit)")}</b><small><code>${esc(c.short)}</code><span>·</span>${esc(c.author)}</small></span></button>`
    );
  });
  $("#commits").innerHTML =
    items.join("") +
    (rows.length ? "" : '<p class="quiet side-note">No matching commits</p>') +
    (state.history?.more
      ? '<button class="load-more" data-do="load-more">Load older commits</button>'
      : "");
  $("#history-status").textContent = state.history
    ? num(state.commits.length) + " commits loaded"
    : "No repository open";
}
function applyHistory(data, branch) {
  state.history = data;
  state.branch = branch || data.branch;
  state.commits = data.commits;
  $("#repo-name").textContent = data.name;
  $("#branch").innerHTML = [...new Set([state.branch, ...data.branches])]
    .map(
      (b) =>
        `<option ${b === state.branch ? "selected" : ""} value="${esc(b)}">${esc(b)}</option>`,
    )
    .join("");
  renderHistory();
}
async function openRepo() {
  try {
    const data = await api.open();
    if (!data) return;
    repoEpoch++;
    historyTicket++;
    detailTicket++;
    state.data = null;
    state.selected = "";
    $("#search").value = "";
    applyHistory(data);
    if (data.commits.length) await selectCommit(data.commits[0].sha);
    else {
      $("#main").innerHTML = emptyState(
        "git",
        "No commits yet",
        "Create a commit in this repository to explore its changes.",
      );
      toolbar();
    }
  } catch (e) {
    notice(errorText(e));
  }
}
async function loadHistory(branch, append = false) {
  const token = ++historyTicket;
  try {
    const data = await api.history({
      branch: branch || null,
      skip: append ? state.commits.length : 0,
    });
    if (token !== historyTicket) return;
    if (append) {
      state.history.more = data.more;
      state.commits.push(...data.commits);
      renderHistory();
      return;
    }
    const previous = branch === state.branch ? state.selected : "";
    applyHistory(data, branch);
    if (data.commits.length)
      await selectCommit(
        data.commits.some((c) => c.sha === previous)
          ? previous
          : data.commits[0].sha,
      );
    else {
      state.data = null;
      state.selected = "";
      detailTicket++;
      $("#main").innerHTML = emptyState(
        "git",
        "No commits yet",
        "This branch has no committed changes.",
      );
      toolbar();
    }
  } catch (e) {
    if (token === historyTicket) {
      state.data = null;
      intro(errorText(e));
      notice(errorText(e));
    }
  }
}
async function selectCommit(sha) {
  const token = ++detailTicket;
  state.selected = sha;
  state.data = null;
  state.diff = null;
  state.file = "";
  state.runId = "";
  state.node = "";
  state.graphLimit = 4;
  state.issueDetails = new Map();
  state.filter = "all";
  state.zoom = fitZoom();
  diffTicket++;
  renderHistory();
  toolbar();
  $("#main").innerHTML = emptyState(
    "loader",
    "Reading commit",
    "Loading committed files and relationships…",
  );
  try {
    const data = await api.inspect({ head: sha });
    if (token !== detailTicket) return;
    state.data = data;
    renderMain();
    if (state.tab === "changes" && data.files.length)
      await selectFile(data.files[0].path);
  } catch (e) {
    if (token === detailTicket)
      $("#main").innerHTML = emptyState(
        "risk",
        "Could not read this commit",
        errorText(e),
      );
  }
}
function fitZoom() {
  const width = window.innerWidth;
  const map = width >= 1180 ? width - 292 - 240 - 74 : width - 250 - 64;
  return Math.max(0.56, Math.min(1.18, Math.round((map / 770) * 100) / 100));
}
function stat(label, value, cls, ico) {
  return `<div class="stat"><span>${icon(ico, 14)}${esc(label)}</span><strong class="${cls}">${esc(value)}</strong></div>`;
}
const tabs = [
  ["graph", "Issue graph", "graph"],
  ["changes", "Changes", "diff"],
  ["risks", "Risks", "risk"],
  ["reviews", "Reviews", "shield"],
];
function renderMain() {
  const d = state.data;
  if (!d) return;
  const run = selectedRun();
  const totals = d.files.reduce(
    (v, f) => [v[0] + (f.added || 0), v[1] + (f.deleted || 0)],
    [0, 0],
  );
  const counts = {
    changes: d.files.length,
    risks: d.risks.length,
    reviews: d.runs.length,
  };
  const content =
    state.tab === "graph"
      ? graphView(d, run, state)
      : state.tab === "changes"
        ? changesView(d)
        : state.tab === "risks"
          ? risksView(d)
          : reviewsView(d, run);
  $("#main").innerHTML =
    `<div class="summary"><div class="crumb">${icon("git", 15)} Commit <span>/</span> <code>${esc(d.commit.short)}</code></div>
    <h1 title="${esc(d.commit.subject)}">${esc(d.commit.subject || "(untitled commit)")}</h1>
    <div class="meta"><span class="avatar">${esc(d.commit.author.slice(0, 1).toUpperCase())}</span><b>${esc(d.commit.author)}</b><span>·</span>${esc(new Date(d.commit.date).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }))}</div>
    <div class="stats">${stat("Files changed", num(d.files.length), "", "file")}${stat("Additions", "+" + num(totals[0]), "green", "plus")}${stat("Deletions", "−" + num(totals[1]), "red", "minus")}${stat("Risk signals", num(d.risks.length), "amber", "risk")}</div></div>
    <nav class="tabs" aria-label="Commit views">${tabs.map(([id, label, ico]) => `<button data-tab="${id}" aria-pressed="${state.tab === id}" class="${state.tab === id ? "selected" : ""}">${icon(ico)}${label}${id in counts ? `<small>${counts[id]}</small>` : ""}</button>`).join("")}</nav>
    <section class="content ${state.tab}">${content}</section>`;
  toolbar();
}
function diffMarkup(patch, targetLine, deletedFile) {
  let oldLine,
    newLine,
    matched = false;
  const rows = patch.split("\n").map((line) => {
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
    let kind = "header",
      before = "",
      after = "";
    if (hunk) {
      oldLine = Number(hunk[1]);
      newLine = Number(hunk[2]);
      kind = "hunk";
    } else if (oldLine !== undefined && line.startsWith("+")) {
      kind = "add";
      after = newLine++;
    } else if (oldLine !== undefined && line.startsWith("-")) {
      kind = "del";
      before = oldLine++;
    } else if (oldLine !== undefined && line.startsWith(" ")) {
      kind = "ctx";
      before = oldLine++;
      after = newLine++;
    }
    const marked = targetLine && (deletedFile ? before : after) === targetLine;
    matched ||= Boolean(marked);
    return `<div class="diff-line ${kind} ${marked ? "diff-anchor" : ""}"><span class="gutter">${before}</span><span class="gutter">${after}</span><span>${esc(line) || " "}</span></div>`;
  });
  const note =
    targetLine && !matched
      ? `<div class="pane-note">Line ${Number(targetLine)} is outside this patch preview.</div>`
      : "";
  return note + '<div class="patch">' + rows.join("") + "</div>";
}

function changesView(d) {
  if (!d.files.length)
    return emptyState(
      "diff",
      "No changed files",
      "This commit has the same tree as its comparison base.",
    );
  const file = d.files.find((f) => f.path === state.file);
  const list = d.files
    .map(
      (f) =>
        `<button class="file-row ${f.path === state.file ? "active" : ""}" data-file="${esc(f.path)}"><i class="status-${esc(f.status)}">${esc(f.status)}</i><span title="${esc(f.path)}">${esc(f.path)}</span></button>`,
    )
    .join("");
  let body =
    '<div class="quiet pane-note">Select a file to see its patch.</div>';
  if (file && !state.diff)
    body = '<div class="quiet pane-note">Loading diff…</div>';
  if (state.diff?.error)
    body = `<p class="pane-note red">${esc(state.diff.error)}</p>`;
  if (state.diff?.text !== undefined) {
    body = diffMarkup(state.diff.text, state.anchorLine, file?.status === "D");
    if (state.diff.truncated)
      body += '<div class="pane-note">Preview capped at 96 KB.</div>';
  }
  return `<div class="change-layout"><div class="file-list"><h3>Changed files</h3>${list}</div><div class="diff-pane"><h3>${icon("file")} ${esc(file?.path || "Diff")}${file && file.added !== null ? `<small><em>+${num(file.added)}</em> −${num(file.deleted)}</small>` : ""}</h3>${file?.oldPath ? `<div class="pane-note">Renamed from ${esc(file.oldPath)}</div>` : ""}${body}</div></div>`;
}
async function selectFile(path, line = 0) {
  const file = state.data?.files.find(
    (f) => f.path === path || f.oldPath === path,
  );
  if (!file) return;
  const token = ++diffTicket;
  state.tab = "changes";
  state.file = file.path;
  state.anchorLine = Number(line) || 0;
  state.diff = null;
  renderMain();
  try {
    const result = await api.diff({
      head: state.selected,
      paths: [file.oldPath, file.path].filter(Boolean),
    });
    if (token !== diffTicket) return;
    state.diff = result;
  } catch (e) {
    if (token !== diffTicket) return;
    state.diff = { error: errorText(e) };
  }
  if (state.tab === "changes") {
    renderMain();
    document
      .querySelector(".diff-anchor")
      ?.scrollIntoView({ block: "nearest" });
  }
}
function risksView(d) {
  if (!d.risks.length)
    return emptyState(
      "shield",
      "No risk rules matched",
      "Model checkers can still review this change for bugs.",
    );
  return `<div class="section-head"><h3>Risk signals</h3><p>Rules matched against file names and the committed diff.${d.patchTruncated ? " Diff text was capped at 96 KB." : ""}</p></div><div class="cards">${d.risks.map((r) => `<article class="risk-card"><div>${severity(r.severity)}<h4>${esc(r.label)}</h4></div><p>${r.paths.length ? esc(r.paths.slice(0, 4).join(" · ")) : "Pattern matched in the diff"}${r.paths.length > 4 ? " · +" + (r.paths.length - 4) + " more" : ""}</p><button class="text-btn" data-show-node="${esc("r:" + r.label)}">View connections ${icon("right", 13)}</button></article>`).join("")}</div>`;
}
function reviewsView(d, r) {
  if (!r)
    return emptyState(
      "shield",
      running.has(key()) ? "Review in progress" : "No reviews for this commit",
      running.has(key())
        ? "The checkers are reviewing this revision. Results will appear here."
        : "Run your configured checkers to see findings, model attribution, and any provider errors.",
      running.has(key())
        ? ""
        : button("Run review", "run", { primary: true, icon: "play" }),
    );
  const completed = r.checkers.filter((c) => c.status === "completed").length;
  return `<div class="section-head review-head"><div><h3>Review results</h3><p>${completed} of ${r.checkers.length} checkers completed · ${r.findings.length} findings${r.truncated ? " · Diff coverage limited" : ""}</p></div>
    <select id="review-pick" aria-label="Review run">${d.runs.map((x) => `<option value="${esc(x.id)}" ${r.id === x.id ? "selected" : ""}>${esc(new Date(x.created).toLocaleString())} · ${esc(x.status)}</option>`).join("")}</select></div>
    <div class="checker-results">${r.checkers.map((c) => `<article><span class="${c.status === "completed" ? "green" : "amber"}">${icon(c.status === "completed" ? "check" : "risk")}</span><div><b>${esc(c.name)}</b><code>${esc(c.model || "CLI default")}</code><p>${esc(c.error || c.findings.length + " findings")}</p></div></article>`).join("")}</div>
    <div class="cards">${r.findings.map((f, i) => `<article class="finding-card">${severity(f.severity)}<h4>${esc(f.title)}</h4><p>${esc(f.detail)}</p><small>${esc(f.checkers.join(" · "))}</small><div><button class="text-btn" data-file="${esc(f.file)}" data-line="${Number(f.line)}">${esc(f.file)}:${f.line}</button><button class="text-btn" data-show-node="a:${i}">View connections ${icon("right", 13)}</button></div></article>`).join("") || `<p class="pane-note">${r.status === "complete" ? "No findings reported." : "No findings from the completed checker responses. Coverage is incomplete."}</p>`}</div>`;
}
async function runReview() {
  if (!state.data || running.has(key())) return;
  const runKey = key(),
    sha = state.selected;
  running.add(runKey);
  state.tab = "reviews";
  renderMain();
  try {
    const receipt = await api.run({ head: sha });
    if (key() === runKey && state.data) {
      state.data.runs = [
        receipt,
        ...state.data.runs.filter((r) => r.id !== receipt.id),
      ];
      state.runId = receipt.id;
      renderMain();
    } else notice("Review finished for " + sha.slice(0, 8) + ".");
  } catch (e) {
    notice(errorText(e));
  } finally {
    running.delete(runKey);
    if (key() === runKey) renderMain();
  }
}

function editorRows() {
  return [...document.querySelectorAll(".checker-editor")].map((el) =>
    Object.fromEntries(
      [...el.querySelectorAll("[data-field]")].map((input) => [
        input.dataset.field,
        input.value.trim(),
      ]),
    ),
  );
}
function editRows(rows) {
  const options = state.settings.providers;
  $("#checker-editors").innerHTML = rows
    .map((row, i) => {
      const cli = ["codex", "claude"].includes(row.provider);
      const input = (key, label, placeholder = "") =>
        `<label>${label}<input data-field="${key}" value="${esc(row[key])}" placeholder="${esc(placeholder)}" autocomplete="off"></label>`;
      return `<fieldset class="checker-editor"><legend>Checker ${i + 1}</legend><button type="button" class="remove-checker icon-btn" data-remove="${i}" aria-label="Remove checker ${i + 1}" ${rows.length === 1 ? "disabled" : ""}>${icon("trash", 15)}</button>
      ${input("name", "Name")}<label>Provider<select data-field="provider" data-provider="${i}">${Object.entries(
        options,
      )
        .map(
          ([id, p]) =>
            `<option value="${id}" ${row.provider === id ? "selected" : ""}>${esc(p.label)}</option>`,
        )
        .join("")}</select></label>
      ${input("model", "Model", cli ? "CLI default" : "Model ID")}${input("focus", "Review focus")}
      ${cli ? "" : input("endpoint", "API base URL") + input("keyEnv", "API key environment variable", "Optional for local models")}</fieldset>`;
    })
    .join("");
  $("#add-checker").disabled = rows.length >= 12;
}
async function settingsDialog() {
  try {
    const settings = await api.settings();
    state.settings = settings;
    editRows(settings.checkers);
    $("#settings-error").textContent = "";
    $("#settings-dialog").showModal();
    toolbar();
  } catch (e) {
    notice(errorText(e));
  }
}
$("#settings-btn").onclick = settingsDialog;
$("#close-settings").onclick = () => $("#settings-dialog").close();
$("#add-checker").onclick = () => {
  const rows = editorRows();
  const template = state.settings.providers.ollama;
  let number = rows.length + 1,
    name = "Checker " + number;
  while (rows.some((r) => r.name === name)) name = "Checker " + ++number;
  editRows([...rows, { ...template, name }]);
  $("#checker-editors").lastElementChild.scrollIntoView({ block: "nearest" });
};
$("#checker-editors").addEventListener("click", (event) => {
  const remove = event.target.closest("[data-remove]");
  if (!remove) return;
  const rows = editorRows();
  rows.splice(Number(remove.dataset.remove), 1);
  editRows(rows);
});
$("#checker-editors").addEventListener("change", (event) => {
  if (!event.target.matches("[data-provider]")) return;
  const rows = editorRows(),
    i = Number(event.target.dataset.provider),
    p = state.settings.providers[event.target.value];
  const match = Object.values(state.settings.providers).some(
    (option) => option.name === rows[i].name,
  );
  let name = match ? p.name : rows[i].name;
  if (rows.some((row, index) => index !== i && row.name === name))
    name += " " + (i + 1);
  rows[i] = { ...p, focus: rows[i].focus, name };
  editRows(rows);
});
$("#settings-form").onsubmit = async (event) => {
  event.preventDefault();
  try {
    state.settings.checkers = await api.saveSettings({
      checkers: editorRows(),
    });
    $("#settings-dialog").close();
    toolbar();
    notice("Checker settings saved.");
  } catch (e) {
    $("#settings-error").textContent = errorText(e);
  }
};
function graphFocus(id) {
  state.node = id;
  state.tab = "graph";
  state.filter = "all";
  renderMain();
}
$("#main").addEventListener("change", (event) => {
  if (event.target.id === "graph-filter") {
    state.filter = event.target.value;
    state.graphLimit = 4;
    state.node = "";
    renderMain();
  }
  if (event.target.id === "review-pick") {
    state.runId = event.target.value;
    state.node = "";
    renderMain();
  }
});
document.addEventListener("click", async (event) => {
  const target = event.target.closest("button");
  if (!target || target.disabled) return;
  if (target.dataset.commit) return selectCommit(target.dataset.commit);
  if (target.dataset.tab) {
    state.tab = target.dataset.tab;
    if (state.tab === "changes" && !state.file && state.data.files.length)
      return selectFile(state.data.files[0].path);
    renderMain();
    return;
  }
  if (target.dataset.file)
    return selectFile(target.dataset.file, target.dataset.line);
  if (target.dataset.showNode) return graphFocus(target.dataset.showNode);
  if (target.dataset.node) {
    state.node = target.dataset.node;
    renderMain();
    return;
  }
  const action = target.dataset.do;
  if (!action) return;
  if (action === "open") return openRepo();
  if (action === "load-more") return loadHistory(state.branch, true);
  if (action === "run") return runReview();
  if (action === "more-nodes") {
    state.graphLimit += 12;
    renderMain();
    return;
  }
  if (action.startsWith("zoom-")) {
    state.zoom =
      action === "zoom-reset"
        ? fitZoom()
        : Math.max(
            0.35,
            Math.min(
              2,
              Math.round(
                (state.zoom + (action === "zoom-plus" ? 0.15 : -0.15)) * 100,
              ) / 100,
            ),
          );
    renderMain();
    return;
  }
  if (!state.data) return;
  const g = makeGraph(state.data, selectedRun(), state.issueDetails),
    n = g.nodes.get(state.node) || g.nodes.get(g.commit);
  if (action === "node-diff" && n.path) return selectFile(n.path, n.line);
  if (action === "related-commit" && n.sha) return selectCommit(n.sha);
  if (action === "open-issue" && n.ref)
    return api.openIssue(n.ref).catch((e) => notice(errorText(e)));
  if (action === "load-issue" && n.ref) {
    const token = detailTicket;
    target.disabled = true;
    target.textContent = "Loading…";
    try {
      const d = await api.issue({ repo: n.ref.repo, number: n.ref.number });
      if (token === detailTicket) {
        state.issueDetails.set(n.ref.id, d);
        renderMain();
      }
    } catch (e) {
      if (token === detailTicket) {
        notice(errorText(e));
        renderMain();
      }
    }
  }
});
$("#open").onclick = openRepo;
$("#run-btn").onclick = runReview;
$("#search").oninput = renderHistory;
$("#branch").onchange = () => loadHistory($("#branch").value);
$("#refresh").onclick = () =>
  state.history ? loadHistory(state.branch) : openRepo();
for (const e of document.querySelectorAll("[data-icon]"))
  e.innerHTML = icon(e.dataset.icon, e.dataset.icon === "bug" ? 23 : 16);
(async () => {
  intro();
  try {
    state.settings = await api.settings();
    toolbar();
  } catch (e) {
    notice(errorText(e));
  }
  try {
    if (await api.initial()) await loadHistory();
  } catch (e) {
    notice(errorText(e));
  }
})();
