// SIGMA: execute the actual Explorer visibility functions against synthetic tiles.
// This tests checkbox gates, network partitions, and cache invalidation without
// importing MapLibre or altering published SIGMA data.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const js = fs.readFileSync(path.join(__dirname, '..', 'src/sigma/web/static/app.js'), 'utf8');
function extract(begin, end) {
  const start = js.indexOf(begin), stop = js.indexOf(end, start + begin.length);
  assert(start >= 0 && stop > start, `Cannot extract ${begin}`);
  return js.slice(start, stop);
}
const controls = {
  'show-unscored': {checked: false, disabled: false},
  'sigma-show-linked-unscored': {checked: false, disabled: false},
  'unclustered-key': {hidden: true},
};
const sectors = new Map([
  ['A', {clusters: 2}], ['B', {clusters: 1}],
  ['C', {clusters: 1}], ['Z', {clusters: 0}],
]);
const partitions = [
  {type: 'Feature', properties: {node_id: 'a1', type: 'A'}, geometry: {bbox: [0, 0, 10, 10]}},
  {type: 'Feature', properties: {node_id: 'b1', type: 'B'}, geometry: {bbox: [20, 20, 30, 30]}},
  {type: 'Feature', properties: {node_id: 'c1', type: 'C'}, geometry: {bbox: [40, 40, 50, 50]}},
];
const candidate = (id, type, coordinates) =>
  ({type: 'Feature', properties: {id, type, unclustered: true}, geometry: {type: 'Point', coordinates}});
let features = [], visible = false, updates = 0;
const sandbox = {
  network: null,
  map: {getLayer: () => ({})},
  $: id => controls[id],
  hidden: new Set(), sigmaHiddenOriginals: new Set(),
  sigmaOriginalAllowed: () => true,
  sectors,
  sigmaVoronoiFeatures: partitions,
  sigmaBounds: g => g.bbox,
  sigmaInsideGeometry: ([x,y], g) => x >= g.bbox[0] && x <= g.bbox[2] && y >= g.bbox[1] && y <= g.bbox[3],
  unscoredCandidates: [
    candidate('A-inside','A',[1,1]), candidate('A-outside','A',[15,15]),
    candidate('B-inside','B',[21,21]), candidate('C-inside','C',[41,41]),
    candidate('Z-unscored','Z',[1,1])
  ],
  lastRenderedTileSignature: '13/tile', unscoredRenderedKey: null,
  setData: (source, collection) => {
    if (source === 'unscored-points') {features = collection.features; updates++;}
  },
  visibility: (id, val) => {if (id === 'unclustered-establishments') visible = val;},
};
vm.createContext(sandbox);
vm.runInContext(
  extract('  function sigmaSelectedPartitions() {', '  function syncUnscoredOverlay() {') +
  extract('  function syncUnscoredOverlay() {', '  function applyEmphasis() {'), sandbox);
const ids = () => Array.from(features, f => f.properties.id).sort();
const check = expected => {sandbox.syncUnscoredOverlay(); assert.deepEqual(ids(), [...expected].sort());};
check([]);
controls['sigma-show-linked-unscored'].checked = true;
check(['A-inside','A-outside','B-inside','C-inside']);
controls['show-unscored'].checked = true;
check(['A-inside','A-outside','B-inside','C-inside','Z-unscored']);
controls['sigma-show-linked-unscored'].checked = false;
check(['Z-unscored']);
controls['sigma-show-linked-unscored'].checked = true;
sandbox.network = {focus: 'a1', ring: new Map([['a1',0],['b1',1]])};
check(['A-inside','B-inside']);
assert.equal(visible, true);
assert.equal(features.find(f => f.properties.id === 'B-inside').properties.voronoi_node_id, 'b1');
const beforeRingChange = updates;
sandbox.network = {focus: 'a1', ring: new Map([['a1',0],['b1',2]])}; // same IDs, different depth
check(['A-inside','B-inside']);
assert(updates > beforeRingChange, 'Changing network depth must invalidate cached source');
const beforeMembershipChange = updates;
sandbox.network = {focus: 'a1', ring: new Map([['a1',0]])}; // same focus, fewer highlighted partitions
check(['A-inside']);
assert(updates > beforeMembershipChange, 'Changing ring with same focus must invalidate cached source');
sandbox.network = {focus: 'c1', ring: new Map([['c1',0]])};
check(['C-inside']);
controls['sigma-show-linked-unscored'].checked = false;
check([]); assert.equal(visible, false);
sandbox.network = null;
controls['show-unscored'].checked = false;
check([]); assert.equal(visible, false);
console.log('PASS: 10 visibility states; selected focus+linked partitions, independent toggles, ring cache invalidation');
