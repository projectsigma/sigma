// V7 native MapLibre vector tiles: exercise the inserted JS, not just string matching.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const src = fs.readFileSync(path.resolve(__dirname, '../src/sigma/web/static/app.js'), 'utf8');

const nativeStart = src.indexOf('    // Native vector-point LOD:');
const nativeEnd = src.indexOf('    // Assign browser-only icon identifiers', nativeStart);
assert(nativeStart >= 0 && nativeEnd > nativeStart, 'Native source/layer section absent');
const added = {source: null, layer: null, layers: []};
const addNative = new Function('meta','map','location','notHidden','sigmaOriginalFilter',
    'sigmaPointColorExpr','scoreRadius',src.slice(nativeStart,nativeEnd));
addNative({native_points_v7:true,has_points:true}, {
  addSource: (name, spec)=>added.source={name,spec},
  addLayer: spec=>{added.layer=spec;added.layers.push(spec);},
}, {href:'http://127.0.0.1:8765/index.html'},
()=>['==',['get','type'],'06'], ()=>['==',['get','original_type'],'06'],
['get','type'],(small,large)=>['+',small,large]);
assert.equal(added.source.name,'native-points');
assert.equal(added.source.spec.type,'vector');
assert.equal(added.source.spec.minzoom,8);
assert.equal(added.source.spec.maxzoom,13);
assert.match(added.source.spec.tiles[0], /data\/points-v7\/\{z\}\/\{x\}\/\{y\}\.pbf$/);
assert.equal(added.layer.id,'native-establishments');
assert.equal(added.layer['source-layer'],'places');
assert.equal(added.layer.paint['circle-radius'][0],'interpolate');
assert.deepEqual(added.layer.paint['circle-radius'][2], ['zoom']);
const ghostLayer = added.layers.find(layer => layer.id === 'native-ghost-establishments');
assert(ghostLayer, 'Ghost context must use the existing PBF source');
assert.equal(ghostLayer.source, 'native-points');
assert.equal(ghostLayer['source-layer'], 'places');
assert.equal(ghostLayer.layout.visibility, 'none', 'Never show ghosts before selecting');
assert.equal(ghostLayer.paint['circle-opacity'], 0.30, 'Ghost context must remain visible after low-density v13 sampling');
assert.equal(ghostLayer.paint['circle-stroke-width'], 0);

const fnStart = src.indexOf('  function syncNativePointLayer() {');
const fnEnd = src.indexOf('  async function loadVisiblePoints()',fnStart);
assert(fnStart>=0 && fnEnd>fnStart,'native layer controller absent');
const filters=[], opacities=[], shown=[];
const filterFn = new Function('meta','map','selection','nodeIndex','network','notHidden',
  'sigmaOriginalFilter','networkDepthOpacity','fadeByStep','visibility',
  src.slice(fnStart,fnEnd)+'\nreturn syncNativePointLayer;');
const network={focus:'a',ring:new Map([['a',0],['b',1]])};
const fn=filterFn({native_points_v7:true}, {
  getLayer:id=>({id}),
  setFilter:(id,expr)=>filters.push({id,expr}),
  setPaintProperty:(id,key,expr)=>opacities.push({id,key,expr}),
}, {id:'a'}, new Map([['a',{}]]), network,
  ()=>['literal','all'], ()=>['literal','all'],
  (prop,focus,linked,outside)=>['match','step',focus,outside],
  (base,step)=>base/Math.sqrt(step), (id,bool)=>shown.push({id,bool}));
fn();
assert.equal(filters.length,1);
assert.equal(filters[0].id,'native-establishments');
assert.deepEqual(filters[0].expr.at(-1), ['in',['get','node_id'],['literal',['a','b']]]);
assert(shown.some(x=>x.id==='establishments'&&!x.bool));
assert(shown.some(x=>x.id==='aggregate-establishments'&&!x.bool));

const clickStart=src.indexOf('  function onClick(event) {');
const clickEnd=src.indexOf('  // ------------------------------------------------------------------ setup',clickStart);
assert(clickStart>=0&&clickEnd>clickStart);
let clicked=null;
const onClick=new Function('popup','map','selectableMapFeature','selectNode','selectUnclustered','nodeIndex',
  src.slice(clickStart,clickEnd)+'\nreturn onClick;')(
  {remove:()=>{}}, {
    getLayer:(id)=>({id}),getLayoutProperty:()=> 'visible',
    queryRenderedFeatures:()=>[{layer:{id:'native-establishments'},properties:{node_id:'real-X',name:'Shop'},geometry:{coordinates:[121,14.6]}}],
  },()=>true,(id,point)=>clicked={id,point},()=>{},new Map());
onClick({point:{x:1,y:2}});
assert.equal(clicked?.id,'real-X');
assert.deepEqual(clicked.point.coordinates,[121,14.6]);
// V12: evaluate the real ghost-filter generator against overlapping polygons.
// Ghosts must never be selectable, acquire X membership, or appear at rest.
assert(!src.slice(clickStart,clickEnd).includes("'native-ghost-establishments'"),
  'Context layer is deliberately excluded from hit testing');
