// Regression: map-layer opacity follows 1/sqrt(BFS step), as route widths do.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const src = fs.readFileSync(path.resolve(__dirname, '../src/sigma/web/static/app.js'), 'utf8');
const beginning = src.indexOf('  // SIGMA Explorer depth-based map opacity v1');
const ending = src.indexOf('  function applyEmphasis()', beginning);
assert(beginning > 0 && ending > beginning, 'depth-opacity helper still present');
const program = src.slice(beginning, ending);
const fakeNetwork = {focus: 'selected', ring: new Map([
  ['selected', 0], ['near-a', 1], ['near-b', 1], ['two', 2], ['three', 3],
  ['four', 4], ['five', 5], ['twenty', 20]
])};
const {fadeByStep, networkDepthOpacity, voronoiOpacity} = new Function('network',
  `${program}\nreturn {fadeByStep, networkDepthOpacity, voronoiOpacity};`)(fakeNetwork);
function valueFor(expr, id) {
  assert.equal(expr[0], 'match');
  assert.deepEqual(expr[1][0], 'get');
  for (let i = 2; i < expr.length - 1; i += 2) {
    const key = expr[i];
    if (Array.isArray(key) ? key.includes(id) : key === id) return expr[i + 1];
  }
  return expr.at(-1);
}
function approx(a, b, label) {
  assert(Math.abs(a - b) <= 1e-6, `${label}: ${a} != ${b}`);
}
function checkProgression(label, base, column, property, focusOpacity, outside) {
  const expr = networkDepthOpacity(property, focusOpacity,
    step => fadeByStep(base, step), outside);
  approx(valueFor(expr, 'selected'), focusOpacity, `${label} focus`);
  approx(valueFor(expr, 'other'), outside, `${label} context`);
  approx(valueFor(expr, 'near-a'), base, `${label} ring 1`);
  assert.equal(valueFor(expr, 'near-a'), valueFor(expr, 'near-b'));
  for (let step = 2; step <= 5; step++) {
    const preceding = valueFor(expr, ['near-a', 'two', 'three', 'four', 'five'][step-2]);
    const current = valueFor(expr, ['near-a', 'two', 'three', 'four', 'five'][step-1]);
    approx(current, base / Math.sqrt(step), `${label} ring ${step}`);
    assert(current < preceding, `${label}: strictly decreasing`);
  }
  approx(valueFor(expr, 'twenty'), Number((base / Math.sqrt(20)).toFixed(6)), `${label} ring 20`);
  assert(valueFor(expr, 'twenty') < valueFor(expr, 'five'), `${label}: no artificial opacity floor`);
  return expr;
}
const pointExpr = checkProgression('establishment fill', 0.90, 'circle-opacity', 'node_id', 0.96, 0.025);
checkProgression('establishment stroke', 1, 'circle-stroke-opacity', 'node_id', 1, 0.025);
checkProgression('cluster triangle', 1, 'icon-opacity', 'id', 0, 0.16);
// Selected-network Voronoi fills use a deliberately steeper 1/4-per-step fade,
// unlike the original inverse-sqrt center and road rendering.
for (const [theme, base] of [['light', 0.18], ['dark', 0.16]]) {
  const expr = networkDepthOpacity('node_id', 0,
    step => voronoiOpacity(base, step), 0);
  approx(valueFor(expr, 'selected'), 0, `${theme} Voronoi focus is separate`);
  approx(valueFor(expr, 'other'), 0, `${theme} unrelated polygon`);
  for (let step = 1; step <= 5; step++) {
    const id = ['near-a','two','three','four','five'][step-1];
    approx(valueFor(expr, id), Number((base * Math.pow(0.25, step - 1)).toFixed(6)),
      `${theme} Voronoi step ${step}`);
  }
}
assert.match(src, /visibility\('partition-linked-line', false\)/);
// Linked partition boundaries remain hidden; only the selected focus gets an outline.
assert.match(src, /const foreground = mode === 'network' && !!network/);
assert.match(src, /visibility\('partition-focus-line', foreground\)/);
assert.match(src, /map\.setFilter\('partition-focus-line', focus\)/);
approx(valueFor(pointExpr, 'two'), Number((0.90 / Math.sqrt(2)).toFixed(6)), 'ring 2 establishment opacity');
approx(valueFor(pointExpr, 'three'), Number((0.90 / Math.sqrt(3)).toFixed(6)), 'ring 3 establishment opacity');
approx(valueFor(pointExpr, 'five'), Number((0.90 / Math.sqrt(5)).toFixed(6)), 'ring 5 establishment opacity');
assert.equal(new Function('network', `${program}\nreturn networkDepthOpacity('id',1,()=>0.9,0.78);`)(null), 0.78);
assert.match(src, /function fadeByStep\(base, step\)/);
assert.match(src, /base \/ Math\.sqrt\(Math\.max\(1, step\)\)/);
assert.match(src, /'circle-opacity', ids \?\s*networkDepthOpacity\('node_id', 0\.96, step => fadeByStep\(0\.90, step\)/);
assert.match(src, /'circle-stroke-opacity', ids \?\s*networkDepthOpacity\('node_id', 1, step => fadeByStep\(1, step\)/);
assert.match(src, /'icon-opacity', ids \?\s*networkDepthOpacity\('id', 0, step => fadeByStep\(1, step\)/);
assert.match(src, /paint\('partition-linked-fill', 'fill-opacity', network \?\s*networkDepthOpacity/);
assert.match(src, /paint\('partition-linked-line', 'line-opacity', network \?\s*networkDepthOpacity/);
assert.match(src, /paint\('partition-focus-fill', 'fill-opacity', dark \? 0\.24 : 0\.30\)/);
assert.match(src, /networkDepthOpacity\('node_id', 0, step => voronoiOpacity\(dark \? 0\.16 : 0\.18, step\), 0\)/);
assert(src.includes('applyTheme(themeMode); // Restore theme-aware paints after each selection refresh.'));
assert(!src.includes('0.94, 0.42'), 'Previous weak fade must be removed.');
// Network road routes already shrink with depth; this patch must not change them.
assert.match(src, /const width = \(a, b, step\) => \['\*', Math\.max\(0\.26, 1 \/ Math\.sqrt\(step\)\)/);
assert.match(src, /const routeDim = step => Math\.max\(0\.18, 0\.86 \/ Math\.sqrt\(step\)\)/);
const roadScale = step => Math.max(0.26, 1 / Math.sqrt(step));
approx(roadScale(1), 1, 'road direct factor');
approx(roadScale(2), 1 / Math.sqrt(2), 'road step 2 factor');
approx(roadScale(5), 1 / Math.sqrt(5), 'road step 5 factor');
approx(roadScale(20), 0.26, 'road lower width bound');
console.log('PASS: inverse-square-root BFS fade; establishments, triangles, polygons, themes, focus and road scaling.');
