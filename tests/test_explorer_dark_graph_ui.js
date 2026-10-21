// v6: dark theme + legible diagram without labels obscuring nodes.
'use strict';
const fs = require('node:fs');
const assert = require('node:assert/strict');
const path = require('node:path');
const root = path.resolve(__dirname,'..');
const js = fs.readFileSync(path.join(root,'src/sigma/web/static/app.js'),'utf8');
const css = fs.readFileSync(path.join(root,'src/sigma/web/static/style.css'),'utf8');
assert.match(css,/sigma-explorer-dark-graph-fix-20261019-v6/);
assert.match(js,/selector: 'node.focus', style: \{'width': 28, 'height': 28/);
assert.match(js,/selector: 'node.labelled', style: [^\n]*'text-background-opacity': 0/);
assert.match(js,/'text-valign': 'bottom', 'text-halign': 'center', 'text-margin-y': 7/);
assert(!js.includes("'text-background-opacity': 0.93"), 'No opaque label backgrounds');
assert.match(js,/paint\('partition-linked-fill', 'fill-opacity', network \?/);
assert.match(js,/step => fadeByStep\(dark \? 0\.17 : 0\.105, step\)/);
assert.match(js,/const face = themeMode === 'dark' \? 'dark_center_icon'/);
assert.match(js,/darkLinkedIconByType\.set\(key, darkLinkedName\)/);
assert.match(js,/applyTheme\(themeMode\); \/\/ Restore theme-aware paints/);
console.log('PASS: graph labels outside nodes, no white backgrounds, dark map paints and dark triangle artwork.');
