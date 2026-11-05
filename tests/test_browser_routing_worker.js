/* Run with: node tests/test_browser_routing_worker.js */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const buf = new ArrayBuffer(16 + 3 * 16 + 3 * 16);
const data = new DataView(buf);
' SIGRTE01'.trim().split('').forEach((ch, i) => data.setUint8(i, ch.charCodeAt(0)));
data.setUint32(8, 3, true); data.setUint32(12, 3, true);
const coords = [[120, 15], [121, 15], [122, 15]];
coords.forEach(([lon, lat], i) => {
  data.setFloat64(16 + i * 16, lon, true);
  data.setFloat64(24 + i * 16, lat, true);
});
[[0, 1, 5], [1, 2, 4], [0, 2, 20]].forEach(([u, v, w], i) => {
  const offset = 16 + 3 * 16 + i * 16;
  data.setUint32(offset, u, true); data.setUint32(offset + 4, v, true);
  data.setFloat64(offset + 8, w, true);
});
let done;
const result = new Promise(resolve => { done = resolve; });
const self = {postMessage: message => done(message)};
const context = {self, fetch: async () => ({ok: true, arrayBuffer: async () => buf}),
  ArrayBuffer, Uint8Array, Float64Array, Int32Array, DataView, Map, Set, Number, Error};
vm.runInNewContext(
  fs.readFileSync(path.join(__dirname, '..', 'src', 'sigma', 'web', 'static', 'route-worker.js'), 'utf8'),
  context, {filename: 'route-worker.js'});
self.onmessage({data: {requestId: 1, jobs: [{id: 'a', source: 0, target: 2, distance: 9}]}});
result.then(response => {
  assert.equal(response.error, undefined);
  assert.equal(response.routes.length, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(response.routes[0].coordinates)), coords);
  console.log('Browser route worker smoke test passed.');
}).catch(e => {console.error(e); process.exitCode = 1;});
