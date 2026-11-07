// Execute against the actual generated Explorer code without a browser.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/sigma/web/static/app.js'), 'utf8');
const start = source.indexOf('  function inVisibleNetwork(properties) {');
const end = source.indexOf('  async function loadVisiblePoints() {', start);
assert(start >= 0 && end > start, 'Missing source-level visibility functions');
const block = source.slice(start, end);

function make({focused, summaryCount=3}) {
  const seen = new Map();
  const items = ['A','B','C'].map((node_id, i) => ({
    type: 'Feature', properties: {node_id, type: '12:72:222', original_type: '12:72:222',
      unclustered: false, score: i + 1},
    geometry: {type: 'Point', coordinates: [121.0+i*0.001, 14.5]}
  }));
  const state = {
    hidden: new Set(),
    selection: focused ? {id: 'A'} : null,
    nodeIndex: new Map(items.map(f => [f.properties.node_id, {}])),
    network: focused ? {ring: new Map([['A',0],['B',1]])} : null,
    visiblePointGroups: [{type: 'FeatureCollection', features: items}],
    visibleAggregateFeatures: items.map(f => ({type:'Feature',
      properties: {...f.properties, count: summaryCount}, geometry: f.geometry})),
    meta: {aggregate_budget: 4000, score_range:[1,3]},
    map: {getSource: () => ({}), getBounds: () => ({contains: () => true}), project: coordinates => ({x: coordinates[0], y: coordinates[1]})},
    sectors: new Map(),
    sigmaOriginalType: props => props.original_type,
    sigmaOriginalAllowed: () => true,
    isNum: x => Number.isFinite(x),
    setData: (key, fc) => seen.set(key, fc),
    syncUnscoredOverlay: () => {},
  };
  const factory = new Function('state', `
    let {hidden,selection,nodeIndex,network,visiblePointGroups,visibleAggregateFeatures,
      meta,map,sectors,sigmaOriginalType,sigmaOriginalAllowed,isNum,setData,syncUnscoredOverlay} = state;
    let unscoredCandidates = [], unscoredRenderedKey = null;
    ${block}
    return {run:syncRenderedEstablishments, boundSummaryGlyphs};
  `);
  return {api:factory(state), seen};
}

for (const focused of [true, false]) {
  const {api, seen} = make({focused});
  api.run();
  const selected = seen.get('points').features.map(f => f.properties.node_id);
  assert.deepEqual(selected, focused ? ['A','B'] : ['A','B','C']);
  const aggregates = seen.get('aggregates').features.map(f => f.properties.node_id);
  assert.deepEqual(aggregates, focused ? ['A','B'] : ['A','B','C']);
}

// When a dense selected network is coalesced, counts remain exact and any
// mixed-node summary must NOT falsely retain a specific X identity.
const {api} = make({focused:true});
const many = Array.from({length:4500}, (_, i) => ({type:'Feature',
  properties:{type:'12:72:222',original_type:'12:72:222',node_id:i%2?'A':'B',count:1},
  geometry:{type:'Point',coordinates:[121+(i%100)*1e-6, 14.5]}}));
const summarized = api.boundSummaryGlyphs(many);
assert(summarized.length <= 4000);
assert.equal(summarized.reduce((n,f)=>n+f.properties.count,0),4500);
assert(summarized.every(f=>!Object.hasOwn(f.properties,'node_id')));
console.log('PASS: selected X members only, clearing selection restores points, summary counts conserved.');
