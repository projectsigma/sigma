'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const {buildNetwork, expandRoutes} = require('../src/sigma/web/static/network-model.js');
const pair = new Map([['A', new Map()], ['B', new Map()], ['C', new Map()]]);
function add(u, v, coefficient) {
  const edge = {from: u, to: v, coefficient, distance: 1, weight: coefficient};
  if (!pair.get(u).has(v)) pair.get(u).set(v, {other: v, out: null, in: null});
  if (!pair.get(v).has(u)) pair.get(v).set(u, {other: u, out: null, in: null});
  pair.get(u).get(v).out = edge;
  pair.get(v).get(u).in = edge;
}
add('A','B',0.25);
add('B','A',0.05);
add('C','A',0.01);
const limits = {graphNodes:300, graphEdges:1500};
function links(direction) {
  return id => [...pair.get(id).values()].map(r => ({
    ...r, out: direction === 'incoming' ? null : r.out,
    in: direction === 'outgoing' ? null : r.in,
  })).filter(r=>r.out || r.in);
}
const directed = net => new Set(net.edges.map(e => `${e.source}->${e.target}`));
assert.deepEqual(directed(buildNetwork('A', links('outgoing'), '2', limits)), new Set(['A->B','B->A']));
assert.deepEqual(directed(buildNetwork('A', links('incoming'), '2', limits)), new Set(['A->B','B->A','C->A']));
// Direction determines reachability; the diagram shows the induced directed edges
// among discovered nodes (so a reciprocal link is visible even at depth 1).
assert.deepEqual(directed(buildNetwork('A', links('incoming'), '1', limits)), new Set(['A->B','B->A','C->A']));
assert.deepEqual(directed(buildNetwork('A', links('outgoing'), '1', limits)), new Set(['A->B','B->A']));
assert.deepEqual(directed(buildNetwork('A', links('both'), '1', limits)), new Set(['A->B','B->A','C->A']));
// Regression: both C and D sit at depth 2 from A. Their C->D and D->C
// edges must appear even though neither is expanded to discover more nodes.
const outerPairs = new Map(['A', 'B', 'C', 'D', 'E'].map(node => [node, new Map()]));
function outerEdge(u, v, coefficient) {
  const edge = {from:u, to:v, coefficient, distance:1, weight:coefficient};
  for (const [a,b,field] of [[u,v,'out'], [v,u,'in']]) {
    if (!outerPairs.get(a).has(b)) outerPairs.get(a).set(b, {other:b, out:null, in:null});
    outerPairs.get(a).get(b)[field] = edge;
  }
}
outerEdge('A', 'B', 0.8);
outerEdge('B', 'C', 0.6);
outerEdge('B', 'D', 0.5);
outerEdge('C', 'D', 0.4);
outerEdge('D', 'C', 0.3);
outerEdge('D', 'E', 0.2);
const outerLinks = node => [...outerPairs.get(node).values()].filter(r => r.out);
const twoHops = buildNetwork('A', outerLinks, '2', limits);
assert.deepEqual(new Set(twoHops.ring.keys()), new Set(['A','B','C','D']));
assert.deepEqual(directed(twoHops), new Set(['A->B','B->C','B->D','C->D','D->C']));
assert.equal(twoHops.ring.has('E'), false, 'depth two must not discover E');
assert.equal(twoHops.edgeCountAvailable, 5);
assert.deepEqual(directed(buildNetwork('A', outerLinks, '1', limits)), new Set(['A->B']));
assert.deepEqual(directed(buildNetwork('A', outerLinks, 'all', limits)),
  new Set(['A->B','B->C','B->D','C->D','D->C','D->E']));
const cappedEdges = buildNetwork('A', outerLinks, '2', {...limits, graphEdges:3});
assert.equal(cappedEdges.truncated, true);
assert.equal(cappedEdges.edgeCountAvailable, 5);
assert.equal(cappedEdges.edges.length, 3);
const cut = buildNetwork('A', links('both'), 'all', {graphNodes:2, graphEdges:1});
assert.equal(cut.truncated, true);
assert.equal(cut.edges.length, 1);
assert.equal(cut.ring.size, 2);
const strongly = buildNetwork('A', links('outgoing'), '2', limits).edges;
assert.equal(strongly.find(e=>e.source==='B').coefficient, 0.05);
// Exact reverse paths are stored once and rebuilt in the browser.
const routes = expandRoutes({type: 'FeatureCollection', features: [
  {type: 'Feature', properties: {from: 'A', to: 'B'}, geometry: {type: 'LineString', coordinates: [[0, 0], [1, 1], [2, 0]]}},
  {type: 'Feature', properties: {from: 'B', to: 'A', reverse_of: 0}, geometry: null},
  {type: 'Feature', properties: {from: 'C', to: 'A'}, geometry: {type: 'LineString', coordinates: [[5, 5], [0, 0]]}},
]});
assert.deepEqual(routes.features[1].geometry.coordinates, [[2, 0], [1, 1], [0, 0]]);
assert.deepEqual(routes.features[0].geometry.coordinates, [[0, 0], [1, 1], [2, 0]]); // source not mutated
assert.deepEqual(routes.features[2].geometry.coordinates, [[5, 5], [0, 0]]);
assert.throws(() => expandRoutes({features: [{properties: {reverse_of: 3}, geometry: null}]}));
console.log('SIGMA Explorer directed-network and route tests passed.');
