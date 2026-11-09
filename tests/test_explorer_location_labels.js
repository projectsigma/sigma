
// SIGMA location labels: strict boundary containment, panel occlusion, user toggle.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = path.join(__dirname,'../src/sigma/web/static');
const src = fs.readFileSync(path.join(base,'app.js'),'utf8');
const html = fs.readFileSync(path.join(base,'index.html'),'utf8');
const css = fs.readFileSync(path.join(base,'style.css'),'utf8');
const begin = src.indexOf('  // SIGMA_EXPLORER_LOCATION_LABELS_ONLY_20261109');
const end = src.indexOf('  // ------------------------------------------------------------------ map emphasis',begin);
assert(begin>=0 && end>begin,'Geographic code is isolated from analytical behavior');
assert.match(html,/id="show-locations" checked/);
assert.match(html,/Help: Location/);
assert.match(src,/\$\('show-locations'\)\.addEventListener\('change', scheduleLocationLabels\)/);
assert.match(src,/\.disabled = !\(meta\.has_context_labels && meta\.has_boundary\)/);
assert.match(css,/\.sigma-locations-control/);
const labels = [
  {geometry:{coordinates:[120.70,14.60]},properties:{kind:'town',name:'Quezon City'}},
  {geometry:{coordinates:[120.55,14.50]},properties:{kind:'locality',name:'Neighborhood'}},
  {geometry:{coordinates:[120.95,14.55]},properties:{kind:'road',name:'Example Avenue',class:'primary'}},
  {geometry:{coordinates:[120.20,14.50]},properties:{kind:'locality',name:'Behind panel'}},
  {geometry:{coordinates:[120.83,14.97]},properties:{kind:'locality',name:'Behind status'}},
  {geometry:{coordinates:[121.15,14.50]},properties:{kind:'locality',name:'Outside city'}},
  {geometry:{coordinates:[120.995,14.60]},properties:{kind:'locality',name:'Cross-border text'}},
];
// Published administrative polygon: right border x=1000, plus a small hole.
const boundary={features:[{geometry:{type:'Polygon',coordinates:[
 [[120,14],[121,14],[121,15],[120,15],[120,14]],
 [[120.78,14.2],[120.82,14.2],[120.82,14.25],[120.78,14.25],[120.78,14.2]],
]}}]};
let zoom=14, roadsOn=true, locationsOn=true, roadColor='#949b9b', opacity=.38;
const frames=[], listeners={};
function element(){return {style:{},children:[],clientWidth:1200,clientHeight:1000,
  append(c){this.children.push(c)},replaceChildren(...nodes){this.children=nodes},
  setAttribute(){},addEventListener(name,fn){this[name]=fn},textContent:''};}
const root=element();
root.getBoundingClientRect=()=>({left:100,top:50,right:1300,bottom:1050});
const rect=(x0,y0,x1,y1)=>({getClientRects:()=>[1],
  getBoundingClientRect:()=>({left:x0+100,top:y0+50,right:x1+100,bottom:y1+50})});
const panel=rect(0,60,420,750),status=rect(0,0,940,60),legend=rect(0,910,400,1000);
panel.addEventListener=(name,fn)=>{listeners['panel-'+name]=fn};
const document={createElement:()=>element(),querySelector:s=>s==='.sector-panel'?panel:null,
  querySelectorAll:()=>[panel,status,legend]};
const map={getZoom:()=>zoom,getContainer:()=>root,
  getLayer:id=>id==='roads-line',
  getPaintProperty:(_,key)=>key==='line-opacity'?opacity:roadColor,
  project:c=>({x:(c[0]-120)*1000,y:(15-c[1])*1000}),
  on:(kind,fn)=>{listeners[kind]=fn}};
const $=id=>id==='show-locations'?{checked:locationsOn}:
  id==='show-roads'?{checked:roadsOn}:null;
const getJSON=async p=>p==='data/context-labels.geojson'?{features:labels}:
  p==='data/boundary.geojson'?boundary:Promise.reject(Error('Unexpected source: '+p));
const requestAnimationFrame=fn=>frames.push(fn);
const {loadLocationLabels,renderLocationLabels,scheduleLocationLabels,locationRectInsidePolygon,
       locationProjectedPolygons}=new Function('map','document','$','getJSON','requestAnimationFrame','meta',
 src.slice(begin,end)+'\nreturn {loadLocationLabels,renderLocationLabels,scheduleLocationLabels,locationRectInsidePolygon,locationProjectedPolygons};')(
 map,document,$,getJSON,requestAnimationFrame,{has_context_labels:true,has_boundary:true});
(async()=>{
  await loadLocationLabels();
  assert.equal(typeof listeners.move,'function');
  assert.equal(typeof listeners.resize,'function');
  assert.equal(typeof listeners['panel-toggle'],'function');
  frames.shift()();
  const names=()=>root.children[0].children.map(e=>e.textContent);
  assert.deepEqual(names(),['Quezon City','Neighborhood','Example Avenue']);
  assert(!names().includes('Outside city'),'All outside municipality labels must be removed');
  assert(!names().includes('Cross-border text'),'Text crossing the boundary must be rejected');
  assert(!names().includes('Behind panel'),'Sector panel must occlude labels fully');
  assert(!names().includes('Behind status'),'Status panel must occlude labels fully');
  const polygons=locationProjectedPolygons();
  assert(!locationRectInsidePolygon([790,770,805,800],polygons),'Hole must exclude rectangles');
  locationsOn=false;renderLocationLabels();assert.equal(names().length,0,'Master toggle off');
  roadsOn=false;locationsOn=true;renderLocationLabels();
  assert(names().includes('Quezon City'));assert(!names().includes('Example Avenue'));
  roadsOn=true;renderLocationLabels();assert(names().includes('Example Avenue'));
  assert.equal(Number(root.children[0].children[0].style.opacity),.78);
  zoom=10;renderLocationLabels();assert.deepEqual(names(),['Quezon City']);
  listeners['panel-toggle']();assert.equal(frames.length,1,'Panel changes reschedule labels');
  frames.shift()();
  // When boundary is unavailable, do not create an unconstrained overlay.
  const empty=new Function('map','document','$','getJSON','requestAnimationFrame','meta',
    src.slice(begin,end)+'\nreturn loadLocationLabels;')(
      map,document,$,async p=>({features:[]}),requestAnimationFrame,
      {has_context_labels:true,has_boundary:true});
  const before=root.children.length;
  await empty();assert.equal(root.children.length,before);
  console.log('PASS: local boundary, panel-safe locations, toggle, road visibility, and zoom.');
})().catch(error=>{console.error(error);process.exitCode=1});
