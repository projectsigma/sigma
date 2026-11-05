/* SIGMA default browser-native route reconstruction. Presentation only: numerical Network X and scores are computed upstream. */
'use strict';
let graphPromise = null;
const pathCache = new Map();
const MAX_PATHS = 256;
const MAGIC = 'SIGRTE01';

function readGraph() {
  if (!graphPromise) graphPromise = (async () => {
    const response = await fetch('data/routing-graph.bin');
    if (!response.ok) throw new Error(`Routing graph: HTTP ${response.status}`);
    const bytes = await response.arrayBuffer();
    const view = new DataView(bytes);
    if (view.byteLength < 16) throw new Error('Routing graph is truncated');
    const magic = Array.from(new Uint8Array(bytes, 0, 8), b => String.fromCharCode(b)).join('');
    if (magic !== MAGIC) throw new Error('Unexpected SIGMA routing graph version');
    const n = view.getUint32(8, true), m = view.getUint32(12, true);
    if (!n || 16 + n * 16 + m * 16 !== view.byteLength) throw new Error('Routing graph size mismatch');
    const lon = new Float64Array(n), lat = new Float64Array(n);
    let offset = 16;
    for (let i = 0; i < n; i++) {
      lon[i] = view.getFloat64(offset, true);
      lat[i] = view.getFloat64(offset + 8, true);
      offset += 16;
      if (!Number.isFinite(lon[i]) || !Number.isFinite(lat[i]))
        throw new Error('Routing graph has nonfinite coordinates');
    }
    const head = new Int32Array(n).fill(-1);
    const next = new Int32Array(m * 2), to = new Int32Array(m * 2);
    const weights = new Float64Array(m * 2);
    let k = 0;
    for (let i = 0; i < m; i++) {
      const u = view.getUint32(offset, true), v = view.getUint32(offset + 4, true);
      const w = view.getFloat64(offset + 8, true);
      offset += 16;
      if (u >= n || v >= n || u === v || !Number.isFinite(w) || w <= 0)
        throw new Error('Routing graph contains an invalid edge');
      to[k] = v; weights[k] = w; next[k] = head[u]; head[u] = k++;
      to[k] = u; weights[k] = w; next[k] = head[v]; head[v] = k++;
    }
    return {n, lon, lat, head, next, to, weights};
  })().catch(error => { graphPromise = null; throw error; });
  return graphPromise;
}

// An ordinary binary min-heap. The worker is separate from the UI thread.
function push(heap, value) {
  let i = heap.length; heap.push(value);
  while (i > 0) {
    const p = (i - 1) >> 1;
    if (heap[p][0] <= value[0]) break;
    heap[i] = heap[p]; i = p;
  }
  heap[i] = value;
}
function pop(heap) {
  const top = heap[0], tail = heap.pop();
  if (!heap.length) return top;
  let i = 0;
  while (true) {
    const left = i * 2 + 1;
    if (left >= heap.length) break;
    const right = left + 1;
    const child = right < heap.length && heap[right][0] < heap[left][0] ? right : left;
    if (heap[child][0] >= tail[0]) break;
    heap[i] = heap[child]; i = child;
  }
  heap[i] = tail;
  return top;
}
function solve(g, source, jobs) {
  const targets = new Set(jobs.map(j => j.target));
  const distance = new Float64Array(g.n).fill(Infinity);
  const previous = new Int32Array(g.n).fill(-1);
  distance[source] = 0;
  const heap = [[0, source]];
  while (heap.length && targets.size) {
    const [d, u] = pop(heap);
    if (d !== distance[u]) continue;
    targets.delete(u);
    for (let e = g.head[u]; e !== -1; e = g.next[e]) {
      const v = g.to[e], proposed = d + g.weights[e];
      if (proposed < distance[v]) {
        distance[v] = proposed; previous[v] = u;
        push(heap, [proposed, v]);
      }
    }
  }
  return jobs.map(job => {
    const target = job.target;
    if (!Number.isFinite(distance[target])) throw new Error(`Unreachable route ${source} -> ${target}`);
    // The authoritative numerical distance is Python's published X-edge distance.
    const tolerance = Math.max(0.000001, Math.abs(job.distance) * 1e-8);
    if (Math.abs(distance[target] - job.distance) > tolerance)
      throw new Error(`Route distance disagrees with SIGMA X edge (${source} -> ${target})`);
    const sequence = [target];
    let current = target;
    for (let steps = 0; current !== source && steps < g.n; steps++) {
      current = previous[current];
      if (current < 0) throw new Error('Corrupt predecessor path');
      sequence.push(current);
    }
    if (current !== source) throw new Error('Predecessor cycle detected');
    sequence.reverse();
    let coordinates = sequence.map(node => [g.lon[node], g.lat[node]]);
    if (coordinates.length === 1) coordinates = [coordinates[0], [...coordinates[0]]];
    return {id: job.id, coordinates};
  });
}

self.onmessage = async event => {
  const {requestId, jobs} = event.data || {};
  try {
    if (!Array.isArray(jobs)) throw new Error('Invalid route request');
    const g = await readGraph();
    const groups = new Map(), result = [];
    for (const j of jobs) {
      if (!Number.isSafeInteger(j.source) || !Number.isSafeInteger(j.target) ||
          j.source < 0 || j.target < 0 || j.source >= g.n || j.target >= g.n ||
          !Number.isFinite(j.distance) || j.distance < 0)
        throw new Error('Invalid routing endpoints or distance');
      const key = `${j.source}/${j.target}`;
      const saved = pathCache.get(key);
      if (saved) {
        pathCache.delete(key); pathCache.set(key, saved);
        result.push({id: j.id, coordinates: saved});
      } else {
        if (!groups.has(j.source)) groups.set(j.source, []);
        groups.get(j.source).push(j);
      }
    }
    for (const [source, group] of groups) {
      const solved = solve(g, source, group);
      for (const item of solved) {
        const original = group.find(j => j.id === item.id);
        const key = `${original.source}/${original.target}`;
        pathCache.set(key, item.coordinates);
        if (pathCache.size > MAX_PATHS) pathCache.delete(pathCache.keys().next().value);
        result.push(item);
      }
    }
    self.postMessage({requestId, routes: result});
  } catch (error) {
    self.postMessage({requestId, error: String(error && error.message || error)});
  }
};
