// SIGMA_HOVER_POINT_PARTITION_OUTLINE_V15
// Execute the actual onHover() and sigmaSetHoveredPartition() handlers in
// isolation. No new polygon processing, renderer layer or scoring logic.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const src = fs.readFileSync(path.resolve(__dirname, '../src/sigma/web/static/app.js'), 'utf8');
const between = (start, end) => {
  const a = src.indexOf(start), b = src.indexOf(end, a + start.length);
  assert(a >= 0 && b > a, `Missing source anchors: ${start}`);
  return src.slice(a, b);
};
const tests = [
  // Test the real source implementation, not a second copy of its selection rules.
  between('  function selectableMapFeature(feature) {',
    '  // sigma-sector-clusters-katz-triangles-20261101-v1'),
  between('  function sigmaSetHoveredPartition(id) {', '  const POPUP_BLOCKS = 3;'),
  between('  function onHover(event) {', '  // Collapse bursts of mousemove events'),
].join('\n');
const filterHistory = [], visibilityHistory = [];
let hits = [], queryLayers = [], popups = 0;
const context = {
  ready: true,
  selection: {id:'focus'},
  network: {focus:'focus', ring:new Map([['focus',0],['linked',1]])},
  nodeIndex: new Map([['focus',{type:'A'}],['linked',{type:'B'}],['outside',{type:'C'}]]),
  hidden: new Set(),
  sigmaHoveredPartitionId: null,
  popup: {remove:()=>{},setLngLat(){return this;},setDOMContent(){return this;},addTo(){popups++;return this;}},
  el: (tag,props,...children)=>({tag,props,children}),
  describe: () => ['Visible establishment'],
  describeRoutes: () => [],
  POPUP_BLOCKS: 3,
  map: {
    getLayer:()=>({}), getLayoutProperty:()=> 'visible',
    getCanvas:()=>({style: {cursor:''}}),
    queryRenderedFeatures:(point,{layers})=>{
      queryLayers=layers;
      return hits.filter(feature => layers.includes(feature.layer.id));
    },
    setFilter:(layer,filter)=>filterHistory.push({layer,filter}),
    setLayoutProperty:(layer,property,value)=>visibilityHistory.push({layer,property,value}),
  },
};
vm.createContext(context);
vm.runInContext(tests,context);
const feature = (layer,properties={}) => ({layer:{id:layer},properties,geometry:{coordinates:[121,14.6]}});
const hover = (items,expected,label) => {
  hits=items; context.onHover({point:{x:3,y:4},lngLat:{lng:121,lat:14.6}});
  assert.equal(context.sigmaHoveredPartitionId,expected,label);
  const last = visibilityHistory.at(-1);
  if (expected) {
    assert.equal(last.value,'visible',label);
    assert.equal(JSON.stringify(filterHistory.at(-1).filter),
      JSON.stringify(['==',['get','node_id'],expected]),label);
  } else {
    assert.equal(last.value,'none',label);
  }
};
hover([feature('selected-center')],'focus','selected icon retains its outline');
hover([feature('centers',{id:'linked'})],'linked','linked center retains its outline');
hover([feature('centers',{id:'linked'}),feature('native-establishments',{node_id:'focus'})],
  'linked','center takes priority over an overlapping scored point');
hover([feature('selected-center'),feature('native-establishments',{node_id:'linked'})],
  'focus','selected-center takes priority over an overlapping scored point');
hover([feature('native-establishments',{node_id:'focus'})],'focus','native scored focus point');
hover([feature('native-establishments',{node_id:'linked'})],'linked','native scored linked point');
hover([feature('establishments',{node_id:'focus'})],'focus','legacy scored point');
hover([feature('unclustered-establishments',{voronoi_node_id:'linked',type:'B'})],
  'linked','classified-only point with existing same-sector Voronoi assignment');
hover([feature('unclustered-establishments',{voronoi_node_id:'focus',type:'A'})],
  'focus','classified-only point contained in focused partition');
hover([feature('unclustered-establishments',{type:'B'})],null,
  'unclustered without a display-only partition cannot draw a boundary');
hover([feature('aggregate-establishments',{representative_node_id:'linked'})],null,
  'cross-cluster aggregate must not imply membership');
context.hidden.add('B');
hover([feature('centers',{id:'linked'})],null,
  'hidden-sector center cannot activate an outline');
hover([feature('native-establishments',{node_id:'linked'})],null,
  'hidden-sector point cannot activate an outline');
context.hidden.delete('B');
hover([feature('native-establishments',{node_id:'outside'})],null,
  'point outside selected ring is not eligible');
hover([feature('native-ghost-establishments',{node_id:'outside'})],null,
  'ghosts remain excluded from hover and click interaction');
assert(!queryLayers.includes('native-ghost-establishments'),'ghosts never queried');
// Mouseout / panning should clear through the original helper.
context.sigmaSetHoveredPartition(null);
assert.equal(context.sigmaHoveredPartitionId,null);
// Do not create a polygon outline when there is no active selection.
context.network=null; context.selection=null;
hover([feature('native-establishments',{node_id:'focus'})],null,
  'no active selection retains original hover guard');
console.log('PASS: actual scored, linked, selected-center and opt-in unclustered hover; no aggregate/ghost inference');


