'use strict';
// Regression for the multi-step patch: every rendered road is published and
// step-specific; true reciprocal X connections are purple, never duplicates.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/sigma/web/static/app.js'), 'utf8');
const first = source.indexOf('  const routePairKey =');
const last = source.indexOf('  async function highlightRoute(', first);
assert(first >= 0 && last > first, 'Multi-step tri-color route function must exist');
const js = source.slice(first, last);
const geometry = (...points) => ({type:'LineString', coordinates:points});
const feature = (from, to, coefficient, coordinates) => ({
  properties: {from, to, other:to, direction:'outgoing', coefficient,
    weight:coefficient * 10, distance:3.5},
  geometry: geometry(...coordinates),
});
const routeFiles = new Map([
  ['A', [feature('A','B',0.90, [[0,0],[1,0]])]],
  ['B', [feature('B','A',0.70, [[1,0],[0,0]]),
         feature('B','C',0.60, [[1,0],[2,0]])]],
  ['C', [feature('C','B',0.40, [[2,1],[1,1]]),
         feature('C','E',0.30, [[2,0],[3,0]])]],
  ['D', [feature('D','C',0.25, [[3,2],[2,2]])]],
  ['F', [feature('F','G',0.20, [[2,0],[3,0]])]],
  ['G', []], ['E', []]
]);
const nodeIndex = new Map([...routeFiles.keys()].map(id=>[id,{id,route_file:id}]));
const edge = (source,target,strength) => ({source,target,strength});
const network = {focus:'A', ring:new Map([['A',0],['B',1],['C',2],['F',2],['G',2],['D',3],['E',3]]), edges: [
  edge('A','B',0.9), edge('B','A',0.7),
  edge('B','C',0.6), edge('C','B',0.4),
  edge('C','E',0.3), edge('D','C',0.25), edge('F','G',0.2)
]};
let output = null;
const setData = (name, value) => {if(name==='routes') output=value;};
const getRoutes = async name => ({type:'FeatureCollection', features:routeFiles.get(name)});
const create = new Function('nodeIndex', 'getRoutes', 'setData', 'EMPTY', 'isNum',
    'showError', 'routeEpoch', 'hoverEpoch', 'network',
    `${js}\nreturn {showRoutes, sameRoadGeometry, routePairKey};`);
const funcs = create(nodeIndex, getRoutes, setData, () => ({type:'FeatureCollection',features:[]}),
  Number.isFinite, err => {throw err;}, 0, 0, network);
assert(funcs.sameRoadGeometry(geometry([0,0],[1,0]),geometry([1,0],[0,0])));
assert(!funcs.sameRoadGeometry(geometry([0,0],[1,0]),geometry([1,1],[0,1])));
(async () => {
  await funcs.showRoutes();
  assert(output && Array.isArray(output.features));
  assert.equal(output.features.length, 6, 'One coincident reciprocal pair merged; distinct routes retained');
  const match = (a,b) => output.features.filter(f=>
    f.properties.pair_key === funcs.routePairKey(a,b));
  const ab=match('A','B');
  assert.equal(ab.length, 1, 'Identical reverse paths form one purple route');
  assert.equal(ab[0].properties.kind,'both');
  assert.equal(ab[0].properties.depth,1);
  assert.equal(ab[0].properties.reverse_coefficient,0.7);
  assert.equal(ab[0].properties.separate_paths,false);
  const bc=match('B','C');
  assert.equal(bc.length,2,'Different published roads must stay separate');
  assert(bc.every(f=>f.properties.kind==='both'&&f.properties.depth===2));
  assert(bc.every(f=>f.properties.separate_paths===true));
  assert.equal(match('C','E')[0].properties.kind,'outgoing');
  assert.equal(match('C','E')[0].properties.depth,3);
  assert.equal(match('D','C')[0].properties.kind,'incoming');
  assert.equal(match('D','C')[0].properties.depth,3);
  assert.equal(match('F','G')[0].properties.kind,'outgoing','Unrelated physically overlapping paths are not treated as reciprocal');
  assert.equal(match('F','G')[0].properties.depth,2);
  assert(output.features.every(f=>f.geometry.type==='LineString'), 'No geographic chords created');
  console.log('PASS: multi-step exact roads, direction, reciprocity and unchanged geometry.');
})().catch(err=>{console.error(err);process.exitCode=1;});
