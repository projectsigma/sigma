'use strict';
// Verify depth draw order and stable 3-color palette; test is self-contained.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root,'src/sigma/web/static', name),'utf8');
const js=read('app.js'), html=read('index.html'), css=read('style.css');
assert(js.includes('SIGMA reciprocal three-color depth routes v2'));
const start=js.indexOf("    map.addSource('routes', {type: 'geojson', data: EMPTY()});");
const end=js.indexOf("    map.addSource('route-hover', {type: 'geojson', data: EMPTY()});",start);
assert(start>=0 && end>start);
const segment=js.slice(start,end);
const layers=[];
const map={addSource(){},addLayer(layer){layers.push(layer);}};
const COLOR={outgoing:'#c0392b', incoming:'#1f6fb2', both:'#7b3fa0'};
new Function('map','COLOR','EMPTY',segment)(map,COLOR,()=>({features:[]}));
assert.equal(layers.length,60,'Three map layers per depth (20 depths), not per-edge overlays');
assert.equal(layers[0].id,'routes-step-20-casing','Deepest network roads drawn first');
assert.equal(layers[1].id,'routes-step-20');
assert.equal(layers[2].id,'routes-step-20-in');
assert.equal(layers.at(-3).id,'routes-casing');
assert.equal(layers.at(-2).id,'routes');
assert.equal(layers.at(-1).id,'routes-in','Direct links visually dominate');
for (let depth=1;depth<=20;depth++) {
  const stem=depth===1?'routes':`routes-step-${depth}`;
  const solid=layers.find(x=>x.id===stem);
  const incoming=layers.find(x=>x.id===(depth===1?'routes-in':stem+'-in'));
  assert(solid&&incoming);
  assert.deepEqual(solid.paint['line-color'], ['match',['get','kind'],'both',COLOR.both,COLOR.outgoing]);
  assert.equal(incoming.paint['line-color'],COLOR.incoming);
  assert.deepEqual(incoming.paint['line-dasharray'],[2,1]);
  assert(solid.paint['line-opacity']>=0.18);
  if (depth>1){
    const previous = layers.find(x=>x.id===(depth===2?'routes':`routes-step-${depth-1}`));
    assert(solid.paint['line-opacity'] < previous.paint['line-opacity'], 'Greater depth must be fainter');
  }
}
assert(js.includes("const tripleColor = ['match', ['get', 'kind'], 'both',"), 'Theme preserves purple');
assert(js.includes("`routes-step-${step}`"), 'Theme updates all steps');
assert(js.includes('const routeLayers = [];'), 'Map hover recognizes deeper routes');
assert(html.includes('purple = reciprocal X links'), 'Explain the meaning of purple');
assert(html.includes('<i class="legend-line both"></i>Both</span>'), 'Compact reciprocal legend entry exists');
assert(css.includes('.legend-line.both { color:var(--both); }'), 'Purple legend entry uses the modeled color');
console.log('PASS: stable red/blue/purple palette, all steps, draw order, theme and legend.');
