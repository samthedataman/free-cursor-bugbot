"use strict";
const paths = {
  bug: '<rect x="6.5" y="7" width="11" height="13" rx="5"/><path d="M9 7V5a3 3 0 0 1 6 0v2M12 10v7M4 10l3 1m-3 3h3m-3 5 3-2m13-7-3 1m3 3h-3m3 5-3-2"/>',
  folder:
    '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  chevrons: '<path d="m8 9 4-4 4 4m-8 6 4 4 4-4"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  right: '<path d="m9 6 6 6-6 6"/>',
  branch:
    '<circle cx="6" cy="5" r="2.5"/><circle cx="6" cy="19" r="2.5"/><circle cx="18" cy="6" r="2.5"/><path d="M6 8v8m0-2c7 0 12 0 12-5"/>',
  git: '<path d="M2 12h6m8 0h6"/><circle cx="12" cy="12" r="4"/>',
  search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
  graph:
    '<rect x="2" y="9" width="5" height="6" rx="1"/><rect x="17" y="2" width="5" height="6" rx="1"/><rect x="17" y="16" width="5" height="6" rx="1"/><path d="M7 12h3c3 0 1-7 5-7h2m-7 7c3 0 1 7 5 7h2"/>',
  file: '<path d="M5 3h9l5 5v13H5zM14 3v6h5"/>',
  diff: '<path d="M5 3h9l5 5v13H5zM8 12h5m-2.5-2.5v5m-2.5 3h5"/>',
  risk: '<path d="m11 4-9 15a1 1 0 0 0 1 1h18a1 1 0 0 0 1-1L13 4a1.2 1.2 0 0 0-2 0zM12 9v5m0 3h.01"/>',
  issue:
    '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="2" fill="currentColor" stroke="none"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  shield:
    '<path d="m12 2 8 3v6c0 5-4 8-8 11-4-3-8-6-8-11V5z"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
  sliders:
    '<path d="M3 7h7m4 0h7M3 17h3m4 0h11"/><circle cx="12" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>',
  play: '<path d="m7 4 13 8-13 8z"/>',
  x: '<path d="m6 6 12 12M18 6 6 18"/>',
  refresh: '<path d="M20 10a8 8 0 1 0 0 6M20 4v6h-6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  fit: '<path d="M4 9V4h5m6 0h5v5m0 6v5h-5m-6 0H4v-5"/>',
  globe:
    '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c5 5 5 13 0 18-5-5-5-13 0-18"/>',
  link: '<path d="m10 14 4-4m-5 1 3-3 3-3a4 4 0 0 1 6 6l-3 3m-3-1-6 6a4 4 0 0 1-6-6l3-3"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
  external: '<path d="M13 4h7v7m0-7L10 14M10 5H4v15h15v-6"/>',
  terminal:
    '<rect x="2" y="4" width="20" height="16" rx="3"/><path d="m6 9 3 3-3 3m6 0h5"/>',
  stack: '<path d="m12 3 9 5-9 5-9-5zM3 12l9 5 9-5M3 16l9 5 9-5"/>',
  trash: '<path d="M3 6h18M8 6V4h8v2M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',
  loader: '<path d="M20 12a8 8 0 1 1-8-8"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/>',
};
function icon(name, size = 16) {
  return (
    '<svg aria-hidden="true" width="' +
    size +
    '" height="' +
    size +
    '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">' +
    (paths[name] || "") +
    "</svg>"
  );
}
function esc(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
}
const $ = (selector) => document.querySelector(selector);
const num = (value) => Number(value || 0).toLocaleString();
const shortDate = (date) =>
  new Date(date).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
function emptyState(symbol, title, body, action = "") {
  return (
    '<div class="empty"><div class="empty-icon">' +
    icon(symbol, 28) +
    "</div><h2>" +
    esc(title) +
    "</h2><p>" +
    esc(body) +
    "</p>" +
    action +
    "</div>"
  );
}
function button(label, action, opts = {}) {
  return (
    '<button class="' +
    (opts.primary ? "primary" : "secondary") +
    '" data-do="' +
    esc(action) +
    '">' +
    (opts.icon ? icon(opts.icon) : "") +
    esc(label) +
    "</button>"
  );
}
