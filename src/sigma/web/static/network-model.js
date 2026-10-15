/* SIGMA Explorer v3.1.1: pure, testable directed X-network traversal and route expansion.
 * The returned edges preserve actual source->target orientation and coefficients.
 * No deduplication by unordered pair is permitted.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.SigmaGraph = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';
  function buildNetwork(focus, linksOf, depthOption, limits) {
    const maxDepth = depthOption === 'all' ? Infinity : Number(depthOption);
    if (!Number.isInteger(maxDepth) && maxDepth !== Infinity) throw new Error('Invalid network depth');
    const ring = new Map([[focus, 0]]);
    let frontier = [focus], truncated = false;
    for (let depth = 0; depth < maxDepth && frontier.length; depth++) {
      const next = [];
      for (const node of frontier) {
        for (const link of linksOf(node)) {
          if (ring.has(link.other)) continue;
          if (ring.size >= limits.graphNodes) { truncated = true; continue; }
          ring.set(link.other, depth + 1);
          next.push(link.other);
        }
      }
      frontier = next;
    }
    // Depth only limits which nodes are discovered. The diagram must include
    // the permitted directed edges between ALL discovered nodes, including
    // cross-links and reciprocal edges at the outermost ring. Otherwise an
    // edge from one max-depth node to another silently disappears.
    const edges = new Map();
    for (const node of ring.keys()) {
      for (const r of linksOf(node)) {
        if (!ring.has(r.other)) continue;
        for (const e of [r.out, r.in]) {
          if (!e) continue;
          const key = JSON.stringify([e.from, e.to]);
          if (!edges.has(key)) edges.set(key, {
            source: e.from, target: e.to,
            coefficient: e.coefficient, distance: e.distance, weight: e.weight,
            strength: Number.isFinite(e.coefficient) ? e.coefficient : 0,
          });
        }
      }
    }
    const ordered = [...edges.values()].sort((a, b) =>
      b.strength - a.strength || String(a.source).localeCompare(String(b.source)) || String(a.target).localeCompare(String(b.target)));
    if (ordered.length > limits.graphEdges) truncated = true;
    return {focus, ring, edges: ordered.slice(0, limits.graphEdges), truncated, direct: linksOf(focus),
      edgeCountAvailable: ordered.length};
  }
  // Route files store the path of a reciprocal edge once when the reverse edge uses
  // exactly the reversed path; such features carry reverse_of and no geometry.
  function reverseLine(geometry) {
    if (!geometry || geometry.type !== 'LineString') throw new Error('reverse_of must refer to a LineString route');
    return {type: 'LineString', coordinates: geometry.coordinates.slice().reverse()};
  }
  function expandRoutes(collection) {
    const features = collection.features || [];
    return {...collection, features: features.map(feature => {
      const ref = feature.properties ? feature.properties.reverse_of : undefined;
      if (feature.geometry || ref === undefined || ref === null) return feature;
      const base = features[ref];
      if (!base || !base.geometry) throw new Error('Route file has an invalid reverse_of reference');
      return {...feature, geometry: reverseLine(base.geometry)};
    })};
  }
  return {buildNetwork, expandRoutes};
});
