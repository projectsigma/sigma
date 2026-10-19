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
assert.match(src, /cy\.nodes\(\)\.filter\(n => n\.data\('ring'\) <= 1\)\.addClass\('labelled'\)/);
assert.match(src, /const near = cy\.nodes\(\)\.filter\(n => n\.data\('ring'\) <= 2\)/);
assert.match(src, /cy\.fit\(near, 40\)/);
assert(!src.includes("'opacity': 0.20, 'curve-style': 'bezier'"), 'Faint old edges must be gone');

// Execute the actual drawGraph() function with a tiny fake Cytoscape collection.
const start = src.indexOf('  function drawGraph() {');
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
  addClass(name) {for (const n of arr) n.classes.add(name);}
});
let layoutOptions = null;
const cy = {
  elements: () => ({remove() {nodes.length = 0; links.length = 0;}}),
  add(elements) {for (const el of elements) {
    const target = {data: key => key ? el.data[key] : el.data,
      classes: new Set(el.classes?.split(/\s+/).filter(Boolean) || [])};
    (el.group === 'nodes' ? nodes : links).push(target);
  }},
  nodes: () => collection(nodes),
  edges: () => links,
  layout(opts) {layoutOptions = opts;return {run() {}};}
};
const drawGraph = new Function('cy', '$', 'network', 'nodeIndex', 'LIMIT',
  'compareNodes', 'shortLabel', 'sectorColor',
  `${program}\nreturn drawGraph;`)(cy, id => controls[id], network, nodeIndex,
    {labelledNodes: 12, graphNodes: 300, graphEdges: 1500},
    (a,b) => a.localeCompare(b), n => `${n.type}·${n.cluster}`, () => '#46a0ba');
drawGraph();
assert.equal(nodes.length, 19);
assert.equal(links.length, edges.length);
assert(nodes.filter(n => n.classes.has('labelled')).length > 1,
  'Even when crowded, center and direct neighbors keep labels');
assert(nodes.filter(n => n.classes.has('labelled')).every(n => n.data('ring') <= 1));
assert(links.some(e => e.classes.has('mid-edge')));
assert(links.some(e => e.classes.has('outer-edge')));
assert.equal(layoutOptions.minNodeSpacing, 16);
assert.match(controls['graph-count'].textContent, /19 clusters/);
console.log('PASS: high-depth legibility, ring-one labels, depth-aware edge contrast, nearby zoom control.');
