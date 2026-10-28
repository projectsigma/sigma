'use strict';
// Integration regression for the actual Explorer layer-building code.
// Deliberately uses numeric GeoJSON sector codes and string metadata codes.
// It caught the October 2026 regression where icon IDs were assigned before
// the sector-specific canvas images were registered, making all icons fallback.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '..', 'src/sigma/web/static/app.js'), 'utf8');

function section(start, end) {
  const a = source.indexOf(start);
  const b = source.indexOf(end, a + start.length);
  assert(a >= 0 && b > a, `Missing source section: ${start}`);
  return source.slice(a, b);
}
const unscoredSource = section('  const unscoredSectorIcons = new Map();', '  function centerIconExpression() {');
const helperSource = section('  function centerIconExpression() {', '  // Selected cluster:');
const selectedSource = section('  function selectedCenterIconExpression() {', '  function addLayers(data) {');
const layerSource = section('  function addLayers(data) {', '  function bindControls() {');
const emphasisSource = section('  // SIGMA Explorer depth-based map opacity v1', '  function updatePartitions() {');
const sectors = new Map([
  ['55', {code: '55', label: 'Retail trade', color: '#f7336f'}],
  ['70', {code: '70', label: 'Real estate', color: '#692c39'}],
  ['63', {code: '63', label: 'Food and beverage service', color: '#25c8d1'}],
  ['80', {code: '80', label: 'Other services', color: '#82728d'}],
]);
const centerIconByType = new Map();
const linkedCenterIconByType = new Map();
const darkCenterIconByType = new Map();
const darkLinkedIconByType = new Map();
const selectedIconByType = new Map();
const colors = {incoming: '#1f6fb2', focus: '#16382a'};
const document = {
  createElement(tag) {
    assert.equal(tag, 'canvas');
    const ctx = {
      fillStyle: '', strokeStyle: '', lineWidth: 0,
      beginPath() {}, moveTo() {}, lineTo() {}, closePath() {}, fill() {}, stroke() {}, clearRect() {},
      getImageData() {return {fill: this.fillStyle, stroke: this.strokeStyle, strokeWidth: this.lineWidth};},
    };
    return {width: 0, height: 0, getContext(type) {assert.equal(type, '2d'); return ctx;}};
  },
};
const images = new Map();
const sources = new Map();
const layers = new Map();
const layoutUpdates = new Map();
const paintUpdates = new Map();
const map = {
  addImage(name, image) {assert(!images.has(name), `Duplicate map image: ${name}`); images.set(name, image);},
  addSource(name, source) {sources.set(name, source);},
  addLayer(layer) {layers.set(layer.id, layer);},
  setLayoutProperty(layer, property, value) {layoutUpdates.set(`${layer}.${property}`, value);},
  setPaintProperty(layer, property, value) {paintUpdates.set(`${layer}.${property}`, value);},
  setFilter() {}, getLayer() {return undefined;},
};
const meta = {score_range: [0, 1]};
const isNum = v => typeof v === 'number' && Number.isFinite(v);
const EMPTY = () => ({type: 'FeatureCollection', features: []});
const sectorMatchPairs = () => [...sectors].flatMap(([key, value]) => [key, value.color]);
const funcs = new Function('document', 'sectors', 'map', 'COLOR', 'centerIconByType',
  'linkedCenterIconByType', 'darkCenterIconByType', 'darkLinkedIconByType',
  'selectedIconByType', 'meta', 'isNum', 'sectorMatchPairs', 'EMPTY',
  `${unscoredSource}\n${helperSource}\n${selectedSource}\n${layerSource}\nreturn {addLayers};`)(
  document, sectors, map, colors, centerIconByType, linkedCenterIconByType,
  darkCenterIconByType, darkLinkedIconByType, selectedIconByType,
  meta, isNum, sectorMatchPairs, EMPTY);

// Numeric codes are common in GeoJSON while metadata may carry strings.
const data = {clusters: {type: 'FeatureCollection', features: []},
  centers: {type: 'FeatureCollection', features: [...sectors.keys()].map((code, i) => ({
    type: 'Feature', properties: {id: `${code}:${i}`, type: Number(code)},
    geometry: {type: 'Point', coordinates: [121 + i * 0.01, 14.5]},
  }))}, overview: {type: 'FeatureCollection', features: []}, roads: null, boundary: null};
