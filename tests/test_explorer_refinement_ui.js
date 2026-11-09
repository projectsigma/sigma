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
for (const heading of ['Selected Place','Cluster network','Linked clusters','Most central clusters']) {
  assert(html.includes(`<h2>${heading} <span class="control-help`), `Help missing for ${heading}`);
}
for (const id of ['graph-fit','theater-toggle','zoom-network','sectors-all','sectors-none']) {
  assert.match(html, new RegExp(`id="${id}"[^>]*>[\\s\\S]*?<\\/button>\\s*<span class="control-help`), `Button help missing: ${id}`);
}
assert.match(js, /function displayedSectorStrength\(\)/);
// Sector ordering is now user-controlled (Industry / Code / Places).
assert.match(js, /const sectorSortState = \{key: 'code', descending: false\}/);
assert.match(js, /sectorSortState\.key === 'name'/);
assert.match(js, /sectorSortState\.key === 'places'/);
assert.match(js, /compareSectorCodes\(a,b\)/);
// Coefficient strengths remain available in sector detail tooltips.
assert.match(js, /globalSectorStrength\.get\(s\.code\)/);
// Refresh must re-rank sectors only after confirming this generation is current.
assert.match(js, /const finish = \(\) => \{\s*if \(epoch !== refreshEpoch\) return;\s*sigmaPerf\('sectorPanel', renderSectors\);/);
// Expensive reranking and graph work are deferred until after the next paint.
assert.match(js, /requestAnimationFrame\(\(\) => setTimeout\(finish, 0\)\);/);
assert.match(js, /recordSectorStrength\(nodeIndex\.get\(e\.from\), e\.coefficient\)/);
assert.match(js, /map\.setFilter\('native-establishments', filter\)/);
assert.match(js, /if \(meta\.native_points_v7\) syncNativePointLayer\(\)/);
assert.match(js, /'line-opacity', ids \? 0\.18 : 0\.38/);
assert.match(js, /function initializeHelp\(\)/);
assert.match(js, /statHelp\[label\]/);
assert.match(html, /id="central-limit"/);
assert.match(html, /<option value="10" selected>10<\/option>/);
assert.match(html, /<option value="20">20<\/option>/);
assert.match(html, /<option value="50">50<\/option>/);
assert.match(html, /id="central-sector-search"/);
assert.match(js, /const centralTableState = \{limit: 10, key: 'centrality', descending: true\}/);
assert.match(js, /\.slice\(0, centralTableState\.limit\)\.map\(\(n, i\) => \(\{n, rank: i \+ 1\}\)\)/);
assert.match(js, /\['rank', 'Rank'\], \['cluster', 'Cluster'\], \['code', 'Code'\]/);
assert.match(js, /\['centrality', 'Centrality'\], \['members', 'Places'\]/);
assert.match(js, /aria-sort/);
assert(js.includes("const centralHelpKeys = {cluster: 'central-cluster', centrality: 'centrality'"));
assert(js.includes('heading.append(helpIcon(label, columnHelp[centralHelpKeys[key]]))'));
assert.match(js, /function syncPlacesVisibility\(\)/);
assert.match(js, /pointLayerDesired\.set\(layer, !!shown\)/);
assert.match(js, /const all = \$\('show-centers'\)\.checked;/);
assert.match(html, /Find a Place/);
assert.match(html, /Selected Place/);
assert.match(html, /Show unclustered places in sectors without clusters/);
assert.match(js, /Show unclustered places in scored sectors/);
assert.match(js, /thHelp\('→ TC', 'out-a'\)/);
assert.match(js, /thHelp\('← TC', 'in-a'\)/);
assert.match(js, /stat\('Places in cluster'/);
assert.match(js, /if \(linkedBox\.checked && !\$\('show-places'\)\.checked\)/);
assert.match(css, /#central \.central-table \{width:100%; max-width:100%; table-layout:auto;/);
assert.match(css, /#central \.central-table td:nth-child\(2\) \{max-width:0; overflow:hidden;/);
assert.match(css, /#central \.central-table td:first-child \{text-align:center;/);
assert.match(js, /function preferPlacesForSelection\(\)/);
assert.match(css, /sigma-explorer-refinement-20261019-v2/);
console.log('PASS: explicit sector sorting, coefficient help, context fade, right-panel explanations');
