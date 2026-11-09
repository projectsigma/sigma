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
assert.match(html, /id="show-places" checked/, 'Scored Places default on');
assert.match(js, /\$\('show-places'\)\.addEventListener\('change', syncPlacesVisibility\)/, 'Places toggle registered');
assert.match(js, /const pointLayers = new Set\(/, 'Visibility gate covers establishment layers');
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

// Alpha 9 follow-up: run the actual Places visibility gate and master-off handler.
const visBegin = js.indexOf('  const pointLayers = new Set(');
const visEnd = js.indexOf('  const notHidden = ', visBegin);
const placeBegin = js.indexOf('  function syncPlacesVisibility() {');
const placeEnd = js.indexOf('  // SIGMA SELECTED-NETWORK SCOPE', placeBegin);
assert(visBegin >= 0 && visEnd > visBegin && placeBegin >= 0 && placeEnd > placeBegin);
const control = {
  'show-places': {checked: true},
  'show-unscored': {checked: true},
  'sigma-show-linked-unscored': {checked: true},
};
const mapLayers = new Map([
  ['native-establishments','visible'], ['unclustered-establishments','visible'],
  ['centers','visible'], ['selected-point','visible'], ['native-ghost-establishments','visible'],
]);
const mapMock = {
  getLayer: id => mapLayers.has(id) ? {id} : null,
  getLayoutProperty: id => mapLayers.get(id),
  setLayoutProperty: (id, key, value) => {
    assert.equal(key, 'visibility'); mapLayers.set(id, value);
  },
};
let overlayCalls = 0, clearedSelection = 0, popupCloses = 0;
const setup = new Function('map', '$', 'ready', 'popup', 'selection', 'nodeIndex',
  'clearSelection', 'syncUnscoredOverlay',
  `${js.slice(visBegin, visEnd)}\n${js.slice(placeBegin, placeEnd)}\n` +
  'return {visibility, syncPlacesVisibility};');
const {visibility, syncPlacesVisibility} = setup(mapMock, id => control[id], true,
  {remove: () => popupCloses++}, null, new Map(), () => clearedSelection++,
  () => overlayCalls++);
visibility('native-establishments', true);
visibility('unclustered-establishments', true);
visibility('native-ghost-establishments', true);
control['show-places'].checked = false;
syncPlacesVisibility();
for (const id of ['native-establishments','unclustered-establishments','selected-point','native-ghost-establishments'])
  assert.equal(mapLayers.get(id), 'none', `${id} hidden with Places off`);
assert.equal(mapLayers.get('centers'), 'visible', 'Independent cluster center remains visible');
assert.equal(control['show-unscored'].checked, false, 'Unclustered no-cluster checkbox cleared');
assert.equal(control['sigma-show-linked-unscored'].checked, false, 'Unclustered scored-sector checkbox cleared');
visibility('native-establishments', true);
assert.equal(mapLayers.get('native-establishments'), 'none', 'Async place layer cannot bypass master off');
control['show-places'].checked = true;
syncPlacesVisibility();
assert.equal(mapLayers.get('native-establishments'), 'visible', 'Scored places re-enabled');
assert.equal(mapLayers.get('unclustered-establishments'), 'none', 'Unclustered stays off');
assert.equal(control['show-unscored'].checked, false, 'Unclustered option remains unchecked');
assert.equal(control['sigma-show-linked-unscored'].checked, false, 'Linked unclustered remains unchecked');
assert.equal(overlayCalls, 1);
assert.equal(clearedSelection, 0);
assert.equal(popupCloses, 1);
console.log('PASS: scored Places master switch, unclustered opt-ins and independent centers.');

// Alpha 9 selection-control dynamic regression: both point and cluster entry
// must reset just the two top-level checkboxes, without enabling unclustered.
const selectionModeStart = js.indexOf('  function preferPlacesForSelection() {');
const selectionModeEnd = js.indexOf('  // SIGMA SELECTED-NETWORK SCOPE', selectionModeStart);
assert(selectionModeStart >= 0 && selectionModeEnd > selectionModeStart);
const selectionControls = {
  'show-places': {checked: false},
  'show-centers': {checked: true},
  'show-unscored': {checked: false},
  'sigma-show-linked-unscored': {checked: false},
};
let placeSyncs = 0, centerSyncs = 0;
const selectMode = new Function('$', 'syncPlacesVisibility', 'updateCenterVisibility',
  `${js.slice(selectionModeStart, selectionModeEnd)}\nreturn preferPlacesForSelection;`)(
    name => selectionControls[name], () => placeSyncs++, () => centerSyncs++);
selectMode();
assert.equal(selectionControls['show-places'].checked, true);
assert.equal(selectionControls['show-centers'].checked, false);
assert.equal(selectionControls['show-unscored'].checked, false);
assert.equal(selectionControls['sigma-show-linked-unscored'].checked, false);
assert.equal(placeSyncs, 1);
assert.equal(centerSyncs, 1);
selectMode();
assert.equal(placeSyncs, 1, 'No redundant Places repaint on repeated selection');
assert.equal(centerSyncs, 1, 'No redundant centers repaint on repeated selection');
assert.match(js, /function selectUnclustered\(point\) \{\s*preferPlacesForSelection\(\);/);
assert.match(js, /function selectNode\(id, point = null, options = \{\}\) \{\s*preferPlacesForSelection\(\);/);
console.log('PASS: selection-control dynamic regression.');
