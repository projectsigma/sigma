// SIGMA Explorer second overlay: safe structural regression checks only.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = path.join(__dirname, '../src/sigma/web/static');
const html = fs.readFileSync(path.join(base,'index.html'),'utf8');
const js = fs.readFileSync(path.join(base,'app.js'),'utf8');
const css = fs.readFileSync(path.join(base,'style.css'),'utf8');
assert.match(html, /sigma-explorer-refinement-20261019-v2/);
for (const heading of ['Selected location','Cluster network','Linked clusters','Most central clusters']) {
  assert(html.includes(`<h2>${heading} <span class="control-help`), `Help missing for ${heading}`);
}
for (const id of ['graph-fit','theater-toggle','zoom-network','sectors-all','sectors-none']) {
  assert.match(html, new RegExp(`id="${id}"[^>]*>[\\s\\S]*?<\\/button>\\s*<span class="control-help`), `Button help missing: ${id}`);
}
assert.match(js, /function displayedSectorStrength\(\)/);
assert.match(js, /globalSectorStrength\.get\(a\.code\)/);
assert.match(js, /renderSectors\(\);  \/\/ Re-rank sectors/);
assert.match(js, /recordSectorStrength\(nodeIndex\.get\(e\.from\), e\.coefficient\)/);
assert.match(js, /'circle-opacity', ids \?\s*networkDepthOpacity\('node_id', 0\.96, step => fadeByStep\(0\.90, step\), 0\.025\)/);
assert.match(js, /'line-opacity', ids \? 0\.18 : 0\.38/);
assert.match(js, /function initializeHelp\(\)/);
assert.match(js, /statHelp\[label\]/);
assert.match(js, /thHelp\('→ a', 'out-a'\)/);
assert.match(css, /sigma-explorer-refinement-20261019-v2/);
console.log('PASS: contextual sector ordering, coefficient labels, context fade, right-panel explanations');
