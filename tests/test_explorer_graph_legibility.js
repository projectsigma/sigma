// Regression: a five-step diagram remains readable; focus zoom does not change the graph.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const src = fs.readFileSync(path.join(root, 'src/sigma/web/static/app.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'src/sigma/web/static/index.html'), 'utf8');
const css = fs.readFileSync(path.join(root, 'src/sigma/web/static/style.css'), 'utf8');
assert(src.includes('sigma-explorer-graph-legibility-20261020-v7'));
assert.match(html, /id="graph-focus"/);
assert.match(html, /data-tip="Zoom into the selected cluster and the first two network rings/);
assert.match(css, /#network\s*\{\s*height:440px;/);
assert.match(src, /'opacity': 0\.52, 'curve-style': 'bezier'/);
assert.match(src, /opacity: dark \? 0\.60 : 0\.52/);
assert.match(src, /selector: 'edge\.mid-edge'/);
assert.match(src, /selector: 'edge\.outer-edge'/);
assert.match(src, /selector: 'node\[ring >= 2\]', style: \{'width': 16/);
// The current graph deliberately labels only the focus when the network is large.
assert.match(src, /cy\.nodes\(\)\.filter\(n => n\.data\('ring'\) === 0\)\.addClass\('labelled'\)/);
assert.match(src, /wheelSensitivity: 0\.65/);
assert.match(src, /cy\.on\('zoom resize', syncNetworkGlyphs\)/);
assert.match(src, /const near = cy\.nodes\(\)\.filter\(n => n\.data\('ring'\) <= 2\)/);
assert.match(src, /cy\.fit\(near, 40\)/);
assert(!src.includes("'opacity': 0.20, 'curve-style': 'bezier'"), 'Faint old edges must be gone');

// Execute the current size-sync logic and drawGraph with a tiny fake Cytoscape collection.
const start = src.indexOf('  let graphGlyphFitZoom = 1;');
const end = src.indexOf('  function graphTip(', start + 1);
assert(start >= 0 && end > start, 'Graph function anchors are intact');
const program = src.slice(start, end);
const nodeIndex = new Map();
const ring = new Map();
const edges = [];
for (let i = 0; i < 19; i++) {
  const id = `63:${i}`;
  const depth = i === 0 ? 0 : Math.min(5, Math.ceil(i / 3));
  ring.set(id, depth);
  nodeIndex.set(id, {id, type: '63', cluster: i});
  if (i > 0) edges.push({source: `63:${Math.floor((i - 1) / 3)}`, target: id,
    strength: 0.12, coefficient: 0.12, distance: 100, weight: 12});
}
// A cross-connection in an outer ring is faint, but not hidden.
edges.push({source: '63:15', target: '63:17', strength: 0.05, coefficient: 0.05,
  distance: 200, weight: 10});
const network = {focus: '63:0', ring, edges, truncated: false};
const controls = {'graph-tip': {hidden: false}, 'network-empty': {hidden: true},
  'graph-count': {textContent: ''}};
const nodes = [], links = [];
const collection = arr => ({
  length: arr.length,
  filter(fn) {return collection(arr.filter(fn));},
  addClass(name) {for (const n of arr) n.classes.add(name);},
  style(values) {for (const n of arr) n.style(values);return this;}
});
let layoutOptions = null;
let zoom = 2;
const cy = {
  elements: () => ({remove() {nodes.length = 0; links.length = 0;}}),
  add(elements) {for (const el of elements) {
    const classes = new Set(el.classes?.split(/\s+/).filter(Boolean) || []);
    const target = {data: key => key ? el.data[key] : el.data, classes,
      appliedStyle: {},
      hasClass(name) {return classes.has(name);},
      style(values) {Object.assign(this.appliedStyle, values);return this;}};
    (el.group === 'nodes' ? nodes : links).push(target);
  }},
  nodes(selector) {
    if (selector === '.focus') return collection(nodes.filter(n => n.hasClass('focus')));
    if (selector === '.labelled') return collection(nodes.filter(n => n.hasClass('labelled')));
    if (selector === '[ring >= 2]') return collection(nodes.filter(n => n.data('ring') >= 2));
    return collection(nodes);
  },
  edges: () => links,
  zoom: () => zoom,
  batch(callback) {callback();},
  layout(opts) {layoutOptions = opts;return {run() {}};}
};
const graph = new Function('cy', '$', 'network', 'nodeIndex', 'LIMIT',
  'compareNodes', 'shortLabel', 'sectorColor',
  `${program}\nreturn {drawGraph, syncNetworkGlyphs};`)(cy, id => controls[id], network, nodeIndex,
    {labelledNodes: 12, graphNodes: 300, graphEdges: 1500},
    (a,b) => a.localeCompare(b), n => `${n.type}·${n.cluster}`, () => '#46a0ba');
// Sparse networks keep all identifiers visible without magnifying glyphs.
network.ring = new Map([...ring].slice(0, 6));
network.edges = edges.filter(e => network.ring.has(e.source) && network.ring.has(e.target));
graph.drawGraph();
assert.equal(nodes.length, 6);
assert.equal(nodes.filter(n => n.hasClass('labelled')).length, 6);
assert(Math.abs(nodes[0].appliedStyle.width * zoom - 23) < 0.01, 'Six-node focus is 23px on screen');
assert(Math.abs(nodes[1].appliedStyle.width * zoom - 17) < 0.01, 'Six-node peers are 17px on screen');

network.ring = ring;
network.edges = edges;
graph.drawGraph();
assert.equal(nodes.length, 19);
assert.equal(links.length, edges.length);
assert.deepEqual(nodes.filter(n => n.hasClass('labelled')).map(n => n.data('id')), ['63:0'],
  'Large graphs label the focus; other cluster IDs remain available on hover');
assert(links.some(e => e.hasClass('mid-edge')));
assert(links.some(e => e.hasClass('outer-edge')));
assert.equal(layoutOptions.minNodeSpacing, 16);
assert.match(controls['graph-count'].textContent, /19 clusters/);
assert(Math.abs(nodes[0].appliedStyle.width * zoom - 18) < 0.01, '19-node focus is 18px on screen');
assert(Math.abs(nodes[1].appliedStyle.width * zoom - 13) < 0.01, '19-node peers are 13px on screen');

// A denser network gets smaller circles and lower-contrast non-focus links.
for (let i = 19; i < 46; i++) {
  const id = `63:${i}`;
  ring.set(id, Math.min(5, Math.ceil(i / 9)));
  nodeIndex.set(id, {id, type: '63', cluster: i});
  edges.push({source: '63:0', target: id, strength: 0.12,
    coefficient: 0.12, distance: 100, weight: 12});
}
graph.drawGraph();
assert.equal(nodes.length, 46);
assert.deepEqual(nodes.filter(n => n.hasClass('labelled')).map(n => n.data('id')), ['63:0']);
assert(Math.abs(nodes[0].appliedStyle.width * zoom - 14) < 0.01, '46-node focus is 14px on screen');
assert(Math.abs(nodes[1].appliedStyle.width * zoom - 8) < 0.01, '46-node peers are 8px on screen');
assert(links.some(e => e.hasClass('outer-edge') && e.appliedStyle.opacity === 0.10));

// Mouse-wheel zoom changes glyph size gently, without unbounded enlargement.
zoom = 3;
graph.syncNetworkGlyphs();
const focusedPx = nodes[0].appliedStyle.width * zoom;
assert(focusedPx > 14 && focusedPx < 20, 'Focus responds modestly to wheel zoom');
console.log('PASS: dense-graph labels, bounded node sizing, depth-aware edges and gradual zoom.');
