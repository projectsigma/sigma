// SIGMA Explorer final v3 overlay: UI defaults, custom depth, sorting and sizes.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname,'..');
const base = path.join(root, 'src/sigma/web/static');
const html = fs.readFileSync(path.join(base,'index.html'),'utf8');
const js = fs.readFileSync(path.join(base,'app.js'),'utf8');
const css = fs.readFileSync(path.join(base,'style.css'),'utf8');
assert.match(html, /sigma-explorer-final-20261019-v3/);
assert.match(html, /<option value="1" selected>Direct links<\/option>/);
assert.match(html, /<option value="2">Two steps<\/option>/);
assert.match(html, /<option value="3">Three steps<\/option>/);
assert.match(html, /<option value="custom">Custom…<\/option>/);
assert.match(html, /id="depth-custom"[^>]*min="1" max="20"[^>]*hidden disabled/);
assert.match(js, /depthCustom\.addEventListener\('input'/);
assert.match(js, /Number\.isSafeInteger\(value\) && value >= 1 && value <= 20/);
assert.match(js, /const sectorSortState = \{key: 'code', descending: false\}/);
assert.match(js, /else if \(sectorSortState\.key === 'places'\) n = a\.points - b\.points/);
assert.match(js, /else n = compareSectorCodes\(a,b\)/);
assert.match(js, /function io240Rank\(s\)/);
// The coefficient remains available in the row's explanation, not as a separate column.
assert.match(js, /const score = network && linked\.has\(s\.code\)/);
assert.match(js, /\$\{description\}: \$\{isNum\(score\) \? fmtCoef\(score\) : 'not available'\}/);
assert(!js.includes('`a ${fmtCoef(score)}`'), 'Sector rows must not display unexplained "a"');
assert.match(js, /Circle AREA, not radius, is proportional to normalized SIGMA score/);
// Scored markers stay area-scaled but use initial-fit-relative zoom stops.
assert.match(js, /const scoredPointRadius = radiusAtFit\(\[/);
assert.match(js, /\[0, scoreRadius\(1\.8, 5\.5\)\]/);
assert.match(js, /\[2, scoreRadius\(2\.4, 7\.7\)\]/);
assert.match(js, /\[4, scoreRadius\(2\.8, 9\.2\)\]/);
assert.match(css, /sigma-explorer-final-20261019-v3/);
assert.match(js, /function updateCenterVisibility\(\)/);
// Unclustered hollow outlines must have the same *external footprint* as
// minimum-value scored points, not a size inferred from visual_min_score.
assert.match(js, /const unclusteredPointRadius = radiusAtFit\(\[\s*\[-3, 0\.775\], \[-1, 1\.175\], \[0, 1\.375\],\s*\[2, 1\.975\], \[4, 2\.375\]\]\);/);
assert.match(js, /'circle-stroke-width': 1\.2, 'circle-stroke-opacity': 0\.95/);
console.log('PASS: custom depth, explicit hierarchical sorting, coefficient help, area-scaled SIGMA points.');
