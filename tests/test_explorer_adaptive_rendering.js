/* Behavioral regression: hidden and unlinked establishment data never reach MapLibre. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/sigma/web/static/app.js'), 'utf8');
function extract(name) {
  const start = source.indexOf(`function ${name}(`);
  assert(start >= 0, `Missing function ${name}`);
  const opening = source.indexOf('{', start);
  let depth = 0;
  for (let i = opening; i < source.length; i++) {
    if (source[i] === '{') depth++;
    if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw Error(`Unclosed function ${name}`);
}
const js = ['inVisibleNetwork', 'boundSummaryGlyphs', 'screenBoundExactPoints', 'syncRenderedEstablishments'].map(extract).join('\n');
function feature(id, type = 'A', count = 1, lon = 120, lat = 14) {
  return {type: 'Feature', properties: {node_id: id, type, original_type: type, count},
    geometry: {type: 'Point', coordinates: [lon, lat]}};
}
const output = {};
const ctx = {
  hidden: new Set(['B']),
  sigmaOriginalAllowed: () => true,
  selection: {id: 'n1'}, nodeIndex: new Map([['n1', {}]]),
  network: {ring: new Map([['n1', 0], ['n2', 1]])},
  map: {getSource: () => ({}), getBounds: () => ({contains: () => true}), project: coords => ({x: coords[0] * 200, y: coords[1] * 200})},
  visiblePointGroups: [{features: [feature('n1'), feature('n3'), feature('n2', 'B')]}],
  visibleAggregateFeatures: [feature('n1'), feature('n3'), feature('n2', 'B')],
  sectors: new Map(), meta: {aggregate_budget: 100},
  isNum: n => Number.isFinite(n),
  sigmaOriginalType: p => p.original_type,
  setData: (name, data) => { output[name] = data; },
  syncUnscoredOverlay: () => {}, unscoredCandidates: [], unscoredRenderedKey: null,
};
vm.createContext(ctx);
vm.runInContext(`${js}\nsyncRenderedEstablishments();`, ctx);
assert.deepEqual(Array.from(output.points.features, f => f.properties.node_id), ['n1']);
assert.deepEqual(Array.from(output.aggregates.features, f => f.properties.node_id), ['n1']);
ctx.hidden = new Set();
ctx.selection = null;
ctx.network = null;
ctx.visibleAggregateFeatures = Array.from({length: 5000}, (_, i) =>
  feature('n' + i, 'A', i % 7 + 1, 120 + i * 0.00001, 14 + i * 0.00001));
vm.runInContext('syncRenderedEstablishments();', ctx);
assert(output.aggregates.features.length <= 100, 'screen aggregate count must be bounded');
const sum = arr => arr.reduce((acc, f) => acc + f.properties.count, 0);
assert.equal(sum(output.aggregates.features), sum(ctx.visibleAggregateFeatures), 'count mass must be preserved');
console.log('PASS: out-of-network filtering and bounded, count-preserving summary glyphs');