const ghostStart=src.indexOf('  // SIGMA_EXPLORER_GHOST_CONTEXT_V12');
const ghostEnd=src.indexOf('  async function loadVisiblePoints()',ghostStart);
assert(ghostStart>=0&&ghostEnd>ghostStart,'ghost controller missing');
const ghostSrc=src.slice(ghostStart,ghostEnd);
const selected={id:'a',point:null};
const state={partitions:'network'};
let zoom=12.2;
const hidden=new Set();
const originalHidden=new Set();
const polygons=[
  {type:'Feature',properties:{node_id:'a',type:'06'},geometry:{type:'Polygon',coordinates:[[[0,0],[2,0],[2,2],[0,2],[0,0]]]}},
  {type:'Feature',properties:{node_id:'b',type:'06'},geometry:{type:'Polygon',coordinates:[[[1,1],[3,1],[3,3],[1,3],[1,1]]]}},
  {type:'Feature',properties:{node_id:'z',type:'06'},geometry:{type:'Polygon',coordinates:[[[6,6],[7,6],[7,7],[6,7],[6,6]]]}},
];
const sigBounds = shape => {
  const coords=shape.coordinates.flat(2);
  return [Math.min(...coords.filter((_,i)=>i%2===0)),Math.min(...coords.filter((_,i)=>i%2===1)),
    Math.max(...coords.filter((_,i)=>i%2===0)),Math.max(...coords.filter((_,i)=>i%2===1))];
};
const seenGhost=[],shownGhost=[];
const mapGhost={getLayer:id=>({id}),getZoom:()=>zoom,
  getBounds:()=>({getWest:()=>-1,getEast:()=>5,getSouth:()=>-1,getNorth:()=>5}),
  setFilter:(id,filter)=>seenGhost.push({id,filter})};
const makeGhost = new Function('meta','map','network','selection','state','sigmaVoronoiFeatures',
  'sigmaBounds','hidden','sigmaHiddenOriginals','notHidden','sigmaOriginalFilter','visibility',
  ghostSrc+'\nreturn {ghostContextRate, syncGhostContextLayer};');
const net={focus:'a',ring:new Map([['a',0],['b',1]])};
const controls=makeGhost({native_points_v7:true},mapGhost,net,selected,state,polygons,
  sigBounds,hidden,originalHidden,()=>['literal',true],()=>['literal',true],
  (id,value)=>shownGhost.push({id,value}));
for(const [z,rate] of [[8,0.015],[9,0.015],[10,0.015],[11,0.04],[12,0.10],[19,0.10]])
  assert.equal(controls.ghostContextRate(z),rate);
controls.syncGhostContextLayer();
assert.equal(shownGhost.at(-1).value,true);
assert.equal(seenGhost.length,1);
const expr=seenGhost.at(-1).filter;
assert.equal(expr[0],'all');
assert.deepEqual(expr[2],['has','lod_rank']);
assert.deepEqual(expr[3],['<',['get','lod_rank'],0.10]);
assert.deepEqual(expr[6],['!',['in',['get','node_id'],['literal',['a','b']]]]);
assert.equal(expr[7][0],'within');
assert.equal(expr[7][1].type,'FeatureCollection');
assert.deepEqual(expr[7][1].features.map(f=>f.geometry.coordinates[0][0]),[[0,0],[1,1]]);
controls.syncGhostContextLayer();
assert.equal(seenGhost.length,1,'Same context does not trigger MapLibre filter reparse');
// No viewport-bounding-box dependency: a pan in the same selection is cheap.
mapGhost.getBounds=()=>{throw Error('Ghost filter must not depend on viewport panning');};
controls.syncGhostContextLayer();
assert.equal(seenGhost.length,1,'Panning must not recompile the geographic filter');
zoom=11;
controls.syncGhostContextLayer();
assert.equal(seenGhost.at(-1).filter[3][2],0.04);
state.partitions='all';
controls.syncGhostContextLayer();
assert.equal(shownGhost.at(-1).value,false,'No ghosts in normal all-sectors overview');
state.partitions='network';
net.ring=new Map([['a',0]]);
controls.syncGhostContextLayer();
assert.deepEqual(seenGhost.at(-1).filter[7][1].features.map(f=>f.geometry.coordinates[0][0]),[[0,0]]);
// A dense selected network cannot send 96 polygons to the MapLibre worker.
for(let i=0;i<30;i++){
  const id='extra-'+i;
  net.ring.set(id,2);
  polygons.push({type:'Feature', properties:{node_id:id,type:'06'}, geometry:
    {type:'Polygon',coordinates:[[[i,0],[i+0.5,0],[i+0.5,0.5],[i,0.5],[i,0]]]}});
}
controls.syncGhostContextLayer();
const limited=seenGhost.at(-1).filter[7][1].features;
assert(limited.length<=12,'Ghost polygons must be capped to a small, stable set');
assert.deepEqual(limited[0].geometry.coordinates[0][0],[0,0],
  'Selected focus polygon has first priority');
assert(!ghostSrc.includes('map.getBounds()'), 'Ghost polygon footprint must not change on pan');
console.log('PASS: v13 ghost layer: 10% cap, stable pan, bounded exact polygons, click isolation');
console.log('PASS: v7 MapLibre native layer, valid zoom root, X filtering, and clicking true locations');
