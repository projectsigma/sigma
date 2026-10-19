// SIGMA Explorer toolbar regression: behavior/markup contracts, no extra deps.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, 'src/sigma/web/static', name), 'utf8');
const html = read('index.html');
const js = read('app.js');
const css = read('style.css');
assert.match(html, /id="show-centers"(?![^>]*\bchecked\b)/, 'Center checkbox defaults off');
assert.match(html, /class="toolbar-center-triangle"/, 'Triangle marker next to center toggle');
assert.match(html, /id="top-custom"[^>]*type="number"[^>]*min="1"[^>]*max="10000"/, 'Custom integer link limit');
assert.match(html, /<option value="custom">Custom…<\/option>/, 'Custom choice in dropdown');
assert.match(html, /projectsigma\.github\.io\/sigma\/content\/intro\/index\.html/, 'Documentation link');
for (const id of ['partitions','show-centers','show-roads','direction','depth','top','reset']) {
  assert.match(html, new RegExp('Help: ' + (id==='show-centers' ? 'Cluster centers' : ({'show-roads':'Roads', 'direction':'Links', 'depth':'Depth', 'top':'Strongest links', 'reset':'Clear selection'}[id] || 'Partitions'))), id + ' help');
}
assert.match(js, /function updateCenterVisibility\(\)/, 'Selection-sensitive center rendering');
assert.match(js, /visibility\('centers', all \|\| ids\.length > 0\)/, 'Selected network remains visible with checkbox off');
assert.match(js, /map\.setFilter\('centers', all \? notHidden\(\) :/, 'Only selected network centers when off');
assert.match(js, /map\.setFilter\('selected-center', notHidden\(\)\)/, 'Selected focus respects sector visibility');
assert.match(js, /Number\.isSafeInteger\(value\)/, 'Reject invalid custom top N');
assert.match(js, /topCustom\.addEventListener\('input'/, 'Custom top N live updates');
assert.match(css, /sigma-explorer-toolbar-20261019-v1/, 'Tooltip style installed');
console.log('PASS: toolbar tooltip, default center visibility, network-only triangles, custom top-N, documentation.');
