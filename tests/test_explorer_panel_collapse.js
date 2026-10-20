// SIGMA Explorer right panel: native disclosure accessibility and defaults.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const dir = path.join(__dirname, '../src/sigma/web/static');
const html = fs.readFileSync(path.join(dir, 'index.html'), 'utf8');
const css = fs.readFileSync(path.join(dir, 'style.css'), 'utf8');
const js = fs.readFileSync(path.join(dir, 'app.js'), 'utf8');
const ci = fs.readFileSync(path.join(__dirname, '../.github/workflows/explorer_js.yml'), 'utf8');
const specs = [
  ['finder-section', false, 'Find an establishment', 'finder-query'],
  ['selection', true, 'Selected location', 'place-name'],
  ['graph-section', true, 'Cluster network', 'network'],
  ['connections-section', true, 'Linked clusters', 'connections'],
  ['central-section', true, 'Most central clusters', 'central'],
];
for (const [cls, open, heading, bodyId] of specs) {
  const start = html.indexOf(`<section class="${cls}"`);
  assert(start >= 0, `Missing ${cls}`);
  const end = html.indexOf('</section>', start);
  assert(end > start, `Unclosed ${cls}`);
  const fragment = html.slice(start, end);
  const details = fragment.match(/<details class="sidebar-disclosure"( open)?>/);
  assert(details, `Missing native disclosure in ${cls}`);
  assert.equal(!!details[1], open, `${cls}: unexpected initial expanded state`);
  assert(fragment.includes('<summary class="section-head">'), `${cls}: heading should toggle disclosure`);
  assert(fragment.includes(heading), `${cls}: heading missing`);
  assert(fragment.includes('<div class="sidebar-disclosure-body">'), `${cls}: body wrapper missing`);
  assert(fragment.includes(`id="${bodyId}"`), `${cls}: body content lost`);
  assert(fragment.includes('</div>\n    </details>'), `${cls}: disclosure closure missing`);
}
assert(css.includes('sigma-explorer-collapsible-panels-20261020-v1'));
assert(css.includes('.sidebar-disclosure[open] > summary.section-head::before'));
assert(css.includes('html[data-theme="dark"] .side .sidebar-disclosure'));
assert.match(js, /querySelector\('\.graph-section \.sidebar-disclosure'\)\.addEventListener\('toggle'/);
assert.match(js, /cy\.resize\(\);\s*if \(network\) cy\.fit/);
assert.match(js, /finderPanel\.open = false;/);
assert.match(ci, /node tests\/test_explorer_panel_collapse\.js/);
console.log('PASS: finder starts collapsed; four other sections collapse independently; graph expands by default and resizes on reopening.');
