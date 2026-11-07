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

// A new selection must immediately clear stale routes, and defer graph work until its
// asynchronous published-partition load resolves. Superseded work must not run.
async function testSelectionRefresh() {
  const script = section('  let graphAutoClosed = true;', '  function selectUnclustered(');
  const work = [], frames = [], timers = [];
  let lastSelectionId = 'first';
  const nodeIndex = new Map([['first', {}], ['second', {}]]);
  // Inject closure's mutable selection through a getter implemented with a proxy object.
  const sharedSelection = new Proxy({}, {
    get: (_, prop) => prop === 'id' ? lastSelectionId : undefined,
  });
  // refresh's generation variables are scoped within the test function itself.
  const wrapped = new Function('sigmaPerf', 'sigmaSyncSelectedTriangle', 'sigmaTriangleImageCache', 'SIGMA_TRIANGLE_IMAGE_LIMIT', 'pruneSigmaTriangleImages', 'selection', 'nodeIndex', 'buildNetwork',
    'computeNetworkTriangleStyles', 'renderSelection', 'ready', 'applyEmphasis', 'updateStatus',
    'renderSectors', 'drawGraph', 'renderConnections', 'showRoutes', 'setData', 'EMPTY',
    'requestAnimationFrame', 'setTimeout', 'document', 'sigmaSetHoveredPartition',
    'meta', 'cancelBrowserPending',
    `async function loadPartitionNeighborhood() { return true; }\nfunction showError(error) { throw error; }\nlet refreshEpoch=0, routeEpoch=0, hoverEpoch=0, pendingHoverEvent=null, sigmaTriangleStyleByNode=null, network=null;\n${script}\nreturn {refresh};`);
  const callbacks = ['renderSelection', 'applyEmphasis', 'updateStatus', 'renderSectors', 'drawGraph', 'renderConnections', 'showRoutes'];
  const cb = Object.fromEntries(callbacks.map(key => [key, () => work.push(`${key}:${lastSelectionId}`)]));
  const graphDetails = {open: false};
  const mode = {route_mode: 'precomputed'};
  const handler = wrapped((_label, fn) => fn(), () => {}, new Map(), 640, () => {}, sharedSelection, nodeIndex, id => ({focus:id}), () => new Map(),
    cb.renderSelection, true, cb.applyEmphasis, cb.updateStatus, cb.renderSectors, cb.drawGraph,
    cb.renderConnections, cb.showRoutes, (name, data) => {
      if (name === 'routes' || name === 'route-hover') {
        assert.deepEqual(data.features, [], 'Old routes must disappear immediately');
        work.push(`${name}:clear`);
      }
    }, () => ({type:'FeatureCollection',features:[]}), fn => frames.push(fn), fn => timers.push(fn),
    {querySelector: selector => {
      assert.equal(selector, '.graph-section .sidebar-disclosure');
      return graphDetails;
    }}, id => {
      assert.equal(id, null, 'Refresh must clear the hovered partition');
      work.push('hover:clear');
    }, mode, () => work.push('browser:cancel'));
  handler.refresh();
  await Promise.resolve();
  assert.equal(graphDetails.open, true, 'selected network should expand graph');
  assert.deepEqual(work.slice(0,3), ['hover:clear','routes:clear','route-hover:clear'],
    'Selection refresh must clear the hovered polygon before old routes');
  assert(work.includes('applyEmphasis:first'));
  assert(!work.some(x=>x.startsWith('drawGraph:')),'expensive work must be deferred');
  lastSelectionId='second';
  handler.refresh();
  await Promise.resolve();
  for(const f of frames.splice(0)) f();
  for(const t of timers.splice(0)) t();
  assert.equal(work.filter(x=>x==='drawGraph:second').length,1);
  assert.equal(work.filter(x=>x==='drawGraph:first').length,0,'superseded graph render must be canceled');
  assert.equal(work.filter(x=>x==='showRoutes:second').length,1);
  assert.equal(work.filter(x=>x==='showRoutes:first').length,0);
  // Preserve manual collapse while a network remains selected.
  graphDetails.open = false;
  handler.refresh();
  await Promise.resolve();
  assert.equal(graphDetails.open, false, 'manual collapse should persist');
  // No selected X-network closes the disclosure; a new one reopens it.
  lastSelectionId = 'missing';
  handler.refresh();
  await Promise.resolve();
  assert.equal(graphDetails.open, false, 'missing network should collapse graph');
  lastSelectionId = 'first';
  handler.refresh();
  await Promise.resolve();
  assert.equal(graphDetails.open, true, 'new network should reopen graph');
  // Switching to browser mode must synchronously cancel obsolete worker jobs.
  const prior = work.length;
  mode.route_mode = 'browser';
  handler.refresh();
  await Promise.resolve();
  assert.deepEqual(work.slice(prior, prior + 4),
    ['hover:clear', 'browser:cancel', 'routes:clear', 'route-hover:clear'],
    'browser routing must cancel pending worker jobs before clearing old paths');
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
// Native scored tiles do not rebuild huge GeoJSON sources per pan; the legacy
// fallback still retains a signature cache and reclips on an unchanged tile set.
assert.match(source, /if \(meta\.native_points_v7\) \{/);
assert.match(source, /syncNativePointLayer\(\)/);
assert.match(source, /if \(signature === lastRenderedTileSignature\) \{\s*syncRenderedEstablishments\(\)/);
assert.match(source, /lastRenderedTileSignature = '';/);
assert.match(source,/const routePaletteChanged = lastRoutePaletteTheme !== themeMode/);
assert.match(source,/const ROUTE_CACHE_LIMIT = 96;/);
assert.match(source,/map\.on\('mousemove', scheduleHover\)/);
testSelectionRefresh().then(() => console.log('PASS: immediate route removal, superseded async render cancellation, bounded hover, exact routes, native tile transition.')).catch(error => { console.error(error); process.exitCode = 1; });