funcs.addLayers(data);
const centers = sources.get('centers').data.features;
const baseLayer = layers.get('centers');
assert.deepEqual(baseLayer.layout['icon-image'], ['get', 'center_icon']);
assert.deepEqual(layers.get('selected-center').layout['icon-image'], ['get', 'icon']);
for (const feature of centers) {
  const code = String(feature.properties.type);
  const expected = sectors.get(code).color;
  const normal = images.get(feature.properties.center_icon);
  const linked = images.get(feature.properties.linked_center_icon);
  const darkNormal = images.get(feature.properties.dark_center_icon);
  const darkLinked = images.get(feature.properties.dark_linked_center_icon);
  const selected = images.get(selectedIconByType.get(code));
  assert(normal && linked && darkNormal && darkLinked && selected, `${code}: light/dark icon registration must precede feature assignment`);
  assert.equal(normal.fill, '#ffffff', `${code}: unselected fill must be white`);
  assert.equal(normal.stroke, expected, `${code}: unselected outline must match sector`);
  assert.equal(linked.fill, expected, `${code}: linked fill must match sector`);
  assert.equal(linked.stroke, colors.incoming, `${code}: linked outline must be blue`);
  assert.equal(darkNormal.fill, '#252323', `${code}: dark normal icon interior uses matte graphite`);
  assert.equal(darkNormal.stroke, expected, `${code}: dark normal icon sector outline`);
  assert.equal(darkLinked.fill, expected, `${code}: dark linked icon sector fill`);
  assert.equal(darkLinked.stroke, '#8cc8e9', `${code}: dark linked icon contrast outline`);
  assert.equal(selected.fill, expected, `${code}: selected fill must match sector`);
  assert.equal(selected.stroke, colors.incoming, `${code}: selected outline must be blue`);
  assert.notEqual(feature.properties.center_icon, 'sigma-center-default', `${code}: no fallbacks`);
  assert.notEqual(feature.properties.linked_center_icon, 'sigma-center-linked-default', `${code}: no fallbacks`);
}

function evaluate(expr, props) {
  if (!Array.isArray(expr)) return expr;
  const [op, ...args] = expr;
  if (op === 'get') return props[args[0]];
  if (op === 'literal') return args[0];
  if (op === '==') return evaluate(args[0], props) === evaluate(args[1], props);
  if (op === 'in') return evaluate(args[1], props).includes(evaluate(args[0], props));
  if (op === 'match') {
    const value = evaluate(args[0], props);
    for (let i = 1; i < args.length - 1; i += 2) {
      const candidate = args[i];
      if (Array.isArray(candidate) ? candidate.includes(value) : candidate === value)
        return evaluate(args[i + 1], props);
    }
    return evaluate(args[args.length - 1], props);
  }
  if (op === 'case') {
    for (let i = 0; i < args.length - 1; i += 2) if (evaluate(args[i], props)) return evaluate(args[i+1], props);
    return evaluate(args[args.length-1], props);
  }
  throw Error(`Unsupported expression: ${op}`);
}
const network = {ring: new Map([['63:2', 0], ['55:0', 1], ['70:1', 1]]), focus: '63:2'};
const getEmphasis = new Function('map','network','COLOR','notHidden','updatePartitions',
  'themeMode','updateCenterVisibility','applyTheme',
  `function syncUnscoredOverlay() {}\n${emphasisSource}\nreturn applyEmphasis;`)(
    map, network, colors, () => true, () => {}, 'light', () => {}, () => {});
getEmphasis();
const iconExpr = layoutUpdates.get('centers.icon-image');
const opacityExpr = paintUpdates.get('centers.icon-opacity');
assert(iconExpr && opacityExpr, 'Selection changes icon image and opacity');
const focus = centers.find(f => f.properties.id === '63:2');
const retail = centers.find(f => f.properties.id === '55:0');
const realEstate = centers.find(f => f.properties.id === '70:1');
const unrelated = centers.find(f => f.properties.id === '80:3');
for (const linked of [retail, realEstate]) {
  assert.equal(evaluate(iconExpr, linked.properties), linked.properties.linked_center_icon);
  assert.equal(images.get(evaluate(iconExpr, linked.properties)).fill, sectors.get(String(linked.properties.type)).color);
  assert.equal(evaluate(opacityExpr, linked.properties), 1);
}
assert.equal(evaluate(opacityExpr, focus.properties), 0, 'Focused normal triangle hidden behind selected icon');
assert.equal(evaluate(iconExpr, unrelated.properties), unrelated.properties.center_icon);
assert(evaluate(opacityExpr, unrelated.properties) < 0.3, 'Unrelated context triangle stays faint');
console.log('PASS: real sector palette registered before use; normal, linked, selected and dimmed centroids render correctly.');