// SIGMA_HOVER_PARTITIONS_OFF_SOURCE_V1: real on-demand source, not mocked loader logic.
// Off must suppress persistent partition fill/line while the hover-only outline
// still has the exact published geometry of the selected X network.
async function checkPartitionsOffHoverSource() {
  const getFunction = (start, end) => between(start, end);
  const source = [
    getFunction('  async function loadPartitionNeighborhood(epoch) {',
      '  // ------------------------------------------------------------------ selection'),
    getFunction('  function updatePartitions() {',
      '  // Render the directed X edges'),
    getFunction('  function sigmaSetHoveredPartition(id) {',
      '  const POPUP_BLOCKS = 3;'),
  ].join('\n');
  const polygon = (node_id, type) => ({type:'Feature',
    properties:{node_id,type},
    geometry:{type:'Polygon',coordinates:[[[120,14],[121,14],[121,15],[120,14]]]}});
  const focus = polygon('focus','A'), linked = polygon('linked','B');
  const requests = [], sources = [], ordinaryVisibility = [], hoverFilters = [], hoverLayout = [];
  const selectedNetwork = {focus:'focus', ring:new Map([['focus',0],['linked',1]])};
  const mapStub = {
    getLayer:()=>({}),
    setFilter:(layer,filter)=>hoverFilters.push({layer,filter}),
    setLayoutProperty:(layer,prop,value)=>hoverLayout.push({layer,prop,value}),
  };
  const sandbox = {
    meta: {partition_on_demand:true}, ready:true, refreshEpoch:8,
    state:{partitions:'off'},
    network:selectedNetwork, selection:{id:'focus'},
    nodeIndex:new Map([['focus',{type:'A',shard:1}],['linked',{type:'B',shard:2}]]),
    hidden:new Set(), map:mapStub,
    sigmaVoronoiFeatures:[], sigmaHoveredPartitionId:null,
    setData:(name,data)=>sources.push({name,data}),
    visibility:(name,enabled)=>ordinaryVisibility.push({name,enabled}),
    getJSON:async name=>{
      requests.push(name);
      if (name==='data/partitions/0001.geojson') return {features:[focus]};
      if (name==='data/partitions/0002.geojson') return {features:[linked]};
      if (name==='data/clusters.geojson') return {features:[focus,linked]};
      throw Error(`Unexpected partition request: ${name}`);
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(source,sandbox);

  assert.equal(await sandbox.loadPartitionNeighborhood(8),true,'OFF fetch succeeds');
  assert.deepEqual(requests, ['data/partitions/0001.geojson','data/partitions/0002.geojson'],
    'OFF fetches only selected-network shards, not all clusters');
  assert.equal(JSON.stringify(sources.at(-1).data.features.map(f=>f.properties.node_id)),
    JSON.stringify(['focus','linked']),
    'OFF retains exact selected-network polygons in hidden map source');
  assert.equal(sandbox.sigmaVoronoiFeatures.length,0,
    'OFF does not activate ghost or unclustered partition-context state');
  sandbox.updatePartitions();
  for (const name of ['partition-fill','partition-line','partition-linked-fill',
    'partition-linked-line','partition-focus-fill','partition-focus-line']) {
    assert.equal(ordinaryVisibility.find(v=>v.name===name)?.enabled,false,
      `OFF leaves persistent layer ${name} hidden`);
  }
  sandbox.sigmaSetHoveredPartition('linked');
  assert.equal(sandbox.sigmaHoveredPartitionId,'linked','hover points to loaded linked polygon');
  assert.equal(hoverLayout.at(-1).value,'visible','hover-only outline becomes visible');
  assert.equal(JSON.stringify(hoverFilters.at(-1).filter),
    JSON.stringify(['==',['get','node_id'],'linked']),
    'hover-only outline filters on the actual X node ID');
  assert.equal(requests.length,2,'mousemove causes no extra polygon requests');
  sandbox.sigmaSetHoveredPartition(null);
  assert.equal(hoverLayout.at(-1).value,'none','hover exit clears outline');

  sandbox.state.partitions='network';
  assert.equal(await sandbox.loadPartitionNeighborhood(8),true);
  assert.equal(sandbox.sigmaVoronoiFeatures.length,2,
    'Network mode preserves its original partition-context behavior');

  sandbox.state.partitions='all';
  assert.equal(await sandbox.loadPartitionNeighborhood(8),true);
  assert.equal(sandbox.sigmaVoronoiFeatures.length,2,
    'All mode retains its original full polygon behavior');
  assert.equal(requests.at(-1),'data/clusters.geojson');

  sandbox.state.partitions='off'; sandbox.network=null; sandbox.selection=null;
  const before = requests.length;
  assert.equal(await sandbox.loadPartitionNeighborhood(8),true);
  assert.equal(requests.length,before,'OFF without an X selection never fetches polygons');
  assert.equal(sources.at(-1).data.features.length,0,
    'OFF without selection empties the geometry source');
  sandbox.sigmaSetHoveredPartition('focus');
  assert.equal(sandbox.sigmaHoveredPartitionId,null,
    'OFF without selection does not reveal an unrelated Voronoi polygon');

  // Stale asynchronous results must not overwrite newer focus/visibility state.
  sandbox.network=selectedNetwork; sandbox.selection={id:'focus'};
  const snapshots = sources.length;
  assert.equal(await sandbox.loadPartitionNeighborhood(7),false,
    'stale refresh epoch is rejected');
  assert.equal(sources.length,snapshots,
    'stale load never replaces the active map source');
}
checkPartitionsOffHoverSource().then(() => {
  console.log('PASS: OFF still supplies existing selected Voronoi hover outlines; no persistent partitions or ghost context');
}).catch(error => { console.error(error); process.exitCode = 1; });
