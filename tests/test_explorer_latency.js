'use strict';
// Interaction recovery regressions; requires only Node's standard library.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '..', 'src', 'sigma', 'web', 'static', 'app.js'), 'utf8');

function section(start, end) {
  const a = source.indexOf(start), b = source.indexOf(end, a + start.length);
  assert(a >= 0 && b > a, `Missing Explorer performance section: ${start}`);
  return source.slice(a, b);
}

// A new selection must synchronously clear old routes and cancel stale deferred render jobs.
{
  const script = section('  function refresh() {', '  function selectUnclustered(');
  const work = [], frames = [], timers = [];
  let lastSelectionId = 'first';
  const nodeIndex = new Map([['first', {}], ['second', {}]]);
  // Inject closure's mutable selection through a getter implemented with a proxy object.
  const sharedSelection = new Proxy({}, {
    get: (_, prop) => prop === 'id' ? lastSelectionId : undefined,
  });
  // refresh's generation variables are scoped within the test function itself.
  const wrapped = new Function('selection', 'nodeIndex', 'buildNetwork',
    'computeNetworkTriangleStyles', 'renderSelection', 'ready', 'applyEmphasis', 'updateStatus',
    'renderSectors', 'drawGraph', 'renderConnections', 'showRoutes', 'setData', 'EMPTY',
    'requestAnimationFrame', 'setTimeout',
    `let refreshEpoch=0, routeEpoch=0, hoverEpoch=0, pendingHoverEvent=null, sigmaTriangleStyleByNode=null, network=null;\n${script}\nreturn {refresh};`);
  const callbacks = ['renderSelection', 'applyEmphasis', 'updateStatus', 'renderSectors', 'drawGraph', 'renderConnections', 'showRoutes'];
  const cb = Object.fromEntries(callbacks.map(key => [key, () => work.push(`${key}:${lastSelectionId}`)]));
  const handler = wrapped(sharedSelection, nodeIndex, id => ({focus:id}), () => new Map(),
    cb.renderSelection, true, cb.applyEmphasis, cb.updateStatus, cb.renderSectors, cb.drawGraph,
    cb.renderConnections, cb.showRoutes, (name, data) => {
      if (name === 'routes' || name === 'route-hover') {
        assert.deepEqual(data.features, [], 'Old routes must disappear immediately');
        work.push(`${name}:clear`);
      }
    }, () => ({type:'FeatureCollection',features:[]}), fn => frames.push(fn), fn => timers.push(fn));
  handler.refresh();
  assert.deepEqual(work.slice(0,2), ['routes:clear','route-hover:clear']);
  assert(work.includes('applyEmphasis:first'));
  assert(!work.some(x=>x.startsWith('drawGraph:')),'expensive work must be deferred');
  lastSelectionId='second';
  handler.refresh();
  for(const f of frames.splice(0)) f();
  for(const t of timers.splice(0)) t();
  assert.equal(work.filter(x=>x==='drawGraph:second').length,1);
  assert.equal(work.filter(x=>x==='drawGraph:first').length,0,'superseded graph render must be canceled');
  assert.equal(work.filter(x=>x==='showRoutes:second').length,1);
  assert.equal(work.filter(x=>x==='showRoutes:first').length,0);
}

// Hover is coalesced, and a newer pointer event wins within a frame.
{
  const script = section('  function scheduleHover(event) {', '  function onClick(event) {');
  const frames=[], hovers=[];
  const make = new Function('requestAnimationFrame', 'onHover',
    `let pendingHoverEvent=null, hoverFrameScheduled=false, ready=true;\n${script}\nreturn scheduleHover;`);
  const schedule=make(fn=>frames.push(fn),event=>hovers.push(event.point.x));
  schedule({point:{x:1}}); schedule({point:{x:2}}); schedule({point:{x:3}});
  assert.equal(frames.length,1,'Mousemove storms must generate one frame callback');
  frames.pop()();
  assert.deepEqual(hovers,[3],'Most recent event should be displayed');
}

// Reversed route geometry remains exactly equivalent; distinct published lines never merge.
{
  const script = section('  const routePairKey =', '  const routeAnchor =');
  const {sameRoadGeometry} = new Function(`${script}\nreturn {sameRoadGeometry};`)();
  const line=x=>({type:'LineString',coordinates:x});
  assert(sameRoadGeometry(line([[0,0],[1,0]]),line([[0,0],[1,0]])));
  assert(sameRoadGeometry(line([[0,0],[1,0]]),line([[1,0],[0,0]])));
  assert(!sameRoadGeometry(line([[0,0],[1,0]]),line([[0,0],[1,0.1]])));
  assert(!sameRoadGeometry(line([[0,0],[1,0]]),line([[0,0],[1,0],[2,0]])));
  assert(sameRoadGeometry({type:'MultiLineString',coordinates:[[[0,0],[1,0]]]},
    {type:'MultiLineString',coordinates:[[[0,0],[1,0]]]}));
}

// A pending tile transition must invalidate stale signature and remove old points.
assert.match(source,/if \(signature === lastRenderedTileSignature\) \{ updateStatus\(\); return; \}[\s\S]*?lastRenderedTileSignature = '';[\s\S]*?setData\('points', EMPTY\(\)\);/);
assert.match(source,/const routePaletteChanged = lastRoutePaletteTheme !== themeMode/);
assert.match(source,/const ROUTE_CACHE_LIMIT = 96;/);
assert.match(source,/map\.on\('mousemove', scheduleHover\)/);
console.log('PASS: immediate route removal, superseded render cancellation, bounded hover, exact route identities, tile transition.');
