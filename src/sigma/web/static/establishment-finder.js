/* SIGMA Explorer name finder: browser-only, no dependencies. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.SigmaFinder = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';
  const normalize = value => String(value || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  // Input: Map(sector code -> [[name, tile x/y, position in tile, cluster], ...]).
  // Output: bounded name matches, with the identity of the originating tile feature.
  function search(bySector, query, limit = 30) {
    const needle = normalize(query);
    if (needle.length < 2) return {matches: [], total: 0};
    const matches = [];
    let total = 0;
    for (const [sector, rows] of bySector) {
      for (const row of rows) {
        const name = String(row[0] || '');
        const position = normalize(name).indexOf(needle);
        if (position === -1) continue;
        total++;
        matches.push({name, sector, tile: row[1], offset: row[2], cluster: row[3],
          rank: position === 0 ? 0 : 1});
      }
    }
    matches.sort((a, b) => a.rank - b.rank || a.name.localeCompare(b.name) ||
      a.sector.localeCompare(b.sector) || String(a.tile).localeCompare(String(b.tile)) || a.offset - b.offset);
    return {matches: matches.slice(0, limit), total};
  }
  return {normalize, search};
});
