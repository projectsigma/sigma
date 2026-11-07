// V7 native MapLibre vector tiles: exercise the inserted JS, not just string matching.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const src = fs.readFileSync(path.resolve(__dirname, '../src/sigma/web/static/app.js'), 'utf8');

const nativeStart = src.indexOf('    // Native vector-point LOD:');
const nativeEnd = src.indexOf('    // Assign browser-only icon identifiers', nativeStart);
assert(nativeStart >= 0 && nativeEnd > nativeStart, 'Native source/layer section absent');
const added = {source: null, layer: null};
const addNative = new Function('meta','map','location','notHidden','sigmaOriginalFilter',
    'sigmaPointColorExpr','scoreRadius',src.slice(nativeStart,nativeEnd));
addNative({native_points_v7:true,has_points:true}, {
  addSource: (name, spec)=>added.source={name,spec},
  addLayer: spec=>added.layer=spec,
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
console.log('PASS: v7 MapLibre native layer, valid zoom root, X filtering, and clicking true locations');
