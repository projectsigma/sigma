/* SIGMA Explorer v3.1 — reads published SIGMA artifacts only; no analytics or recomputation.
 *
 * One "network" object drives the map, the diagram and the table:
 *   focus  the selected X node (type, cluster)
 *   ring   Map(node id -> number of links from the focus)
 *   edges  preserved directed edges between the selected X nodes
 *   direct the focus's own linked clusters after the toolbar and sector filters
 * X edges are directed: an edge i -> j means sector i supplies inputs to sector j.
 */
'use strict';
// SIGMA multistep exact routes v1
// SIGMA reciprocal three-color depth routes v2
(() => {
  const $ = id => document.getElementById(id);
  const EMPTY = () => ({type: 'FeatureCollection', features: []});
  const COLOR = {both: '#7b3fa0', outgoing: '#c0392b', incoming: '#1f6fb2', focus: '#bc2735', other: '#9aa8a0'};
  const LIMIT = {graphNodes: 300, graphEdges: 1500, tableRows: 250, labelledNodes: 12};
  const showError = error => {
    $('error').hidden = false;
    $('error').textContent = `SIGMA Explorer: ${String((error && error.message) || error)}`;
  };
  if (location.protocol === 'file:') {
    showError('Open this page through "sigma view" (or any HTTP server). Browsers block data loading from file:// pages.');
    return;
  }
  if (!window.maplibregl || !window.cytoscape || !window.SigmaGraph || !window.SigmaFinder) {
    showError('The bundled map or network library did not load. Rebuild the Explorer with "sigma view <area> --refresh".');
    return;
  }

  // ------------------------------------------------------------------ state
  let map, cy, meta, tileIndex, tileKeys, popup;
  const nodeIndex = new Map();   // node id -> X node
  const pairIndex = new Map();   // node id -> Map(other id -> {other, out, in})
  const sectors = new Map();     // sector code -> {code, label, color, points, clusters}
  const selectedIconByType = new Map(); // explicit sector => filled triangle icon
  const centerIconByType = new Map(); // normal white-face icons
  const linkedCenterIconByType = new Map(); // sector-filled, blue-outlined icons
  const darkCenterIconByType = new Map(); // dark-face center icons
  const darkLinkedIconByType = new Map(); // dark linked center icons
  const hidden = new Set();      // sector codes switched off in the sector panel
  const globalSectorStrength = new Map(); // max incident IO coefficient per sector
  const state = {direction: 'both', depth: '1', top: '5', partitions: 'network'};
  let selection = null;          // {id, point}
  let network = null;
  const jsonCache = new Map();
  let finderEpoch = 0, finderTimer = null;
  let tileEpoch = 0, routeEpoch = 0, hoverEpoch = 0;
  let lastRenderedTileSignature = null; // browser-only display cache, not data cache
  let unscoredCandidates = []; // classified but NO SIGMA score, never in scored map source
  let unscoredRenderedKey = null; // only populated upon explicit user opt-in
  let ready = false;             // map layers exist
  // SIGMA_EXPLORER_LATENCY_V1: generation-guarded paints and frame-coalesced hover.
  let refreshEpoch = 0;
  let pendingHoverEvent = null;
  let hoverFrameScheduled = false;
  let lastRoutePaletteTheme = null;

  // Explicit light default: no OS dark-mode inheritance and no stored setting.
  let themeMode = 'light';
  let lastAppliedGraphTheme = null;
  function applyTheme(choice) {
    themeMode = choice === 'dark' ? 'dark' : 'light';
    const dark = themeMode === 'dark';
    document.documentElement.dataset.theme = themeMode;
    // sigma-action-label-toggle-v1: show the action, not the current theme.
    const themeToggle = $('theme-toggle');
    if (themeToggle) {
      const nextLabel = dark ? 'Light mode' : 'Dark mode';
      themeToggle.setAttribute('aria-pressed', String(dark));
      const label = themeToggle.querySelector('span');
      if (label) label.textContent = nextLabel;
      themeToggle.setAttribute('aria-label', `Switch to ${nextLabel.toLowerCase()}`);
      themeToggle.title = `Switch to ${nextLabel.toLowerCase()}`;
    }
    if (ready && map && map.getLayer && map.getLayer('centers')) {
      const ids = network ? [...network.ring.keys()] : null;
      const inNetwork = ['in', ['get', 'id'], ['literal', ids || []]];
      const face = themeMode === 'dark' ? 'dark_center_icon' : 'center_icon';
      const linked = themeMode === 'dark' ? 'dark_linked_center_icon' : 'linked_center_icon';
      map.setLayoutProperty('centers', 'icon-image', ids ?
        ['case', inNetwork, ['get', linked], ['get', face]] : ['get', face]);
    }
    if (ready && map && map.getLayer && map.getLayer('centers') && network) {
      map.setLayoutProperty('centers', 'icon-image', sigmaLinkedCenterIconExpression());
      sigmaSyncSelectedTriangle();
    }
    // MapLibre paints are independent of HTML/CSS; restyle geographic context.
    if (map && map.getLayer) {
      const paint = (layer, key, value) => {
        if (!map.getLayer(layer)) return;
        // On every selection, many of the 20 route layers have the same paint.
        // Avoid re-applying identical style expressions (MapLibre reparses them).
        if (typeof map.getPaintProperty === 'function') {
          const previous = map.getPaintProperty(layer, key);
          if (previous !== undefined && JSON.stringify(previous) === JSON.stringify(value)) return;
        }
        map.setPaintProperty(layer, key, value);
      };
      paint('background', 'background-color', dark ? '#1f1e1e' : '#f8f7f3');
      paint('boundary-fill', 'fill-color', dark ? '#262425' : '#ffffff');
      paint('boundary-line', 'line-color', dark ? '#74696b' : '#71847b');
      paint('roads-line', 'line-color', dark ? '#897f80' : '#949b9b');
      paint('roads-line', 'line-opacity', network ? (dark ? 0.29 : 0.18) : (dark ? 0.53 : 0.38));
      paint('partition-focus-line', 'line-color', dark ? '#e2a2ab' : COLOR.focus);
      // Route paint palette changes only when theme changes, never when focus changes.
      const routePaletteChanged = lastRoutePaletteTheme !== themeMode;
      if (routePaletteChanged) {
        for (let step = 1; step <= 20; step++) {
          const stem = step === 1 ? 'routes' : `routes-step-${step}`;
          paint(step === 1 ? 'routes-casing' : `${stem}-casing`, 'line-color', dark ? '#191818' : '#ffffff');
        }
      }
      // Against a dark map, muted/dark strokes avoid bright halos around
      // thousands of colored establishments. Preserve the focus outline.
      paint('establishments', 'circle-stroke-color', network ?
        ['case', ['==', ['get', 'node_id'], network.focus], dark ? '#e7a0a8' : COLOR.focus,
          dark ? '#252323' : '#ffffff'] : (dark ? '#252323' : '#ffffff'));
      paint('partition-linked-fill', 'fill-opacity', network ?
        networkDepthOpacity('node_id', 0, step => fadeByStep(dark ? 0.17 : 0.105, step), 0) :
        (dark ? 0.17 : 0.105));
      paint('partition-focus-fill', 'fill-opacity', dark ? 0.19 : 0.25);
      paint('partition-linked-line', 'line-opacity', network ?
        networkDepthOpacity('node_id', 0, step => fadeByStep(dark ? 0.70 : 0.78, step), 0) :
        (dark ? 0.70 : 0.78));
      paint('partition-focus-line', 'line-color', dark ? '#e2a2ab' : COLOR.focus);
      // red = supply, blue = use, purple = both. Same hues at every depth.
      const tripleColor = ['match', ['get', 'kind'], 'both',
        dark ? '#c9a4ed' : COLOR.both, dark ? '#ef9d8b' : COLOR.outgoing];
      if (routePaletteChanged) {
        for (let step = 1; step <= 20; step++) {
          const stem = step === 1 ? 'routes' : `routes-step-${step}`;
          paint(stem, 'line-color', tripleColor);
          paint(step === 1 ? 'routes-in' : `${stem}-in`, 'line-color', dark ? '#8cc8e9' : COLOR.incoming);
        }
        lastRoutePaletteTheme = themeMode;
      }
      paint('selected-point', 'circle-stroke-color', dark ? '#e9aa55' : '#d99d2c');
      if (state.partitions === 'network' && network) {
        paint('partition-line', 'line-color', dark ? '#716769' : '#cad6cf');
        paint('partition-line', 'line-opacity', dark ? 0.18 : 0.22);
      }
    }
    // Theme Cytoscape's canvas explicitly. No text backgrounds on any node:
    // these used to obscure the focal circle with a bright label rectangle.
    if (cy && cy.style && lastAppliedGraphTheme !== themeMode) {
      lastAppliedGraphTheme = themeMode;
      const quiet = dark ? '#a29698' : '#718879';
      const outward = dark ? '#ef9d8b' : '#b35a4f';
      const inward = dark ? '#8cc8e9' : '#39779a';
      cy.style()
        .selector('node').style({
          'border-color': dark ? '#b9a5a8' : '#746767'
        })
        .selector('node.labelled').style({
          color: dark ? '#e3d9d7' : '#665c5e',
          'text-background-opacity': 0,
          'text-outline-width': 0
        })
        .selector('node.focus').style({
          'background-color': dark ? '#dd6475' : '#bc2735',
          'border-color': dark ? '#e0b65a' : '#bc8642',
          color: dark ? '#f3eeeb' : '#5a3737',
          'text-valign': 'bottom', 'text-margin-y': 7,
          'text-background-opacity': 0
        })
        .selector('edge').style({
          'line-color': quiet, 'target-arrow-color': quiet,
          'source-arrow-color': quiet, opacity: dark ? 0.60 : 0.52
        })
        .selector('edge.mid-edge').style({opacity: dark ? 0.76 : 0.68})
        .selector('edge.outer-edge').style({opacity: dark ? 0.53 : 0.43})
        .selector('edge.focus-edge').style({opacity: 0.96})
        .selector('edge.focus-edge.outgoing').style({
          'line-color': outward, 'target-arrow-color': outward,
          'source-arrow-color': outward
        })
        .selector('edge.focus-edge.incoming').style({
          'line-color': inward, 'target-arrow-color': inward,
          'source-arrow-color': inward
        }).update();
    }
  }

  // ------------------------------------------------------------------ helpers
  const getJSON = path => {
    if (!jsonCache.has(path)) {
      jsonCache.set(path, fetch(path).then(r => {
        if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
        return r.json();
      }).catch(err => { jsonCache.delete(path); throw err; }));
    }
    return jsonCache.get(path);
  };
  const routeCache = new Map();
  const ROUTE_CACHE_LIMIT = 96; // bounded *expanded* route collections, not establishment tiles
  const getRoutes = path => {
    if (routeCache.has(path)) {
      const cached = routeCache.get(path);
      routeCache.delete(path);
      routeCache.set(path, cached); // LRU touch
      return cached;
    }
    const request = fetch(path).then(r => {
      if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
      return r.json();
    }).then(SigmaGraph.expandRoutes).catch(err => {
      if (routeCache.get(path) === request) routeCache.delete(path);
      throw err;
    });
    routeCache.set(path, request);
    if (routeCache.size > ROUTE_CACHE_LIMIT) routeCache.delete(routeCache.keys().next().value);
    return request;
  };
  const el = (tag, props = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === 'dataset') Object.assign(node.dataset, v);
      else if (k === 'style') Object.assign(node.style, v);
      else node[k] = v;
    }
    node.append(...children.filter(c => c !== null && c !== undefined));
    return node;
  };
  const isNum = v => typeof v === 'number' && Number.isFinite(v);
  const fmtNum = (v, digits = 4) => isNum(v) ? v.toLocaleString(undefined, {maximumFractionDigits: digits}) : '—';
  const fmtCoef = v => !isNum(v) ? '—' : (v === 0 || Math.abs(v) >= 0.001) ? v.toFixed(4) : v.toPrecision(2);
  // X weights (coefficient / road distance^lambda) are often far below 0.001;
  // fmtNum keeps 4 decimals and would print them as 0.
  const fmtXWeight = v => !isNum(v) ? '—' : (v === 0 || Math.abs(v) >= 0.001) ? fmtNum(v) : v.toExponential(2);
  const fmtDist = v => {
    if (!isNum(v)) return '—';
    if (meta.distance_unit !== 'm') return `${fmtNum(v, 1)} ${meta.distance_unit}`;
    return v >= 1000 ? `${(v / 1000).toFixed(v >= 10000 ? 1 : 2)} km` : `${Math.round(v)} m`;
  };
  // Refinement overlay: all help icons use one viewport-positioned tooltip.
  // Unlike a CSS-only tooltip, this is not clipped by the scrolling side panel.
  const statHelp = {'SIGMA score': 'Published SIGMA score for the selected establishment, when present; point size in the map reflects this score. Not a technical coefficient.', 'Cluster centrality': 'Published centrality of the selected sector-cluster node, distinct from individual input-output link strengths.', 'Establishments in cluster': 'Number of establishments assigned to this sector-cluster in the published result.', 'Linked clusters': 'Distinct adjacent cluster nodes in the full X graph, before the current sector, direction and strongest-link filters.', 'X edges in / out': 'Published number of directed edges entering / leaving this X node, before the current screen filters.', 'PSIC': 'Philippine Standard Industrial Classification code of the selected establishment when available. A dash means unavailable.', 'Sector basis': 'How the establishment\'s sector was assigned. An exact tag is not independent verification of actual activity. Draft concordances and inferred ownership are provisional; flagged assignments need review.'};
  const columnHelp = {'direct-cluster': 'Click a linked cluster to select it. The arrows indicate whether inputs flow from or toward the selected cluster.', 'out-a': "Outgoing technical coefficient a: the selected cluster supplies an input to this cluster, per unit of the receiving cluster's output.", 'in-a': "Incoming technical coefficient a: this cluster supplies an input to the selected cluster, per unit of the selected cluster's output.", 'road-distance': 'Published shortest-path road distance between cluster centers. Distance does not determine Strongest rankings.', 'central-cluster': 'Sector-cluster identifier; click to inspect its connected network.', 'centrality': 'Published centrality value. The list is ranked by this value, not by technical coefficient.', 'establishments': 'Count of establishments represented by the cluster in the published result.'};
  function helpIcon(label, description) {
    const tip = el('span', {className: 'control-help',
      tabIndex: 0, textContent: '?'});
    tip.dataset.tip = description;
    tip.setAttribute('role', 'note');
    tip.setAttribute('aria-label', `Help: ${label}. ${description}`);
    return tip;
  }
  function thHelp(label, key) {
    const cell = el('th', {textContent: label});
    cell.append(helpIcon(label, columnHelp[key]));
    return cell;
  }
  function initializeHelp() {
    const popup = el('div', {id: 'sigma-help-popup', className: 'sigma-help-popup'});
    popup.hidden = true;
    popup.setAttribute('role', 'tooltip');
    document.body.append(popup);
    let active = null;
    const closeHelp = () => {
      if (active) active.removeAttribute('aria-describedby');
      active = null;
      popup.hidden = true;
    };
    const openHelp = target => {
      if (!target || !target.dataset.tip) return;
      if (active && active !== target) active.removeAttribute('aria-describedby');
      active = target;
      popup.textContent = target.dataset.tip;
      popup.hidden = false;
      target.setAttribute('aria-describedby', 'sigma-help-popup');
      const rect = target.getBoundingClientRect();
      const width = popup.getBoundingClientRect().width;
      const height = popup.getBoundingClientRect().height;
      const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8));
      const below = rect.bottom + 9;
      const top = below + height <= window.innerHeight - 8 ? below :
        Math.max(8, rect.top - height - 9);
      popup.style.left = `${left}px`;
      popup.style.top = `${top}px`;
    };
    const closestTip = target => target && target.closest && target.closest('.control-help');
    document.addEventListener('pointerover', e => { const tip = closestTip(e.target); if (tip) openHelp(tip); });
    document.addEventListener('pointerout', e => {
      const tip = closestTip(e.target);
      if (tip && tip === active && !tip.contains(e.relatedTarget)) closeHelp();
    });
    document.addEventListener('focusin', e => { const tip = closestTip(e.target); if (tip) openHelp(tip); });
    document.addEventListener('focusout', e => { if (closestTip(e.target) === active) closeHelp(); });
    document.addEventListener('click', e => {
      const tip = closestTip(e.target);
      if (tip) { e.preventDefault(); e.stopPropagation(); openHelp(tip); }
      else if (active) closeHelp();
    }, true);
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeHelp(); });
    window.addEventListener('scroll', closeHelp, true);
    window.addEventListener('resize', closeHelp);
  }

  const sectorLabel = code => sectors.has(String(code)) ? sectorPresentation(sectors.get(String(code))).name : String(code);
  const sectorColor = code => (sectors.get(code) || {}).color || '#657f78';
  const nodeLabel = n => `${sectorLabel(n.type)} · ${sectorCode(n.type)} · cluster ${n.cluster}`;
  const shortLabel = n => {
    const name = sectorLabel(n.type);
    return `${name.length > 22 ? name.slice(0,19).trimEnd() + '…' : name} · ${n.cluster}`;
  };
  // sigma-explorer-tutorial-polish-20261027-v2: multiline graph names, single short code.
  const sectorCode = code => sparseSectorCode(code);
  function graphNodeLabel(n) {
    const raw = sectorLabel(n.type).trim();
    // Limit graph-glyph text only; full names remain available on hover.
    const words = raw.split(/\s+/);
    const lines = [''];
    for (const word of words) {
      const last = lines.length - 1;
      if (lines[last] && (lines[last].length + word.length + 1 > 20)) {
        if (lines.length === 2) { // no fourth line on dense cluster diagrams
          const existing = lines[last];
          lines[last] = (existing.length > 22 ? existing.slice(0, 21).trimEnd() : existing).replace(/[\s,;:-]+$/, '') + '…';
          break;
        }
        lines.push(word);
      } else lines[last] += (lines[last] ? ' ' : '') + word;
    }
    return [...lines, `C${n.cluster}`].join('\n');
  }
  const swatch = code => el('i', {className: 'swatch', style: {background: sectorColor(code)}});
  const compareNodes = (a, b) => {
    const x = nodeIndex.get(a), y = nodeIndex.get(b);
    const tx = isNaN(+x.type) ? x.type : +x.type, ty = isNaN(+y.type) ? y.type : +y.type;
    if (tx !== ty) return (typeof tx === typeof ty) ? (tx < ty ? -1 : 1) : (typeof tx === 'number' ? -1 : 1);
    return (x.cluster ?? 0) - (y.cluster ?? 0);
  };
  const setData = (name, fc) => { const s = map.getSource(name); if (s) s.setData(fc); };
  const visibility = (layer, shown) => {
    if (map.getLayer(layer)) map.setLayoutProperty(layer, 'visibility', shown ? 'visible' : 'none');
  };
  const notHidden = () => ['!', ['in', ['get', 'type'], ['literal', [...hidden]]]];

  // ------------------------------------------------------------------ network model
  function linksOf(id) {
    const rels = [];
    for (const r of (pairIndex.get(id) || new Map()).values()) {
      const other = nodeIndex.get(r.other);
      if (!other || hidden.has(other.type)) continue;
      const out = state.direction !== 'incoming' ? r.out : null;
      const inn = state.direction !== 'outgoing' ? r.in : null;
      if (!out && !inn) continue;
      const strength = Math.max(out ? (out.coefficient || 0) : 0, inn ? (inn.coefficient || 0) : 0);
      rels.push({other: r.other, out, in: inn, strength});
    }
    rels.sort((a, b) => (b.strength - a.strength) || compareNodes(a.other, b.other));
    return state.top === 'all' ? rels : rels.slice(0, Number(state.top));
  }

  function buildNetwork(focus) {
    return SigmaGraph.buildNetwork(focus, linksOf, state.depth, LIMIT);
  }

  const kindOf = (fwd, back) => (fwd && back) ? 'both' : fwd ? 'outgoing' : 'incoming';

  // ------------------------------------------------------------------ establishments (tiled)
  const toTile = (lon, lat, z) => {
    const n = 2 ** z;
    const phi = Math.max(-85.051128, Math.min(85.051128, lat)) * Math.PI / 180;
    const x = Math.floor((lon + 180) / 360 * n);
    const y = Math.floor((1 - Math.asinh(Math.tan(phi)) / Math.PI) / 2 * n);
    return [Math.max(0, Math.min(n - 1, x)), Math.max(0, Math.min(n - 1, y))];
  };

  async function loadVisiblePoints() {
    const epoch = ++tileEpoch;
    // Reassert the user-controlled gate before async tile loading or redraws.
    // A scored selection suppresses unscored points even if opt-in is checked.
    syncUnscoredOverlay();
    const b = map.getBounds(), z = tileIndex.zoom;
    const [xa, ya] = toTile(b.getWest(), b.getNorth(), z);
    const [xb, yb] = toTile(b.getEast(), b.getSouth(), z);
    const keys = [];
    let total = 0;
    const take = key => { const c = tileIndex.tiles[key]; if (c) { keys.push(key); total += c; } };
    if ((xb - xa + 1) * (yb - ya + 1) > tileKeys.length) {
      for (const key of tileKeys) {
        const [x, y] = key.split('/').map(Number);
        if (x >= xa && x <= xb && y >= ya && y <= yb) take(key);
      }
    } else {
      for (let x = xa; x <= xb; x++) for (let y = ya; y <= yb; y++) take(`${x}/${y}`);
    }
    if (!meta.has_points) {
      lastRenderedTileSignature = null;
      unscoredCandidates = [];
      unscoredRenderedKey = null;
      setData('unscored-points', EMPTY());
      visibility('unclustered-establishments', false);
      setData('points', EMPTY());
      visibility('overview-counts', false);
      updateStatus(meta.profile === 'public' ? 'Public profile: establishment-level locations are not included. Select a cluster center.' : null);
      return;
    }
    if (total > meta.point_budget) {
      lastRenderedTileSignature = null;
      unscoredCandidates = [];
      unscoredRenderedKey = null;
      setData('unscored-points', EMPTY());
      visibility('unclustered-establishments', false);
      setData('points', EMPTY());
      visibility('overview-counts', true);
      updateStatus(`${total.toLocaleString()} establishments in view (more than ${meta.point_budget.toLocaleString()}). The green shading shows where they are; zoom in to see individual establishments.`);
      return;
    }
    visibility('overview-counts', false);
    // A pan within the same tile set cannot change the source features.
    // Reusing that GeoJSON avoids a costly MapLibre source reparse/repaint.
    const signature = `${z}:${keys.join('|')}`;
    if (signature === lastRenderedTileSignature) { updateStatus(); return; }
    // As soon as the visible tile set changes, remove stale points while the
    // new tile data load. A superseded response cannot reinstate them (tileEpoch).
    // Invalidate the old signature too, so a rapid pan-back cannot reuse an emptied source.
    lastRenderedTileSignature = '';
    setData('points', EMPTY());
    unscoredCandidates = [];
    unscoredRenderedKey = null;
    setData('unscored-points', EMPTY());
    try {
      const groups = await Promise.all(keys.map(key => getJSON(`data/tiles/${z}/${key}.geojson`)));
      if (epoch !== tileEpoch) return;
      const scoredFeatures = [];
      const classifiedOnly = [];
      for (const group of groups) for (const feature of (group.features || [])) {
        if (feature.properties && feature.properties.unclustered === true) {
          // Only classified-but-unscored point rows may enter the optional source.
          feature.properties.unscored_icon = unscoredSectorIcons.get(String(feature.properties.type)) ||
            'sigma-unscored-triangle-default';
          classifiedOnly.push(feature);
        } else scoredFeatures.push(feature);
      }
      unscoredCandidates = classifiedOnly;
      // Expensive source parse is reduced: the scored source never receives unscored POIs.
      setData('points', {type: 'FeatureCollection', features: scoredFeatures});
      lastRenderedTileSignature = signature;
      syncUnscoredOverlay();
      updateStatus();
    } catch (err) { if (epoch === tileEpoch) showError(err); }
  }

  function updateStatus(message) {
    if (message) { $('map-status').textContent = message; return; }
    if (!selection) {
      $('map-status').textContent = 'Click an establishment or a cluster center to show the clusters linked to it in network X.';
      return;
    }
    const n = nodeIndex.get(selection.id);
    if (!n) {
      $('map-status').textContent = `Selected: ${selection.point?.name || 'Establishment'}. Classified establishment; no network cluster or SIGMA score.`;
      return;
    }
    const what = selection.point ? `${selection.point.name} (cluster ${shortLabel(n)})` : nodeLabel(n);
    const count = network ? network.direct.length : 0;
    $('map-status').textContent = `Selected: ${what}. ${count} directly linked cluster${count === 1 ? '' : 's'}; lines follow SIGMA's road paths.`;
  }

  // ------------------------------------------------------------------ map emphasis
  // SIGMA toolbar overlay: normal cluster centers are optional, but a selected
  // network still reveals only its cluster centers (for currently visible sectors).
  function updateCenterVisibility() {
    if (!ready) return;
    const all = $('show-centers').checked;
    const ids = network ? [...network.ring.keys()] : [];
    visibility('centers', all || ids.length > 0);
    map.setFilter('centers', all ? notHidden() :
      ['all', notHidden(), ['in', ['get', 'id'], ['literal', ids]]]);
    // Keep the focused larger triangle, but obey sector visibility here too.
    if (map.getLayer('selected-center')) map.setFilter('selected-center', notHidden());
  }

  // SIGMA SELECTED-NETWORK SCOPE / DIRECTIONAL CENTER OUTLINES V2.
  // This is a visual/interaction transform of existing Network X edges.
  // No new edges, clusters, scores or paths are constructed.
  function selectableMapFeature(feature) {
    if (!feature || !feature.layer || !feature.properties) return false;
    if (!network) return true;
    const p = feature.properties;
    if (feature.layer.id === 'unclustered-establishments') return false;
    const id = feature.layer.id === 'centers' ? p.id :
      feature.layer.id === 'establishments' ? p.node_id : null;
    return id != null && network.ring.has(String(id));
  }

  const sigmaTriangleImageCache = new Map();
  let sigmaTriangleStyleByNode = new Map();

  function computeNetworkTriangleStyles() {
    const result = new Map();
    if (!network) return result;
    const edges = network.edges || [];
    const directed = new Set(edges.map(e => JSON.stringify([e.source, e.target])));
    const peak = Math.max(1e-12, ...edges.map(e => Math.max(0, Number(e.coefficient) || 0)));
    function keep(nodeId, candidate) {
      const prev = result.get(nodeId);
      if (!prev || candidate.strength > prev.strength ||
          (candidate.strength === prev.strength &&
           (candidate.depth < prev.depth ||
            (candidate.depth === prev.depth && candidate.key < prev.key))))
        result.set(nodeId, candidate);
    }
    for (const e of edges) {
      const a = network.ring.get(e.source), b = network.ring.get(e.target);
      if (a === undefined || b === undefined) continue;
      const near = routeAnchor(e.source, e.target, network.ring);
      const far = near === e.source ? e.target : e.source;
      const reciprocal = directed.has(JSON.stringify([e.target, e.source]));
      const kind = reciprocal ? 'both' : (e.source === near ? 'outgoing' : 'incoming');
      const strength = Math.max(0, Number(e.coefficient) || 0);
      const depth = Math.max(1, a, b);
      // Exactly the unscaled route width from showRoutes() at this step.
      const wn = Math.min(1, Math.sqrt(strength / peak));
      const routeWidth = Math.max(0.26, 1 / Math.sqrt(depth)) * (0.7 + 1.5 * wn);
      const candidate = {kind, strength, depth, routeWidth,
        key: JSON.stringify([e.source, e.target])};
      // Linked nodes inherit the strongest incoming *displayed network route*
      // from the previous ring; same-depth cross-links are not used as ancestry.
      if (network.ring.get(near) < network.ring.get(far)) keep(far, candidate);
      // The selected focus has no parent link; use its strongest direct edge.
      if (e.source === network.focus || e.target === network.focus)
        keep(network.focus, candidate);
    }
    return result;
  }

  function sigmaTriangleIcon(node, selected, theme) {
    const link = sigmaTriangleStyleByNode.get(node.id);
    const palette = theme === 'dark' ?
      {outgoing: '#ef9d8b', incoming: '#8cc8e9', both: '#c9a4ed'} :
      {outgoing: COLOR.outgoing, incoming: COLOR.incoming, both: COLOR.both};
    const border = link ? palette[link.kind] : sectorColor(node.type);
    const scale = selected ? 1.08 : 0.8;
    // Convert displayed line pixels into source-icon pixels at map zoom 15.
    const rawWidth = link ? link.routeWidth / scale : 2.0;
    const stroke = Math.max(0.85, Math.min(3.7, Math.round(rawWidth * 4) / 4));
    const key = [String(node.type), selected, theme, border, stroke].join('|');
    if (sigmaTriangleImageCache.has(key)) return sigmaTriangleImageCache.get(key);
    const size = selected ? 36 : 32;
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = size;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw Error('Cannot render triangle: canvas 2D unavailable.');
    ctx.fillStyle = sectorColor(node.type);
    ctx.strokeStyle = border;
    ctx.lineWidth = stroke;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    if (selected) { ctx.moveTo(5, 6); ctx.lineTo(31, 6); ctx.lineTo(18, 32); }
    else { ctx.moveTo(5, 6); ctx.lineTo(27, 6); ctx.lineTo(16, 27); }
    ctx.closePath(); ctx.fill(); ctx.stroke();
    const name = `sigma-link-outline-v2-${sigmaTriangleImageCache.size}`;
    map.addImage(name, ctx.getImageData(0, 0, size, size));
    sigmaTriangleImageCache.set(key, name);
    return name;
  }

  function sigmaLinkedCenterIconExpression() {
    const base = themeMode === 'dark' ? 'dark_center_icon' : 'center_icon';
    if (!network) return ['get', base];
    const pairs = [];
    for (const id of network.ring.keys()) {
      if (id === network.focus) continue;
      const node = nodeIndex.get(id);
      if (node) pairs.push(id, sigmaTriangleIcon(node, false, themeMode));
    }
    return pairs.length ? ['match', ['get', 'id'], ...pairs, ['get', base]] : ['get', base];
  }

  function sigmaSyncSelectedTriangle() {
    if (!map || !map.getSource || !map.getSource('selected-center')) return;
    const node = selection && nodeIndex.get(selection.id);
    const valid = node && isNum(node.lon) && isNum(node.lat);
    setData('selected-center', {type: 'FeatureCollection', features: valid ? [{
      type: 'Feature',
      properties: {type: node.type, icon: sigmaTriangleIcon(node, true, themeMode)},
      geometry: {type: 'Point', coordinates: [node.lon, node.lat]}
    }] : []});
  }

  // SIGMA Explorer depth-based map opacity v1
  // The graph's BFS rings are the only source of truth for map depth.
  // The selected cluster is handled separately so it stays prominent.
  function fadeByStep(base, step) {
    // Attenuate by the inverse square root of the BFS distance from focus.
    // The first linked ring retains base opacity; deeper rings remain legible.
    return Number((base / Math.sqrt(Math.max(1, step))).toFixed(6));
  }

  function networkDepthOpacity(property, focusOpacity, linkedOpacity, outsideOpacity) {
    if (!network) return outsideOpacity;
    // A single MapLibre match expression groups IDs by distance; it does not
    // mutate the underlying tiles, centers, or polygon geometries.
    const grouped = new Map();
    for (const [id, step] of network.ring) {
      if (step < 1) continue;
      if (!grouped.has(step)) grouped.set(step, []);
      grouped.get(step).push(id);
    }
    const paint = ['match', ['get', property], network.focus, focusOpacity];
    for (const [step, ids] of [...grouped.entries()].sort((a, b) => a[0] - b[0])) {
      paint.push(ids, linkedOpacity(step));
    }
    paint.push(outsideOpacity);
    return paint;
  }

  // Fail closed on every redraw: opt-in AND classified-but-unscored AND
  // currently enabled sector AND no selected scored X network are required.
  // Fail-closed, data-level opt-in. The unscored GeoJSON source is EMPTY
  // until the user explicitly checks the box. Styling cannot leak these places.
  function syncUnscoredOverlay() {
    if (!map || !map.getLayer || !map.getLayer('unclustered-establishments')) return;
    const control = $('show-unscored');
    const enabled = Boolean(control && control.checked && !control.disabled && !network);
    const sectorKey = [...hidden].sort().join('|');
    const sourceKey = enabled ? `${lastRenderedTileSignature || ''}|${sectorKey}` : null;
    if (unscoredRenderedKey !== sourceKey) {
      const locations = enabled ? unscoredCandidates.filter(f =>
        f.properties && !hidden.has(String(f.properties.type))) : [];
      setData('unscored-points', {type: 'FeatureCollection', features: locations});
      unscoredRenderedKey = sourceKey;
    }
    // Two independent gates: no data if off, AND layer visibility none.
    visibility('unclustered-establishments', enabled);
    const key = $('unclustered-key');
    if (key) key.hidden = !enabled;
  }

  function applyEmphasis() {
    const ids = network ? [...network.ring.keys()] : null;
    const focus = network ? network.focus : '';
    const inNet = ['in', ['get', 'node_id'], ['literal', ids || []]];
    const isFocus = ['==', ['get', 'node_id'], focus];
    map.setPaintProperty('establishments', 'circle-opacity', ids ?
      networkDepthOpacity('node_id', 0.96, step => fadeByStep(0.90, step), 0.025) : 0.78);
    map.setPaintProperty('establishments', 'circle-stroke-opacity', ids ?
      networkDepthOpacity('node_id', 1, step => fadeByStep(1, step), 0.025) : 1);
    map.setPaintProperty('establishments', 'circle-stroke-width', ids ? ['case', isFocus, 0.9, 0.35] : 0.35);
    map.setPaintProperty('establishments', 'circle-stroke-color', ids ? ['case', isFocus, COLOR.focus, '#ffffff'] : '#ffffff');
    const centerIn = ['in', ['get', 'id'], ['literal', ids || []]];
    // Linked clusters are sector-filled with thin blue outlines. The focused
    // triangle is handled by the larger selected-center symbol above this layer.
    // Alternate icon assets remove white triangle interiors in dark mode;
    // linked and focused sector colors remain intact.
    const baseIcon = themeMode === 'dark' ? 'dark_center_icon' : 'center_icon';
    const connectedIcon = themeMode === 'dark' ? 'dark_linked_center_icon' : 'linked_center_icon';
    // One icon layout update per selection, not two consecutive reparses.
    map.setLayoutProperty('centers', 'icon-image', ids && network ?
      sigmaLinkedCenterIconExpression() : ['get', baseIcon]);
    map.setPaintProperty('centers', 'icon-opacity', ids ?
      networkDepthOpacity('id', 0, step => fadeByStep(1, step), 0.16) : 1);
    map.setFilter('establishments', ['all', ['!=', ['get', 'unclustered'], true], notHidden()]);
    // Unscored overlay is opt-in. A selected X cluster (or scored place)
    // hides it completely; clearing selection restores the user's choice.
    syncUnscoredOverlay();
    updateCenterVisibility();
    if (map.getLayer('roads-line')) map.setPaintProperty('roads-line', 'line-opacity', ids ? 0.18 : 0.38);
    if (map.getLayer('roads-line') && themeMode === 'dark')
      map.setPaintProperty('roads-line', 'line-opacity', ids ? 0.29 : 0.53);
    updatePartitions();
    applyTheme(themeMode); // Restore theme-aware paints after each selection refresh.
  }

  function updatePartitions() {
    const mode = state.partitions;
    const show = mode === 'all' || (mode === 'network' && !!network);
    visibility('partition-fill', show);
    visibility('partition-line', show);
    // Foreground geometry is split into separate layers: a selected polygon
    // always draws ABOVE linked polygons, which draw above nearly-white context.
    const foreground = mode === 'network' && !!network;
    for (const layer of ['partition-linked-fill', 'partition-linked-line',
                         'partition-focus-fill', 'partition-focus-line']) {
      visibility(layer, foreground);
    }
    if (!show) return;
    const color = ['match', ['get', 'type'], ...sectorMatchPairs(), '#657f78'];
    if (mode === 'network') {
      const focus = ['==', ['get', 'node_id'], network.focus];
      const inside = ['in', ['get', 'node_id'], ['literal', [...network.ring.keys()]]];
      const outside = ['all', notHidden(), ['!', inside]];
      const linked = ['all', notHidden(), inside, ['!', focus]];
      // Context: paper-white fill, extremely faint neutral boundaries.
      map.setFilter('partition-fill', outside);
      map.setFilter('partition-line', outside);
      map.setPaintProperty('partition-fill', 'fill-opacity', 0);
      map.setPaintProperty('partition-line', 'line-color', '#cad6cf');
      map.setPaintProperty('partition-line', 'line-width', 0.32);
      map.setPaintProperty('partition-line', 'line-opacity', 0.22);
      // Linked clusters stay legible in their sector colors.
      map.setFilter('partition-linked-fill', linked);
      map.setFilter('partition-linked-line', linked);
      // The selected cluster is always drawn last, even with overlapping sectors.
      map.setFilter('partition-focus-fill', focus);
      map.setFilter('partition-focus-line', focus);
    } else {
      map.setFilter('partition-fill', notHidden());
      map.setFilter('partition-line', notHidden());
      map.setPaintProperty('partition-fill', 'fill-opacity', 0.022);
      map.setPaintProperty('partition-line', 'line-color', color);
      map.setPaintProperty('partition-line', 'line-width', 0.45);
      map.setPaintProperty('partition-line', 'line-opacity', 0.5);
    }
  }

  // Render the directed X edges in the selected network, not only the focus's
  // immediate neighbors. Geometry is read from each edge's published source
  // cluster route file; no geographic lines are inferred or recomputed.
  // SIGMA reciprocal three-color depth routes v2.
  // Relationship colors are defined relative to the endpoint closer to focus:
  // outgoing/supply = red, incoming/use = blue, genuine reciprocal = purple.
  // When rings tie, anchor the unordered pair by stable node ID. This is a
  // display convention only; source/target are always the true directed X edge.
  // Published route geometry is read unchanged from the source node's route file.
  const routePairKey = (a, b) => JSON.stringify([a, b].sort());
  const sameCoords = (a, b, reverse = false) => {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) {
      const p = a[i], q = b[reverse ? b.length - 1 - i : i];
      if (!Array.isArray(p) || !Array.isArray(q) || p.length !== q.length) return false;
      for (let j = 0; j < p.length; j++) if (p[j] !== q[j]) return false;
    }
    return true;
  };
  const sameRoadGeometry = (a, b) => {
    if (!a || !b || a.type !== b.type) return false;
    if (a.type === 'LineString') return sameCoords(a.coordinates, b.coordinates) ||
      sameCoords(a.coordinates, b.coordinates, true);
    return JSON.stringify(a.coordinates) === JSON.stringify(b.coordinates);
  };
  const routeAnchor = (a, b, ring) => {
    const da = ring.get(a), db = ring.get(b);
    return da < db ? a : db < da ? b : String(a) < String(b) ? a : b;
  };
  async function showRoutes() {
    const epoch = ++routeEpoch;
    ++hoverEpoch;
    setData('route-hover', EMPTY());
    if (!network || !network.edges.length) { setData('routes', EMPTY()); return; }
    const current = network;
    const strongest = Math.max(1e-12, ...current.edges.map(e => e.strength));
    const bySource = new Map();
    for (const edge of current.edges) {
      const a = current.ring.get(edge.source), b = current.ring.get(edge.target);
      const source = nodeIndex.get(edge.source);
      if (!source || !source.route_file || a === undefined || b === undefined) continue;
      const pairKey = routePairKey(edge.source, edge.target);
      const anchor = routeAnchor(edge.source, edge.target, current.ring);
      const depth = Math.max(1, a, b);
      const descriptor = {edge, anchor, depth, pairKey};
      if (!bySource.has(source.route_file)) bySource.set(source.route_file, []);
      bySource.get(source.route_file).push(descriptor);
    }
    const entries = [...bySource.entries()];
    const output = [];
    let cursor = 0;
    // Fetch at most eight route files simultaneously; cached files are reused.
    async function worker() {
      while (cursor < entries.length) {
        const [file, wanted] = entries[cursor++];
        const fc = await getRoutes(file);
        if (epoch !== routeEpoch) return;
        const needed = new Map(wanted.map(d => [JSON.stringify([d.edge.source, d.edge.target]), d]));
        for (const f of (fc.features || [])) {
          const p = f.properties || {};
          const descriptor = needed.get(JSON.stringify([p.from, p.to]));
          if (!descriptor || !f.geometry) continue;
          const c = isNum(p.coefficient) ? Math.max(0, p.coefficient) : 0;
          output.push({...f, properties: {...p,
            depth: descriptor.depth, anchor: descriptor.anchor,
            pair_key: descriptor.pairKey,
            kind: p.from === descriptor.anchor ? 'outgoing' : 'incoming',
            wn: Math.min(1, Math.sqrt(c / strongest))}});
        }
      }
    }
    try {
      await Promise.all(Array.from({length: Math.min(8, entries.length)}, worker));
      if (epoch !== routeEpoch) return;
      // A reciprocal pair has two independent directed X edges. Their road
      // paths may or may not coincide, and both coefficients must survive.
      // Only combine features when their published geometries truly coincide.
      const byPair = new Map();
      for (const feature of output) {
        const key = feature.properties.pair_key;
        if (!byPair.has(key)) byPair.set(key, []);
        byPair.get(key).push(feature);
      }
      const features = [];
      for (const group of byPair.values()) {
        const byDirected = new Map(group.map(f => [JSON.stringify([f.properties.from, f.properties.to]), f]));
        for (const f of group) {
          const p = f.properties;
          const inverse = byDirected.get(JSON.stringify([p.to, p.from]));
          if (!inverse || inverse === f) {
            features.push(f);
            continue;
          }
          // Both directed connections are modeled. Never infer reciprocity
          // solely from unrelated routes sharing the same physical roadway.
          const q = inverse.properties;
          const separate = !sameRoadGeometry(f.geometry, inverse.geometry);
          const enhanced = {...f, properties: {...p, kind: 'both', reciprocal: true,
            reverse_coefficient: q.coefficient, reverse_weight: q.weight,
            reverse_distance: q.distance, separate_paths: separate}};
          if (separate || p.from === p.anchor) features.push(enhanced);
        }
      }
      // Actual overpainting order is determined by route layers, not array order:
      // the outermost depth is drawn first and direct links are drawn last.
      features.sort((a, b) => b.properties.depth - a.properties.depth ||
        a.properties.wn - b.properties.wn ||
        String(a.properties.pair_key).localeCompare(String(b.properties.pair_key)));
      setData('routes', {type: 'FeatureCollection', features});
    } catch (err) {
      if (epoch === routeEpoch) { setData('routes', EMPTY()); showError(err); }
    }
  }

  async function highlightRoute(other, direction = null) {
    const epoch = ++hoverEpoch;
    const n = network && nodeIndex.get(network.focus);
    if (!other || !n || !n.route_file) { setData('route-hover', EMPTY()); return; }
    try {
      const fc = await getRoutes(n.route_file);
      if (epoch !== hoverEpoch || !network || network.focus !== n.id) return;
      setData('route-hover', {type: 'FeatureCollection', features: fc.features.filter(f =>
        f.properties.other === other && (!direction || f.properties.direction === direction))});
    } catch (err) { if (epoch === hoverEpoch) showError(err); }
  }

  // ------------------------------------------------------------------ side panel
  function stat(label, value) {
    const header = el('span', {className: 'stat-label'}, el('span', {textContent: label}));
    if (statHelp[label]) header.append(helpIcon(label, statHelp[label]));
    return el('div', {className: 'stat'}, header, el('strong', {textContent: value}));
  }

  function renderSelection() {
    const hasCluster = !!(selection && nodeIndex.has(selection.id));
    $('connections-section').hidden = !hasCluster;
    $('central-section').hidden = !!selection;
    $('selection-actions').hidden = !hasCluster;
    if (!selection) {
      $('selected-code').textContent = '';
      $('place-name').textContent = 'No selection';
      $('place-description').textContent = 'Click an establishment or a cluster center on the map. Its cluster and the clusters linked to it in network X are then shown on the map and below.';
      $('stats').replaceChildren();
      return;
    }
    const n = nodeIndex.get(selection.id), p = selection.point;
    if (!n) {
      $('selected-code').textContent = sectorCode(p.type);
      $('place-name').textContent = p.name;
      $('place-description').textContent = `${sectorLabel(p.type)} · Classified establishment without a qualifying network cluster. Hollow circle; SIGMA score not available.`;
      $('stats').replaceChildren(
        stat('SIGMA score', 'N/A'), stat('Cluster centrality', 'N/A'),
        stat('Linked clusters', 'N/A'), stat('PSIC', p.psic || '—'),
        stat('Sector basis', p.basis || '—'));
      return;
    }
    $('selected-code').textContent = `${sectorCode(n.type)} · Cluster ${n.cluster}`;
    $('place-name').textContent = p ? p.name : nodeLabel(n);
    $('place-description').textContent = p ? sectorLabel(p.type) : 'Cluster center (network 1-median of the cluster)';
    const linked = (pairIndex.get(n.id) || new Map()).size;
    $('stats').replaceChildren(
      stat('SIGMA score', p ? fmtNum(p.score) : '—'),
      stat('Cluster centrality', fmtNum(n.centrality)),
      stat('Establishments in cluster', fmtNum(n.members, 0)),
      stat('Linked clusters', fmtNum(linked, 0)),
      stat('X edges in / out', `${fmtNum(n.in_degree, 0)} / ${fmtNum(n.out_degree, 0)}`),
      stat('PSIC', p && p.psic ? String(p.psic) : '—'),
      stat('Sector basis', p && p.basis ? String(p.basis) : '—'),
    );
  }

  function renderConnections() {
    const box = $('connections');
    box.replaceChildren();
    $('edge-count').textContent = '';
    if (!network) return;
    const rows = network.direct;
    $('edge-count').textContent = `${rows.length} linked cluster${rows.length === 1 ? '' : 's'}`;
    if (!rows.length) {
      box.append(el('p', {className: 'more', textContent: 'No linked clusters with the current direction and sector filters.'}));
      return;
    }
    const head = el('tr', {},
      thHelp('Cluster', 'direct-cluster'),
      thHelp('→ a', 'out-a'),
      thHelp('← a', 'in-a'),
      thHelp('Road', 'road-distance'));
    const body = el('tbody');
    for (const r of rows.slice(0, LIMIT.tableRows)) {
      const n = nodeIndex.get(r.other);
      const kind = kindOf(!!r.out, !!r.in);
      const button = el('button', {type: 'button', className: 'link-button', title: 'Select this cluster'},
        el('span', {className: `dir ${kind}`, textContent: kind === 'both' ? '⇄' : kind === 'outgoing' ? '→' : '←'}),
        swatch(n.type), el('span', {textContent: nodeLabel(n)}));
      button.addEventListener('click', () => selectNode(r.other, null, {fly: true}));
      const tr = el('tr', {},
        el('td', {}, button),
        el('td', {textContent: r.out ? fmtCoef(r.out.coefficient) : ''}),
        el('td', {textContent: r.in ? fmtCoef(r.in.coefficient) : ''}),
        el('td', {textContent: fmtDist((r.out || r.in).distance)}));
      tr.addEventListener('mouseenter', () => highlightRoute(r.other));
      tr.addEventListener('mouseleave', () => highlightRoute(null));
      body.append(tr);
    }
    box.append(el('table', {className: 'links'}, el('thead', {}, head), body));
    if (rows.length > LIMIT.tableRows) {
      box.append(el('p', {className: 'more', textContent: `Showing the ${LIMIT.tableRows} strongest of ${rows.length} links.`}));
    }
  }

  function renderCentral() {
    const top = [...nodeIndex.values()].filter(n => isNum(n.centrality) && !hidden.has(n.type))
      .sort((a, b) => b.centrality - a.centrality).slice(0, 12);
    const body = el('tbody');
    for (const n of top) {
      const button = el('button', {type: 'button', className: 'link-button'}, swatch(n.type), el('span', {textContent: nodeLabel(n)}));
      button.addEventListener('click', () => selectNode(n.id, null, {fly: true}));
      body.append(el('tr', {}, el('td', {}, button), el('td', {textContent: fmtNum(n.centrality)}), el('td', {textContent: fmtNum(n.members, 0)})));
    }
    $('central').replaceChildren(el('table', {className: 'links'},
      el('thead', {}, el('tr', {}, thHelp('Cluster', 'central-cluster'), thHelp('Centrality', 'centrality'), thHelp('Establishments', 'establishments'))),
      body));
  }

  // sigma-explorer-graph-legibility-20261020-v7: legible multi-ring Cytoscape overview and near-focus inspection.
  // ------------------------------------------------------------------ network diagram
  // Keep the network graph readable regardless of Cytoscape's fit/zoom.
  // Sizes are screen pixels converted to Cytoscape's model coordinates;
  // topology, graph positions, sector colors, and traversal are unchanged.
  // The graph can span from a handful of clusters to hundreds.  Remember
  // the fitted zoom so an ordinary wheel gesture changes glyph size gently,
  // without bringing back oversized nodes in small networks.
  let graphGlyphFitZoom = 1;
  function syncNetworkGlyphs() {
    if (!cy || !network) return;
    const count = cy.nodes().length;
    const zoom = cy.zoom();
    if (!count || !(zoom > 0)) return;
    // Wheel zoom moves nodes apart/together; labels and circles respond too.
    // Compensate for most (not all) of the zoom; clamp screen-size changes.
    const relativeZoom = zoom / Math.max(graphGlyphFitZoom, 1e-6);
    const glyphScale = Math.max(0.78, Math.min(1.50, Math.pow(relativeZoom, 0.35)));
    const px = size => size * glyphScale / zoom;
    const small = count <= 12;
    const dense = count > 25;
    const nodeSize = small ? 17 : count <= 25 ? 13 : count <= 80 ? 8 : 6;
    const focusSize = small ? 23 : count <= 25 ? 18 : count <= 80 ? 14 : 12;
    const labelSize = small ? 10.4 : count <= 25 ? 9.8 : 9.2;

    cy.batch(() => {
      cy.nodes().style({width: px(nodeSize), height: px(nodeSize),
        'border-width': px(dense ? 0.8 : 1.25)});
      cy.nodes('[ring >= 2]').style({width: px(Math.max(6, nodeSize - 1)),
        height: px(Math.max(6, nodeSize - 1))});
      cy.nodes('.labelled').style({'font-size': px(labelSize), 'text-margin-y': px(6), 'text-max-width': px(122)});
      cy.nodes('.focus').style({width: px(focusSize), height: px(focusSize),
        'border-width': px(1.6), 'font-size': px(small ? 10.5 : 9.5),
        'text-margin-y': px(6)});
      cy.edges().forEach(edge => {
        const strength = Number(edge.data('wn')) || 0;
        const major = edge.hasClass('focus-edge');
        const outer = edge.hasClass('outer-edge');
        edge.style({width: px(major ? 1.3 + 0.7 * strength :
          dense ? 0.42 + 0.2 * strength : 0.7 + 0.4 * strength),
          opacity: major ? 0.88 : dense ? (outer ? 0.10 : 0.22) : 0.5,
          'arrow-scale': major ? 0.65 : dense ? 0.48 : 0.65});
      });
    });
  }

  function drawGraph() {
    cy.elements().remove();
    $('graph-tip').hidden = true;
    $('network-empty').hidden = !!network;
    if (!network) { $('graph-count').textContent = ''; return; }
    const ids = [...network.ring.keys()].sort((a, b) =>
      (network.ring.get(a) - network.ring.get(b)) || compareNodes(a, b));
    const maxRing = Math.max(...network.ring.values());
    const strongest = Math.max(1e-12, ...network.edges.map(e => e.strength));
    const elements = ids.map(id => {
      const n = nodeIndex.get(id), ring = network.ring.get(id);
      return {group: 'nodes', data: {id, label: graphNodeLabel(n), color: sectorColor(n.type), ring, level: maxRing - ring + 1},
        classes: id === network.focus ? 'focus' : ''};
    });
    const directedIds = new Set(network.edges.map(e => `${e.source}\u0000${e.target}`));
    network.edges.forEach((e, i) => {
      if (!network.ring.has(e.source) || !network.ring.has(e.target)) return;
      const outgoing = e.source === network.focus;
      const incoming = e.target === network.focus;
      const reciprocal = directedIds.has(`${e.target}\u0000${e.source}`);
      const near = Math.min(network.ring.get(e.source), network.ring.get(e.target));
      const depthClass = near <= 1 ? 'mid-edge' : 'outer-edge';
      const classes = [outgoing || incoming ? 'focus-edge' : '', outgoing ? 'outgoing' : '',
        incoming ? 'incoming' : '', reciprocal ? 'reciprocal' : '', depthClass].join(' ');
      elements.push({group: 'edges', data: {id: `e${i}`, source: e.source, target: e.target,
        wn: Math.sqrt(e.strength / strongest), coefficient: e.coefficient,
        distance: e.distance, weight: e.weight}, classes});
    });
    cy.add(elements);
    // Label only the focus in dense networks; other nodes retain hover details.
    if (ids.length <= LIMIT.labelledNodes) cy.nodes().addClass('labelled');
    else cy.nodes().filter(n => Number(n.data('ring')) <= 1).addClass('labelled');
    cy.layout({name: 'concentric', concentric: n => n.data('level'), levelWidth: () => 1, minNodeSpacing: 16,
      startAngle: 1.5 * Math.PI, clockwise: true, equidistant: true, avoidOverlap: true, animate: false, fit: true, padding: 26}).run();
    // Default to Fit graph for every selection, never Focus nearby.
    cy.resize();
    cy.fit(undefined, 24);
    graphGlyphFitZoom = cy.zoom();
    syncNetworkGlyphs();
    const linkCount = cy.edges().length;
    $('graph-count').textContent = `${ids.length} clusters · ${linkCount} directed edges${network.truncated ? ' (display limited)' : ''}`;
  }

  function graphTip(event, show) {
    const tip = $('graph-tip');
    if (!show) { tip.hidden = true; return; }
    const n = nodeIndex.get(event.target.id());
    const ring = network ? network.ring.get(n.id) : 0;
    tip.replaceChildren(el('div', {className: 'popup-title', textContent: nodeLabel(n)}),
      el('div', {className: 'popup-row', textContent: `${fmtNum(n.members, 0)} establishments · centrality ${fmtNum(n.centrality)}`}),
      el('div', {className: 'popup-row', textContent: ring === 0 ? 'Selected cluster' : `${ring} link${ring === 1 ? '' : 's'} from the selected cluster`}));
    const pos = event.target.renderedPosition();
    tip.style.left = `${Math.min(pos.x + 14, $('network').clientWidth - 200)}px`;
    tip.style.top = `${pos.y + 12}px`;
    tip.hidden = false;
  }

  // ------------------------------------------------------------------ area-wide establishment finder
  // Search only local-profile bundles. Each index row points to the exact
  // existing tiled point, avoiding duplicate point metadata and fake locations.
  function initializeFinder() {
    const query = $('finder-query'), filter = $('finder-sector');
    for (const sector of sectors.values()) {
      filter.append(el('option', {value: sector.code, textContent: `${sectorPresentation(sector).name} · ${sectorPresentation(sector).code}`}));
    }
    if (!meta.has_establishment_finder || !meta.has_points) {
      query.disabled = true;
      filter.disabled = true;
      $('finder-status').textContent = meta.profile === 'public'
        ? 'Unavailable in the public profile (names and locations are excluded).'
        : 'No searchable establishments in this area.';
      return;
    }
    const later = () => {
      ++finderEpoch; // Invalidate pending earlier searches immediately on input.
      if (finderTimer) clearTimeout(finderTimer);
      finderTimer = setTimeout(runFinder, 200);
    };
    query.addEventListener('input', later);
    filter.addEventListener('change', later);
    query.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        if (finderTimer) clearTimeout(finderTimer);
        runFinder();
      }
    });
  }

  async function loadFinderRows(codes) {
    const manifest = await getJSON('data/search/index.json');
    if (manifest.version !== 1 || !manifest.sectors) throw new Error('Invalid establishment finder index. Rebuild with sigma view --refresh.');
    const grouped = new Map(codes.map(code => [code, []]));
    const jobs = codes.flatMap(code => (manifest.sectors[code] || []).map(path => ({code, path})));
    let position = 0;
    // Bound parallel requests; the same JSON promises are cached across queries.
    await Promise.all(Array.from({length: Math.min(6, jobs.length)}, async () => {
      while (position < jobs.length) {
        const job = jobs[position++];
        const rows = await getJSON(job.path);
        grouped.get(job.code).push(...rows);
      }
    }));
    return grouped;
  }

  async function runFinder() {
    const epoch = ++finderEpoch;
    const text = $('finder-query').value.trim();
    const box = $('finder-results'), status = $('finder-status');
    box.replaceChildren();
    if (window.SigmaFinder.normalize(text).length < 2) {
      status.textContent = 'Type at least two letters to search.';
      return;
    }
    status.textContent = 'Searching establishments…';
    const sector = $('finder-sector').value;
    const codes = sector ? [sector] : [...sectors.keys()];
    try {
      const rows = await loadFinderRows(codes);
      if (epoch !== finderEpoch) return; // Newer text/filter superseded this request.
      const found = window.SigmaFinder.search(rows, text, 30);
      if (!found.total) { status.textContent = 'No matching establishment names.'; return; }
      status.textContent = `${found.total.toLocaleString()} matches${found.total > found.matches.length ? ' · showing the first 30' : ''}`;
      for (const hit of found.matches) {
        const button = el('button', {type: 'button', className: 'finder-result'});
        button.append(el('span', {className: 'finder-name', textContent: hit.name}),
          el('span', {className: 'finder-detail', textContent:
            `${sectorLabel(hit.sector)}${hit.cluster == null ? '' : ` · cluster ${hit.cluster}`}`}));
        button.addEventListener('click', () => pickFinderResult(hit));
        box.append(el('div', {role: 'listitem'}, button));
      }
    } catch (err) {
      if (epoch === finderEpoch) status.textContent = `Search unavailable: ${err.message || err}`;
    }
  }

  async function pickFinderResult(hit) {
    const status = $('finder-status');
    status.textContent = `Locating ${hit.name}…`;
    try {
      const fc = await getJSON(`data/tiles/${tileIndex.zoom}/${hit.tile}.geojson`);
      const feature = fc.features[hit.offset];
      if (!feature || feature.properties.name !== hit.name ||
          String(feature.properties.type) !== String(hit.sector) ||
          feature.geometry.type !== 'Point') throw new Error('Search index and tile disagree. Rebuild Explorer with --refresh.');
      const coordinates = feature.geometry.coordinates;
      const point = {...feature.properties, coordinates};
      if (hidden.has(hit.sector)) {
        hidden.delete(hit.sector);
        renderSectors();
        renderCentral();
      }
      if (point.node_id && nodeIndex.has(point.node_id)) {
        selectNode(point.node_id, point);
      } else {
        // Classified-only locations are displayed, not promoted into X nodes.
        selectUnclustered(point);
      }
      map.easeTo({center: coordinates, zoom: Math.max(map.getZoom(), 15), duration: 500});
      status.textContent = `Located: ${hit.name}`;
      // Close search results after a successful selection, revealing the graph.
      const finderPanel = $('finder-query').closest('.sidebar-disclosure');
      if (finderPanel) finderPanel.open = false;
    } catch (err) {
      status.textContent = `Could not locate establishment: ${err.message || err}`;
    }
  }

  // ------------------------------------------------------------------ selection
  function refresh() {
    // Invalidate in-flight route/hover work BEFORE any synchronous render work.
    const epoch = ++refreshEpoch;
    ++routeEpoch;
    ++hoverEpoch;
    pendingHoverEvent = null;
    if (ready) {
      setData('routes', EMPTY());
      setData('route-hover', EMPTY());
    }
    network = selection && nodeIndex.has(selection.id) ? buildNetwork(selection.id) : null;
    sigmaTriangleStyleByNode = computeNetworkTriangleStyles();
    renderSelection();
    if (ready) {
      applyEmphasis();
      updateStatus();
    }
    const finish = () => {
      if (epoch !== refreshEpoch) return;
      renderSectors(); // Re-rank when selection or Strongest changes.
      drawGraph();
      renderConnections();
      if (ready) showRoutes();
    };
    if (!ready) { finish(); return; }
    // Let MapLibre paint the new focus before reconstructing the diagram and
    // fetching exact route geometries. A newer click cancels this work.
    requestAnimationFrame(() => setTimeout(finish, 0));
  }

  function selectUnclustered(point) {
    selection = {id: null, point};
    refresh();
    setData('selected-center', EMPTY());
    setData('selected-point', {type: 'FeatureCollection', features: [
      {type: 'Feature', properties: {}, geometry: {type: 'Point', coordinates: point.coordinates}}]});
    try { history.replaceState(null, '', location.pathname + location.search); } catch (_) {}
  }

  function selectNode(id, point = null, options = {}) {
    const n = nodeIndex.get(id);
    if (!n) {
      clearSelection();
      $('place-name').textContent = point ? point.name : 'Unassigned establishment';
      $('place-description').textContent = 'This establishment has no X node for its sector and cluster.';
      return;
    }
    selection = {id, point};
    refresh();
    sigmaSyncSelectedTriangle();
    setData('selected-point', point && point.coordinates ? {type: 'FeatureCollection', features: [
      {type: 'Feature', properties: {}, geometry: {type: 'Point', coordinates: point.coordinates}}]} : EMPTY());
    if (options.fly && isNum(n.lon) && isNum(n.lat)) map.easeTo({center: [n.lon, n.lat], zoom: Math.max(map.getZoom(), 13.5), duration: 400});
    try { history.replaceState(null, '', `#${encodeURIComponent(id)}`); } catch (_) { /* ignore */ }
  }

  function clearSelection() {
    selection = null;
    ++hoverEpoch;
    setData('selected-center', EMPTY());
    setData('selected-point', EMPTY());
    refresh();
    try { history.replaceState(null, '', location.pathname + location.search); } catch (_) { /* ignore */ }
  }

  function zoomToNetwork() {
    if (!network) return;
    const coords = [...network.ring.keys()].map(id => nodeIndex.get(id)).filter(n => isNum(n.lon)).map(n => [n.lon, n.lat]);
    if (selection && selection.point && selection.point.coordinates) coords.push(selection.point.coordinates);
    if (!coords.length) return;
    const lons = coords.map(c => c[0]), lats = coords.map(c => c[1]);
    const panel = document.querySelector('.sector-panel');
    const left = panel.open && window.innerWidth > 900 ? panel.offsetWidth + 30 : 40;
    map.fitBounds([[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
      {padding: {top: 70, bottom: 70, left, right: 60}, maxZoom: 15, duration: 450});
  }

  // One control collapses the *whole* right panel; individual disclosures
  // remain untouched. Keep this outside the hidden panel so it can reopen it.
  function setRightPanelCollapsed(collapsed) {
    const panel = $('sigma-details-panel');
    const button = $('sigma-details-toggle');
    if (!panel || !button) return;
    if (collapsed && document.body.classList.contains('theater')) toggleTheater();
    panel.hidden = collapsed;
    document.body.classList.toggle('details-collapsed', collapsed);
    button.textContent = collapsed ? 'Show panel' : 'Hide panel';
    button.setAttribute('aria-expanded', String(!collapsed));
    button.setAttribute('aria-label', collapsed ? 'Show right details panel' : 'Hide right details panel');
    button.title = collapsed ? 'Reopen the right panel' : 'Hide the right panel to enlarge the map';
    // MapLibre must be told when its CSS grid column changes width.
    // Reopening also resizes the graph without altering its nodes/edges.
    requestAnimationFrame(() => {
      if (map && map.resize) map.resize();
      if (!collapsed && cy) {
        cy.resize();
        if (network) cy.fit(undefined, 24);
      }
    });
  }

  function toggleTheater() {
    const active = document.body.classList.toggle('theater');
    $('theater-toggle').textContent = active ? 'Exit theater' : 'Theater view';
    $('theater-toggle').setAttribute('aria-pressed', String(active));
    requestAnimationFrame(() => { cy.resize(); cy.fit(undefined, 35); });
  }

  // ------------------------------------------------------------------ sector panel
  function sectorMatchPairs() {
    const pairs = [];
    for (const s of sectors.values()) pairs.push(s.code, s.color);
    return pairs.length ? pairs : ['__none__', '#657f78'];
  }

  // Sector strength is the largest published technical coefficient incident
  // to any cluster in that sector. This fallback works before a selection.
  function recordSectorStrength(node, coefficient) {
    if (!node || !isNum(coefficient)) return;
    const prior = globalSectorStrength.get(node.type);
    if (prior === undefined || coefficient > prior) globalSectorStrength.set(node.type, coefficient);
  }
  function displayedSectorStrength() {
    const scores = new Map();
    if (!network) return scores;
    for (const rel of network.direct) {
      const target = nodeIndex.get(rel.other);
      if (!target || !isNum(rel.strength)) continue;
      const prev = scores.get(target.type);
      if (prev === undefined || rel.strength > prev) scores.set(target.type, rel.strength);
    }
    return scores;
  }

  // sigma-sector-panel-readability-v1: sector identity first; ID and metrics secondary.
  // sigma-explorer-clean-label-column-sorts-v1: one source for all human sector names.
  // sigma-sparse-hierarchy-codes-20261027-v1: numeric display ancestry, from validated crosswalk sha256=57e95ab8ed174eb0af1530ba428fc01461eba413dd568495b7b4a6c1c2bd05ed.
  // The published/raw sector ID remains the sole key for filters and network operations.
  const sigmaParent80By240 = [null,1,2,3,4,5,6,7,8,9,10,11,12,13,14,14,14,14,14,14,14,14,14,15,15,15,15,15,16,16,17,18,19,19,19,19,19,19,20,21,22,23,24,25,26,26,27,27,27,27,27,27,27,27,27,27,27,27,27,27,27,27,27,27,27,27,27,27,27,28,28,28,28,28,28,29,29,29,30,30,30,30,30,30,30,30,30,31,31,31,31,32,32,32,32,33,33,33,33,33,33,33,34,34,34,35,35,36,36,37,37,37,37,37,37,37,38,39,39,40,40,40,40,41,42,42,42,42,42,42,42,42,43,43,43,43,43,43,43,43,43,43,44,44,44,44,44,44,45,45,45,45,45,45,45,46,46,46,46,46,46,46,47,47,47,47,48,48,48,48,48,48,49,50,51,52,53,54,55,56,57,57,57,57,57,57,58,59,60,60,61,62,62,63,64,64,64,64,65,65,65,65,65,65,66,67,68,68,69,70,71,72,72,72,72,72,72,72,72,72,72,72,72,72,72,72,72,72,73,74,75,76,77,78,79,80,80,80,80,80,80];
  const sigmaParent16By80 = [null,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,4,4,4,4,5,6,6,6,7,7,7,7,7,8,8,9,9,10,10,10,10,11,11,12,13,14,14,15,15,15,16,16];
  function sparseSectorCode(value) {
    const raw = String(value ?? '').trim();
    const match = /^(240|80|16):(\d+)(?::(O|OTHER))?$/i.exec(raw);
    if (!match) return raw;
    const tier = match[1], number = Number(match[2]);
    const residual = Boolean(match[3]);
    const p2 = n => String(n).padStart(2, '0');
    const p3 = n => String(n).padStart(3, '0');
    let parts;
    if (tier === '240') {
      const middle = sigmaParent80By240[number];
      const broad = sigmaParent16By80[middle];
      if (!middle || !broad) return raw;
      parts = [p2(broad), p2(middle), p3(number)];
    } else if (tier === '80') {
      const broad = sigmaParent16By80[number];
      if (!broad) return raw;
      parts = [p2(broad), p2(number)];
    } else {
      if (!Number.isInteger(number) || number < 1 || number > 16) return raw;
      parts = [p2(number)];
    }
    if (residual) parts.push('o');
    return parts.join(':');
  }

  function sectorPresentation(s) {
    const code = String(s.code ?? '').trim();
    const matched = /^(240|80|16):(\d+)(?::(O|OTHER))?$/i.exec(code);
    const raw = String(s.label || '').trim();
    let name = raw || code;
    // Published custom-sector captions repeat the sector code and IO resolution.
    if (name.startsWith(code)) name = name.slice(code.length).replace(/^\s*[-–—:]\s*/, '');
    if (matched) {
      name = name.replace(new RegExp('^IO' + matched[1] + '\\s+' + Number(matched[2]) + '\\s*[·–—-]\\s*', 'i'), '');
      name = name.replace(new RegExp('^' + Number(matched[2]) + '\\s+(?=[A-Za-z])', 'i'), '');
      // Also support padded source identifiers, e.g. IO16 03.
      name = name.replace(/^IO(?:240|80|16)\s+\d+\s*[·–—-]\s*/i, '');
      name = name.replace(/^\d+\s+(?=[A-Za-z])/, '');
    }
    // sigma-canonical-sparse-hierarchy-v1: published sparse codes use clean names.
    const canonical = /^\d{2}(?::\d{2}(?::(?:\d{3}|o))?|:o)?$/.test(code);
    if (canonical) {
      name = name.replace(/^IO(?:240|80|16)\s+\d+\s*[·–—-]\s*/i, '');
      name = name.replace(/^\d+\s+(?=[A-Za-z])/, '');
    }
    const residual = Boolean(matched && matched[3]) || (canonical && /:o$/.test(code));
    if (residual) {
      // Remove only generic residual suffixes; do not alter official non-residual
      // industries such as "Other personal service activities" (IO240 240).
      name = name.replace(/\s*[-–—·]\s*Other(?:\s+industries)?\s*$/i, '');
      name = name.replace(/\s*\(others?\)\s*$/i, '').trim();
      name = name.replace(/\s*[-–—]\s*other industries\s*$/i, '').trim();
      name = (name || 'Other industries') + ' (others)';
    }
    const kind = matched ? ({'240':'Detailed industry','80':'Industry group','16':'Broad group'}[matched[1]]) : 'Industry';
    return {code:sparseSectorCode(code), rawCode:code, name: name.trim() || code, kind: kind + (residual ? ' · residual' : ''), residual};
  }

  const io240Parents = {"io80":{"01":1,"02":2,"03":3,"04":4,"05":5,"06":6,"07":7,"08":8,"09":9,"10":10,"11":11,"12":12,"13":13,"14":14,"15":23,"16":28,"17":30,"18":31,"19":32,"20":38,"21":39,"22":40,"23":41,"24":42,"25":43,"26":44,"27":46,"28":69,"29":75,"30":78,"31":87,"32":91,"33":95,"34":102,"35":105,"36":107,"37":109,"38":116,"39":117,"40":119,"41":123,"42":124,"43":132,"44":142,"45":148,"46":155,"47":162,"48":166,"49":172,"50":173,"51":174,"52":175,"53":176,"54":177,"55":178,"56":179,"57":180,"58":186,"59":187,"60":188,"61":190,"62":191,"63":193,"64":194,"65":198,"66":204,"67":205,"68":206,"69":208,"70":209,"71":210,"72":211,"73":228,"74":229,"75":230,"76":231,"77":232,"78":233,"79":234,"80":235},"io16":{"01":1,"02":39,"03":46,"04":172,"05":176,"06":177,"07":180,"08":191,"09":194,"10":204,"11":209,"12":211,"13":228,"14":229,"15":231,"16":234}};
  const sectorSortState = {key: 'code', descending: false};
  function io240Rank(s) {
    const code = String(s.code);
    // Canonical sparse hierarchy is the stored sector identity.
    const sparse = /^(\d{2})(?::(\d{2})(?::(\d{3}|o))?|:o)?$/.exec(code);
    if (sparse) {
      const broad = sparse[1], middle = sparse[2], child = sparse[3];
      const rank = child && child !== 'o' ? Number(child) :
        middle ? io240Parents.io80[middle] : io240Parents.io16[broad];
      const tier = child && child !== 'o' ? 0 : middle ? 1 : 2;
      return [Number.isFinite(rank) ? rank : Infinity, tier];
    }
    const m = /^(240|80|16):(\d+)(?::(?:O|OTHER))?$/i.exec(code);
    if (!m) return [Infinity, 9];
    const rank = m[1] === '240' ? Number(m[2]) :
      m[1] === '80' ? io240Parents.io80[String(Number(m[2])).padStart(2,'0')] :
      io240Parents.io16[String(Number(m[2])).padStart(2,'0')];
    return [Number.isFinite(rank) ? rank : Infinity, m[1] === '240' ? 0 : m[1] === '80' ? 1 : 2];
  }
  function compareSectorCodes(a, b) {
    const x = io240Rank(a), y = io240Rank(b);
    return (x[0]-y[0]) || (x[1]-y[1]) || String(a.code).localeCompare(String(b.code),undefined,{numeric:true});
  }
  function renderSectors() {
    const list = $('sector-list');
    list.replaceChildren();
    const linked = displayedSectorStrength();
    const needle = ($('sector-search')?.value || '').trim().toLocaleLowerCase();
    const nameOf = s => sectorPresentation(s).name;
    // Show sectors with real clusters by default. Opt-in adds only
    // *nonempty* sectors lacking clusters, not empty Economy catalog entries.
    const includeUnscored = Boolean($('show-unscored')?.checked);
    const eligible = [...sectors.values()].filter(s =>
      s.clusters > 0 || (includeUnscored && s.points > 0));
    const ordered = eligible.filter(s => {
      const p = sectorPresentation(s);
      return !needle || (p.name + ' ' + p.code + ' ' + p.kind + ' ' + s.label).toLocaleLowerCase().includes(needle);
    }).sort((a,b) => {
      let n;
      if (sectorSortState.key === 'name') n = nameOf(a).localeCompare(nameOf(b));
      else if (sectorSortState.key === 'places') n = a.points - b.points;
      else n = compareSectorCodes(a,b);
      return (sectorSortState.descending ? -n : n) || compareSectorCodes(a,b);
    });
    for (const s of ordered) {
      const p = sectorPresentation(s);
      const checkbox = el('input',{type:'checkbox',checked:!hidden.has(s.code)});
      checkbox.addEventListener('change', () => {
        checkbox.checked ? hidden.delete(s.code) : hidden.add(s.code);
        sectorsChanged();
      });
      const score = network && linked.has(s.code) ? linked.get(s.code) : globalSectorStrength.get(s.code);
      const description = network && linked.has(s.code) ? 'Strongest direct network coefficient' : 'Largest network coefficient';
      const label = el('label', {className: s.clusters === 0 && s.points > 0
          ? 'sector-item sector-item--unscored'
          : (s.points ? 'sector-item' : 'sector-item sector-no-places'),
        title:`${p.name}\nCode ${p.code} · ${p.kind}\n${s.points.toLocaleString()} establishments · ${s.clusters} clusters\n${description}: ${isNum(score) ? fmtCoef(score) : 'not available'}`},
        checkbox, swatch(s.code),
        el('span',{className:'name sector-title',textContent:p.name}),
        el('span',{className:'sector-code',textContent:p.code}),
        el('span',{className:'sector-mini-count',textContent:s.points.toLocaleString(),
          title:`${s.points.toLocaleString()} establishments`}));
      list.append(label);
    }
    const visibleEnabled = eligible.filter(s => !hidden.has(s.code)).length;
    $('sector-count').textContent = needle ?
      `${ordered.length} matching · ${visibleEnabled} of ${eligible.length} shown` :
      `${visibleEnabled} of ${eligible.length} shown`;
    document.querySelectorAll('[data-sector-order]').forEach(button => {
      const selected = button.dataset.sectorOrder === sectorSortState.key;
      const direction = selected ? (sectorSortState.descending ? '↓' : '↑') : '↕';
      const glyph = button.querySelector('.sort-direction');
      if (glyph) glyph.textContent = direction;
      button.setAttribute('aria-pressed',String(selected));
      button.title = `Sort by ${button.dataset.sectorOrder}${selected ? (sectorSortState.descending ? ', descending' : ', ascending') : ''}`;
    });
  }

  function sectorsChanged() {
    renderCentral();
    refresh(); // refresh() schedules exactly one sector-list rebuild
  }

  // ------------------------------------------------------------------ map popups
  function describe(feature) {
    const p = feature.properties, id = feature.layer.id;
    if (id === 'unclustered-establishments') {
      return [p.name, `${sectorLabel(p.type)} · ${sectorCode(p.type)}`,
        'Classified establishment · No qualifying cluster · SIGMA score N/A'];
    }
    if (id === 'establishments') {
      return [p.name, `${sectorLabel(p.type)} · ${sectorCode(p.type)}`, `Cluster ${p.cluster} · SIGMA score ${fmtNum(p.score)}`];
    }
    if (id === 'centers') {
      const n = nodeIndex.get(p.id);
      return n ? [nodeLabel(n), `${fmtNum(n.members, 0)} establishments · centrality ${fmtNum(n.centrality)}`, 'Cluster center'] : [p.id];
    }
    return null;
  }

  // Routes of reciprocal edges, and routes that share the first road segments, lie on the
  // same pixels. List every route under the cursor, one block per linked cluster.
  // Route hover groups by DIRECTED edge rather than by focus neighbor so
  // second- and third-step connections are correctly identified.
  // Describe real directed edges. Purple requires both reciprocal X edges,
  // not coincident map segments from unrelated cluster pairs.
  function describeRoutes(hits) {
    if (!network) return [];
    const byPair = new Map();
    for (const h of hits) {
      const p = h.properties || {};
      if (!p.from || !p.to) continue;
      const key = p.pair_key || routePairKey(p.from, p.to);
      if (!byPair.has(key)) byPair.set(key, p);
    }
    return [...byPair.values()].map(p => {
      const a = p.anchor || p.from;
      const b = p.from === a ? p.to : p.from;
      const near = nodeIndex.get(a), far = nodeIndex.get(b);
      const name = id => { const n = nodeIndex.get(id); return n ? shortLabel(n) : id; };
      const depth = Number(p.depth) || 1;
      const rows = [];
      if (p.kind === 'both') {
        const outward = p.from === a;
        const supply = outward ? p : {coefficient: p.reverse_coefficient, weight: p.reverse_weight, distance: p.reverse_distance};
        const use = outward ? {coefficient: p.reverse_coefficient, weight: p.reverse_weight, distance: p.reverse_distance} : p;
        rows.push(`${name(a)} → ${name(b)}: a = ${fmtCoef(supply.coefficient)} (X weight ${fmtXWeight(supply.weight)})`);
        rows.push(`${name(b)} → ${name(a)}: a = ${fmtCoef(use.coefficient)} (X weight ${fmtXWeight(use.weight)})`);
        rows.push(p.separate_paths ? 'Reciprocal X links use two distinct published road paths' : 'Reciprocal X links share the same published road path');
      } else {
        rows.push(`${name(p.from)} → ${name(p.to)}: a = ${fmtCoef(p.coefficient)} (X weight ${fmtXWeight(p.weight)})`);
      }
      rows.push(`Road distance ${fmtDist(p.distance)}`);
      return {title: `${near ? shortLabel(near) : a} ${p.kind === 'both' ? '↔' : '—'} ${far ? shortLabel(far) : b} · step ${depth}`,
        rows, strength: Math.max(0, Number(p.coefficient) || 0, Number(p.reverse_coefficient) || 0)};
    }).sort((a, b) => b.strength - a.strength);
  }

  const POPUP_BLOCKS = 3;
  function onHover(event) {
    // Cheap feature query first. Routes are only queried if no point is selectable.
    const placeLayers = ['centers', 'establishments', 'unclustered-establishments'].filter(l =>
      map.getLayer(l) && map.getLayoutProperty(l, 'visibility') !== 'none');
    const places = map.queryRenderedFeatures(event.point, {layers: placeLayers});
    const scopedPlaces = places.filter(selectableMapFeature);
    map.getCanvas().style.cursor = scopedPlaces.length ? 'pointer' : '';
    let content = null;
    if (scopedPlaces.length) {
      const lines = describe(scopedPlaces[0]);
      if (lines) content = el('div', {}, el('div', {className: 'popup-title', textContent: lines[0]}),
        ...lines.slice(1).map(text => el('div', {className: 'popup-row', textContent: text})));
    } else {
      // Keep every depth in hit testing, but only pay for route queries when needed.
      const routeLayers = [];
      for (let step = 1; step <= 20; step++) {
        const stem = step === 1 ? 'routes' : `routes-step-${step}`;
        routeLayers.push(stem, step === 1 ? 'routes-in' : `${stem}-in`);
      }
      const visibleRoutes = routeLayers.filter(l => map.getLayer(l) &&
        map.getLayoutProperty(l, 'visibility') !== 'none');
      const hits = map.queryRenderedFeatures(event.point, {layers: visibleRoutes});
      const blocks = describeRoutes(hits);
      if (blocks.length) {
        content = el('div', {}, ...blocks.slice(0, POPUP_BLOCKS).map(b => el('div', {className: 'popup-block'},
          el('div', {className: 'popup-title', textContent: b.title}),
          ...b.rows.map(text => el('div', {className: 'popup-row', textContent: text})))));
        if (blocks.length > POPUP_BLOCKS) {
          content.append(el('div', {className: 'popup-row', textContent:
            `${blocks.length - POPUP_BLOCKS} more linked clusters use this road. Hover a row in the table to see one route alone.`}));
        }
      }
    }
    if (!content) { popup.remove(); return; }
    popup.setLngLat(event.lngLat).setDOMContent(content).addTo(map);
  }

  // Collapse bursts of mousemove events into one hover inspection per animation frame.
  function scheduleHover(event) {
    pendingHoverEvent = event;
    if (hoverFrameScheduled) return;
    hoverFrameScheduled = true;
    requestAnimationFrame(() => {
      hoverFrameScheduled = false;
      const latest = pendingHoverEvent;
      pendingHoverEvent = null;
      if (latest && ready) onHover(latest);
    });
  }

  function onClick(event) {
    popup.remove();
    const layers = ['centers', 'establishments', 'unclustered-establishments'].filter(l => map.getLayer(l) && map.getLayoutProperty(l, 'visibility') !== 'none');
    const hits = map.queryRenderedFeatures(event.point, {layers});

    const f = hits.find(selectableMapFeature);
    if (!f) return;
    if (f.layer.id === 'centers') selectNode(f.properties.id);
    else if (f.layer.id === 'unclustered-establishments')
      selectUnclustered({...f.properties, coordinates: f.geometry.coordinates});
    else selectNode(f.properties.node_id, {...f.properties, coordinates: f.geometry.coordinates});
  }

  // ------------------------------------------------------------------ setup
  // A white inverted triangle with a sector-colored outline for each economic type.
  // Canvas images are registered once after MapLibre's style has loaded.
  // Unscored locations: independent, hollow, UPRIGHT triangle icons.
  // Cluster centers remain the original, larger INVERTED triangles.
  const unscoredSectorIcons = new Map();
  function registerUnscoredTriangles() {
    unscoredSectorIcons.clear();
    let index = 0;
    const add = (name, outline) => {
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = 24;
      const ctx = canvas.getContext('2d');
      if (!ctx) throw Error('Cannot render unscored place triangle: canvas 2D unavailable.');
      ctx.clearRect(0, 0, 24, 24);
      ctx.fillStyle = 'rgba(0,0,0,0)';
      ctx.strokeStyle = outline;
      ctx.lineWidth = 2.2;
      ctx.lineJoin = 'round';
      ctx.beginPath();
      ctx.moveTo(12, 4); ctx.lineTo(21, 20); ctx.lineTo(3, 20);
      ctx.closePath(); ctx.fill(); ctx.stroke();
      map.addImage(name, ctx.getImageData(0, 0, 24, 24));
    };
    for (const [code, sector] of sectors) {
      const name = `sigma-unscored-triangle-${index++}`;
      add(name, sector.color || '#b11116');
      unscoredSectorIcons.set(String(code), name);
    }
    add('sigma-unscored-triangle-default', '#b11116');
  }

  function centerIconExpression() {
    const size = 32;
    const baseFallback = 'sigma-center-default';
    const linkedFallback = 'sigma-center-linked-default';
    const darkFallback = 'sigma-center-dark-default';
    const darkLinkedFallback = 'sigma-center-linked-dark-default';
    const addTriangle = (name, fill, outline) => {
      const canvas = document.createElement('canvas');
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('Cannot render cluster centers: 2D canvas is unavailable.');
      ctx.fillStyle = fill;
      ctx.strokeStyle = outline;
      ctx.lineWidth = 2.1;
      ctx.lineJoin = 'round';
      ctx.beginPath();
      ctx.moveTo(5, 6);
      ctx.lineTo(27, 6);
      ctx.lineTo(16, 27);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      map.addImage(name, ctx.getImageData(0, 0, size, size));
    };
    centerIconByType.clear();
    linkedCenterIconByType.clear();
    darkCenterIconByType.clear();
    darkLinkedIconByType.clear();
    let index = 0;
    for (const [code, sector] of sectors) {
      const key = String(code);
      const sectorFill = sector.color || '#657f78';
      const name = `sigma-center-${index}`;
      const linkedName = `sigma-center-linked-${index}`;
      const darkName = `sigma-center-dark-${index}`;
      const darkLinkedName = `sigma-center-linked-dark-${index}`;
      addTriangle(name, '#ffffff', sectorFill);
      addTriangle(linkedName, sectorFill, COLOR.incoming);
      addTriangle(darkName, '#252323', sectorFill);
      addTriangle(darkLinkedName, sectorFill, '#8cc8e9');
      centerIconByType.set(key, name);
      linkedCenterIconByType.set(key, linkedName);
      darkCenterIconByType.set(key, darkName);
      darkLinkedIconByType.set(key, darkLinkedName);
      index++;
    }
    addTriangle(baseFallback, '#ffffff', '#657f78');
    addTriangle(linkedFallback, '#657f78', COLOR.incoming);
    addTriangle(darkFallback, '#252323', '#657f78');
    addTriangle(darkLinkedFallback, '#657f78', '#8cc8e9');
    return ['get', 'center_icon'];
  }

  // Selected cluster: sector-filled downward triangle with a fine blue outline.
  // Images are registered when the map style loads, with no external assets.
  function selectedCenterIconExpression() {
    const size = 36;
    const fallback = 'sigma-center-selected-default';
    const addTriangle = (name, fill) => {
      const canvas = document.createElement('canvas');
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('Cannot render selected cluster center: 2D canvas is unavailable.');
      ctx.fillStyle = fill;
      ctx.strokeStyle = COLOR.incoming;
      ctx.lineWidth = 2.2;
      ctx.lineJoin = 'round';
      ctx.beginPath();
      ctx.moveTo(5, 6);
      ctx.lineTo(31, 6);
      ctx.lineTo(18, 32);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      map.addImage(name, ctx.getImageData(0, 0, size, size));
    };
    selectedIconByType.clear();
    let index = 0;
    for (const [code, sector] of sectors) {
      const name = `sigma-center-selected-${index++}`;
      // The sector's own palette color is painted into the triangle canvas.
      addTriangle(name, sector.color || '#657f78');
      selectedIconByType.set(String(code), name);
    }
    addTriangle(fallback, '#657f78');
    return ['get', 'icon'];
  }

  function addLayers(data) {
    const [minimum, maximum] = meta.score_range || [null, null];
    // Circle AREA, not radius, is proportional to normalized SIGMA score.
    // Each zoom uses restrained min/max sizes so dense groups remain legible.
    const normalizedScore = (isNum(minimum) && isNum(maximum) && minimum < maximum)
      ? ['max', 0, ['min', 1, ['/',
          ['-', ['coalesce', ['get', 'score'], minimum], minimum], maximum - minimum]]]
      : 0.5;
    const scoreRadius = (small, large) => ['sqrt', ['+', small * small,
      ['*', large * large - small * small, normalizedScore]]];
    const sectorColorExpr = ['match', ['get', 'type'], ...sectorMatchPairs(), '#657f78'];
    if (data.boundary) {
      map.addSource('boundary', {type: 'geojson', data: data.boundary});
      map.addLayer({id: 'boundary-fill', type: 'fill', source: 'boundary', paint: {'fill-color': '#ffffff', 'fill-opacity': 1}});
      map.addLayer({id: 'boundary-line', type: 'line', source: 'boundary', paint: {'line-color': '#71847b', 'line-width': 0.8, 'line-opacity': 0.75}});
    }
    map.addSource('clusters', {type: 'geojson', data: data.clusters});
    map.addLayer({id: 'partition-fill', type: 'fill', source: 'clusters', layout: {visibility: 'none'}, paint: {'fill-color': sectorColorExpr, 'fill-opacity': 0.1}});
    // Quiet geographic context: thin, opaque gray, above translucent polygons.
    if (data.roads) {
      map.addSource('roads', {type: 'geojson', data: data.roads});
      map.addLayer({id: 'roads-line', type: 'line', source: 'roads',
        layout: {'line-join': 'round', 'line-cap': 'round'},
        paint: {'line-color': '#949b9b', 'line-opacity': 0.38,
          'line-width': ['interpolate', ['linear'], ['zoom'], 11, 0.22, 15, 0.5, 18, 0.85]}});
    }
    map.addLayer({id: 'partition-line', type: 'line', source: 'clusters', layout: {visibility: 'none'}, paint: {'line-color': sectorColorExpr, 'line-width': 1}});
    // Selection emphasis: separate drawing layers preserve contrast under
    // cross-sector polygon overlaps without altering native spatial outputs.
    map.addLayer({id: 'partition-linked-fill', type: 'fill', source: 'clusters',
      layout: {visibility: 'none'}, paint: {'fill-color': sectorColorExpr, 'fill-opacity': 0.105}});
    map.addLayer({id: 'partition-linked-line', type: 'line', source: 'clusters',
      layout: {visibility: 'none'}, paint: {'line-color': sectorColorExpr,
        'line-width': 0.7, 'line-opacity': 0.78}});
    map.addLayer({id: 'partition-focus-fill', type: 'fill', source: 'clusters',
      layout: {visibility: 'none'}, paint: {'fill-color': sectorColorExpr, 'fill-opacity': 0.25}});
    map.addLayer({id: 'partition-focus-line', type: 'line', source: 'clusters',
      layout: {visibility: 'none'}, paint: {'line-color': COLOR.focus,
        'line-width': 1.25, 'line-opacity': 0.97}});
    map.addSource('routes', {type: 'geojson', data: EMPTY()});
    // Each feature retains its exact published geometry. Layers are registered
    // deepest-first so earlier road links stay in front of later steps.
    const width = (a, b, step) => ['*', Math.max(0.26, 1 / Math.sqrt(step)),
      ['interpolate', ['linear'], ['get', 'wn'], 0, a, 1, b]];
    const routeDim = step => Math.max(0.18, 0.86 / Math.sqrt(step));
    const routeColor = ['match', ['get', 'kind'], 'both', COLOR.both, COLOR.outgoing];
    const stepFilter = step => ['==', ['get', 'depth'], step];
    // Deeper routes use one set of layers per depth, never per-edge layers.
    for (let step = 20; step > 1; step--) {
      const stem = `routes-step-${step}`;
      const dim = routeDim(step), onlyStep = stepFilter(step);
      map.addLayer({id: `${stem}-casing`, type: 'line', source: 'routes', filter: onlyStep,
        layout: {'line-join': 'round', 'line-cap': 'round'},
        paint: {'line-color': '#ffffff', 'line-width': width(1.35, 3.25, step),
          'line-opacity': Math.min(0.65, dim * 0.7)}});
      map.addLayer({id: stem, type: 'line', source: 'routes',
        filter: ['all', onlyStep, ['!=', ['get', 'kind'], 'incoming']],
        layout: {'line-join': 'round', 'line-cap': 'round'},
        paint: {'line-color': routeColor, 'line-width': width(0.7, 2.2, step), 'line-opacity': dim}});
      map.addLayer({id: `${stem}-in`, type: 'line', source: 'routes',
        filter: ['all', onlyStep, ['==', ['get', 'kind'], 'incoming']],
        layout: {'line-join': 'round', 'line-cap': 'round'},
        paint: {'line-color': COLOR.incoming, 'line-width': width(0.7, 2.2, step),
          'line-opacity': dim, 'line-dasharray': [2, 1]}});
    }
    // Keep the original route IDs used by existing Explorer regressions.
    const direct = stepFilter(1), directDim = routeDim(1);
    map.addLayer({id: 'routes-casing', type: 'line', source: 'routes', filter: direct,
      layout: {'line-join': 'round', 'line-cap': 'round'},
      paint: {'line-color': '#ffffff', 'line-width': width(1.35, 3.25, 1),
        'line-opacity': Math.min(0.65, directDim * 0.7)}});
    map.addLayer({id: 'routes', type: 'line', source: 'routes',
      filter: ['all', direct, ['!=', ['get', 'kind'], 'incoming']],
      layout: {'line-join': 'round', 'line-cap': 'round'},
      paint: {'line-color': routeColor, 'line-width': width(0.7, 2.2, 1), 'line-opacity': directDim}});
    map.addLayer({id: 'routes-in', type: 'line', source: 'routes',
      filter: ['all', direct, ['==', ['get', 'kind'], 'incoming']],
      layout: {'line-join': 'round', 'line-cap': 'round'},
      paint: {'line-color': COLOR.incoming, 'line-width': width(0.7, 2.2, 1),
        'line-opacity': directDim, 'line-dasharray': [2, 1]}});
    map.addSource('route-hover', {type: 'geojson', data: EMPTY()});
    map.addLayer({id: 'route-hover', type: 'line', source: 'route-hover', layout: {'line-join': 'round', 'line-cap': 'round'},
      paint: {'line-color': '#d99d2c', 'line-width': 3.2, 'line-opacity': 0.92}});
    const overview = data.overview || EMPTY();
    const busiest = overview.features.reduce((m, f) => Math.max(m, f.properties.count || 0), 1);
    map.addSource('overview', {type: 'geojson', data: overview});
    map.addLayer({id: 'overview-counts', type: 'heatmap', source: 'overview', layout: {visibility: 'none'}, paint: {
      'heatmap-weight': ['interpolate', ['linear'], ['sqrt', ['get', 'count']], 0, 0, Math.sqrt(busiest), 1],
      'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 8, 1.5, 15, 4],
      'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 8, 10, 12, 28, 16, 70],
      'heatmap-opacity': 0.85,
      'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'], 0, 'rgba(45,102,74,0)', 0.15, '#d7e8dc',
        0.4, '#9cc9ad', 0.7, '#4f9a72', 1, '#16382a']}});
    map.addSource('points', {type: 'geojson', data: EMPTY()});
    // A thin, open circle denotes a classified establishment absent from
    // network clustering; no score or X node is implied. Draw beneath scores.
    // Separate EMPTY source by default: impossible to double-render an unscored point.
    map.addSource('unscored-points', {type: 'geojson', data: EMPTY()});
    registerUnscoredTriangles();
    map.addLayer({id: 'unclustered-establishments', type: 'symbol', source: 'unscored-points',
      filter: ['==', ['get', 'unclustered'], true],
      layout: {visibility: 'none', 'icon-image': ['get', 'unscored_icon'],
        'icon-size': ['interpolate', ['linear'], ['zoom'], 11, 0.32, 14, 0.38, 17, 0.50],
        'icon-allow-overlap': true, 'icon-ignore-placement': true},
      paint: {'icon-opacity': 0.84}});
    map.addLayer({id: 'establishments', type: 'circle', source: 'points',
      filter: ['!=', ['get', 'unclustered'], true], paint: {
      'circle-color': sectorColorExpr,
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 11, scoreRadius(1.4, 5.7), 14, scoreRadius(2.0, 10.5), 17, scoreRadius(3.2, 16.5)],
      'circle-opacity': 0.82, 'circle-stroke-width': 0.35, 'circle-stroke-color': '#ffffff'}});
    // Assign browser-only icon identifiers by normalized sector code. This
    // avoids a numeric/string `match` mismatch and preserves palette fidelity.
    // Register sector icons BEFORE assigning their names to center features.
    // Otherwise every feature receives a fallback, erasing palette colors.
    const centerIconLayout = centerIconExpression();
    for (const feature of data.centers.features || []) {
      if (!feature.properties) feature.properties = {};
      const type = String(feature.properties.type);
      feature.properties.center_icon = centerIconByType.get(type) || 'sigma-center-default';
      feature.properties.linked_center_icon = linkedCenterIconByType.get(type) || 'sigma-center-linked-default';
      feature.properties.dark_center_icon = darkCenterIconByType.get(type) || 'sigma-center-dark-default';
      feature.properties.dark_linked_center_icon = darkLinkedIconByType.get(type) || 'sigma-center-linked-dark-default';
    }
    map.addSource('centers', {type: 'geojson', data: data.centers});
    map.addLayer({id: 'centers', type: 'symbol', source: 'centers',
      layout: {
        visibility: 'none',
        'icon-image': centerIconLayout,
        'icon-size': ['interpolate', ['linear'], ['zoom'], 11, 0.55, 15, 0.8, 18, 1],
        'icon-allow-overlap': true,
        'icon-ignore-placement': true
      },
      paint: {'icon-opacity': 1}});
    map.addSource('selected-center', {type: 'geojson', data: EMPTY()});
    map.addLayer({id: 'selected-center', type: 'symbol', source: 'selected-center',
      layout: {
        'icon-image': selectedCenterIconExpression(),
        'icon-size': ['interpolate', ['linear'], ['zoom'], 11, 0.8, 15, 1.08, 18, 1.2],
        'icon-allow-overlap': true,
        'icon-ignore-placement': true
      },
      paint: {'icon-opacity': 1}});
    map.addSource('selected-point', {type: 'geojson', data: EMPTY()});
    map.addLayer({id: 'selected-point', type: 'circle', source: 'selected-point',
      paint: {'circle-color': 'rgba(255,255,255,0)', 'circle-radius': 10, 'circle-stroke-width': 1.5, 'circle-stroke-color': '#d99d2c'}});
  }

  function bindControls() {
    $('partitions').addEventListener('change', e => { state.partitions = e.target.value; updatePartitions(); });
    $('show-centers').addEventListener('change', updateCenterVisibility);
    $('show-roads').addEventListener('change', e => visibility('roads-line', e.target.checked));
    $('direction').addEventListener('change', e => { state.direction = e.target.value; refresh(); });
    // Depth is the graph hop count (not road distance). The model accepts any
    // positive integer; cap manual input at 20 to avoid surprise long traversals.
    const depthSelect = $('depth');
    const depthCustom = $('depth-custom');
    const syncDepth = () => {
      const raw = depthCustom.value.trim();
      const value = Number(raw);
      const valid = raw !== '' && Number.isSafeInteger(value) && value >= 1 && value <= 20;
      depthCustom.setAttribute('aria-invalid', String(!valid));
      if (!valid) return;  // Keep previous display while editing incomplete input.
      state.depth = String(value);
      refresh();
    };
    depthSelect.addEventListener('change', () => {
      const custom = depthSelect.value === 'custom';
      depthCustom.hidden = !custom;
      depthCustom.disabled = !custom;
      if (custom) { syncDepth(); depthCustom.focus(); }
      else { depthCustom.setAttribute('aria-invalid', 'false'); state.depth = depthSelect.value; refresh(); }
    });
    depthCustom.addEventListener('input', () => {
      if (depthSelect.value === 'custom') syncDepth();
    });
    // Presets and arbitrary positive whole-number limits share the same state.top.
    const topSelect = $('top');
    const topCustom = $('top-custom');
    const syncTop = () => {
      const raw = topCustom.value.trim();
      const value = Number(raw);
      const valid = raw !== '' && Number.isSafeInteger(value) && value >= 1 && value <= 10000;
      topCustom.setAttribute('aria-invalid', String(!valid));
      if (!valid) return;  // Preserve the previous network until the entry is valid.
      state.top = String(value);
      refresh();
    };
    topSelect.addEventListener('change', () => {
      const custom = topSelect.value === 'custom';
      topCustom.hidden = !custom;
      topCustom.disabled = !custom;
      if (custom) { syncTop(); topCustom.focus(); }
      else { topCustom.setAttribute('aria-invalid', 'false'); state.top = topSelect.value; refresh(); }
    });
    topCustom.addEventListener('input', () => {
      if (topSelect.value === 'custom') syncTop();
    });
    $('reset').addEventListener('click', clearSelection);
    $('theater-toggle').addEventListener('click', toggleTheater);
    $('graph-focus').addEventListener('click', () => {
      if (!network) return;
      // Zoom into the first two rings without removing outer nodes/edges.
      const near = cy.nodes().filter(n => n.data('ring') <= 2);
      if (near.length) { cy.resize(); cy.fit(near, 40); }
    });
    $('graph-fit').addEventListener('click', () => { cy.resize(); cy.fit(undefined, 24); });
    $('zoom-network').addEventListener('click', zoomToNetwork);
    $('sectors-all').addEventListener('click', () => { hidden.clear(); sectorsChanged(); });
    $('sectors-none').addEventListener('click', () => { for (const code of sectors.keys()) hidden.add(code); sectorsChanged(); });
    $('show-unscored').addEventListener('change', () => {
      // If a selected unscored point has just been hidden, remove its highlight.
      if (!$('show-unscored').checked && selection && !nodeIndex.has(selection.id)) clearSelection();
      else refresh();
    });
    $('sector-search').addEventListener('input', renderSectors);
    document.querySelectorAll('[data-sector-order]').forEach(button => {
      button.addEventListener('click', () => {
        const key = button.dataset.sectorOrder;
        if (!['name','code','places'].includes(key)) return;
        if (sectorSortState.key === key) sectorSortState.descending = !sectorSortState.descending;
        else { sectorSortState.key = key; sectorSortState.descending = key === 'places'; }
        renderSectors();
      });
    });
    document.addEventListener('keydown', e => {
      if (e.key !== 'Escape') return;
      if (document.body.classList.contains('theater')) toggleTheater();
      else if (selection) clearSelection();
    });
  }

  async function initialize() {
    // Never restore opt-in across page reloads, even via browser form state.
    const unscoredToggle = $('show-unscored');
    if (unscoredToggle) unscoredToggle.checked = false;
    $('sigma-details-toggle').addEventListener('click', () => {
      setRightPanelCollapsed(!$('sigma-details-panel').hidden);
    });
    // sigma-institutional-theme-handoff-20261026-v1: persist explicit UI selection.
    $('theme-toggle').addEventListener('click', () => {
      applyTheme(themeMode === 'dark' ? 'light' : 'dark');
      try { localStorage.setItem('sigma-theme', themeMode); } catch (_) { /* optional storage */ }
    });
    let initialTheme = 'light';
    let incomingTheme = null;
    try { incomingTheme = new URLSearchParams(location.search).get('theme'); } catch (_) {}
    if (incomingTheme === 'dark' || incomingTheme === 'light') {
      initialTheme = incomingTheme;
    } else {
      try {
        const saved = localStorage.getItem('sigma-theme');
        if (saved === 'dark' || saved === 'light') initialTheme = saved;
      } catch (_) { /* private browsing may restrict storage */ }
    }
    applyTheme('light');
    if (initialTheme !== 'light') applyTheme(initialTheme);
    initializeHelp();
    const [metadata, graph, tiles] = await Promise.all([getJSON('data/metadata.json'), getJSON('data/graph.json'), getJSON('data/tiles.json')]);
    meta = metadata; tileIndex = tiles; tileKeys = Object.keys(tiles.tiles || {});
    const key = $('unclustered-key');
    if (key) key.hidden = true;  // shown only by opt-in, without a selected X node
    const control = $('show-unscored');
    if (control) {
      control.checked = false; // explicit default on every Explorer load
      control.disabled = meta.profile !== 'local' || !meta.counts?.classified_unclustered_points;
      if (control.disabled) control.closest('.sector-overlay-control').title =
        'No classified-but-unscored locations are available in this Explorer.';
    }
    if (meta.schema_version !== 3) throw new Error('This Explorer bundle was built by another version. Run "sigma view <area> --refresh".');
    for (const s of meta.sectors) sectors.set(s.code, s);
    for (const n of graph.nodes) { nodeIndex.set(n.id, n); pairIndex.set(n.id, new Map()); }
    for (const e of graph.edges) {
      const a = pairIndex.get(e.from), b = pairIndex.get(e.to);
      if (!a || !b) continue;
      if (!a.has(e.to)) a.set(e.to, {other: e.to, out: null, in: null});
      if (!b.has(e.from)) b.set(e.from, {other: e.from, out: null, in: null});
      a.get(e.to).out = e;
      b.get(e.from).in = e;
      recordSectorStrength(nodeIndex.get(e.from), e.coefficient);
      recordSectorStrength(nodeIndex.get(e.to), e.coefficient);
    }
    $('area').textContent = meta.area;
    $('counts').textContent = `${meta.counts.points.toLocaleString()} establishments · ${meta.counts.clusters.toLocaleString()} clusters · ${meta.counts.linked_pairs.toLocaleString()} linked pairs`;
    $('show-roads').disabled = !meta.has_roads;
    if (!meta.has_roads) { $('show-roads').checked = false; $('show-roads').parentElement.title = (meta.warnings || []).join(' ') || 'No published roads in this bundle.'; }
    renderSectors();
    renderCentral();
    if (window.innerWidth < 1100) document.querySelector('.sector-panel').open = false;

    cy = cytoscape({container: $('network'), elements: [], layout: {name: 'preset'}, wheelSensitivity: 0.65, style: [
      {selector: 'node', style: {'background-color': 'data(color)', 'width': 20, 'height': 20, 'border-width': 1.5, 'border-color': '#506a5b', 'opacity': 0.98, 'label': ''}},
      {selector: 'node.labelled', style: {'label': 'data(label)', 'font-size': 10, 'font-weight': 400, 'text-wrap': 'wrap', 'text-max-width': 122, 'font-family': 'system-ui, sans-serif', 'color': '#4b5e53', 'text-valign': 'bottom', 'text-halign': 'center', 'text-margin-y': 7, 'text-background-opacity': 0, 'text-outline-width': 0}},
      {selector: 'node[ring >= 2]', style: {'width': 16, 'height': 16, 'opacity': 0.96}},
      {selector: 'node.focus', style: {'width': 28, 'height': 28, 'background-color': '#255b45', 'border-width': 1.5, 'border-color': '#a5c3b1', 'opacity': 1, 'label': 'data(label)', 'font-family': 'system-ui, sans-serif', 'font-size': 9.8, 'font-weight': 700, 'text-wrap': 'wrap', 'text-max-width': 122, 'color': '#245541', 'text-valign': 'bottom', 'text-halign': 'center', 'text-margin-y': 7, 'text-outline-width': 0, 'text-background-opacity': 0, 'z-index': 10}},
      {selector: 'edge', style: {'width': 'mapData(wn, 0, 1, 0.9, 2.2)', 'line-color': '#718879', 'opacity': 0.52, 'curve-style': 'bezier', 'control-point-step-size': 15, 'target-arrow-color': '#718879', 'source-arrow-color': '#718879', 'arrow-scale': 0.78}},
      {selector: 'edge.mid-edge', style: {'opacity': 0.68, 'z-index': 3}},
      {selector: 'edge.outer-edge', style: {'opacity': 0.43}},
      {selector: 'edge', style: {'target-arrow-shape': 'triangle'}},
      {selector: 'edge.focus-edge', style: {'opacity': 0.96, 'z-index': 5, 'width': 'mapData(wn, 0, 1, 1.6, 3.0)'}},
      {selector: 'edge.focus-edge.reciprocal', style: {'opacity': 0.97}},
      {selector: 'edge.focus-edge.outgoing', style: {'line-color': '#b35a4f', 'target-arrow-color': '#b35a4f', 'source-arrow-color': '#b35a4f'}},
      {selector: 'edge.focus-edge.incoming', style: {'line-color': '#39779a', 'target-arrow-color': '#39779a', 'source-arrow-color': '#39779a'}},
    ]});
    cy.on('zoom resize', syncNetworkGlyphs);
    // A graph hidden in a collapsed panel must resize after it becomes visible.
    // Native <details> handles keyboard/pointer toggling without custom state.
    document.querySelector('.graph-section .sidebar-disclosure').addEventListener('toggle', event => {
      if (event.target.open && cy) requestAnimationFrame(() => {
        cy.resize();
        if (network) cy.fit(undefined, 24);
      });
    });
    cy.on('tap', 'node', e => selectNode(e.target.id(), null, {fly: true}));
    cy.on('mouseover', 'node', e => graphTip(e, true));
    cy.on('mouseout', 'node', e => graphTip(e, false));
    cy.on('mouseover', 'edge', e => {
      if (!network) return;
      const edge = e.target.data();
      const other = edge.source === network.focus ? edge.target : edge.target === network.focus ? edge.source : null;
      if (other) highlightRoute(other, edge.source === network.focus ? 'outgoing' : 'incoming');
    });
    cy.on('mouseout', 'edge', () => highlightRoute(null));
    cy.on('tap', 'edge', e => {
      if (!network) return;
      const edge = e.target.data();
      const other = edge.source === network.focus ? edge.target : edge.target === network.focus ? edge.source : null;
      if (other) highlightRoute(other, edge.source === network.focus ? 'outgoing' : 'incoming');
    });

    popup = new maplibregl.Popup({closeButton: false, closeOnClick: false, offset: 10, maxWidth: '300px'});
    map = new maplibregl.Map({container: 'map', attributionControl: {compact: true},
      style: {version: 8, sources: {}, layers: [{id: 'background', type: 'background', paint: {'background-color': '#f8f7f3'}}]},
      bounds: [[meta.bounds[0], meta.bounds[1]], [meta.bounds[2], meta.bounds[3]]], fitBoundsOptions: {padding: 40}});
    map.addControl(new maplibregl.NavigationControl({showCompass: false}), 'top-right');
    map.addControl(new maplibregl.ScaleControl({unit: 'metric'}), 'bottom-right');
    map.on('load', async () => {
      try {
        const wanted = {clusters: getJSON('data/clusters.geojson'), centers: getJSON('data/nodes.geojson'),
          overview: getJSON('data/overview.geojson'),
          boundary: meta.has_boundary ? getJSON('data/boundary.geojson') : null, roads: meta.has_roads ? getJSON('data/roads.geojson') : null};
        const data = {};
        for (const [k, v] of Object.entries(wanted)) data[k] = v ? await v : null;
        addLayers(data);
        applyTheme(themeMode);
        ready = true;
        map.on('mousemove', scheduleHover);
        map.on('mouseout', () => {
          pendingHoverEvent = null;
          popup.remove();
          map.getCanvas().style.cursor = '';
        });
        map.on('click', onClick);
        map.on('moveend', loadVisiblePoints);
        bindControls();
        initializeFinder();
        await loadVisiblePoints();
        const fromHash = decodeURIComponent(location.hash.slice(1));
        if (fromHash && nodeIndex.has(fromHash)) selectNode(fromHash, null, {fly: true});
        else refresh();
      } catch (err) { showError(err); }
    });
  }

  initialize().catch(showError);
})();
// sigma-explorer-tutorial-polish-20261027-v2
// sigma-explorer-sector-80-graph-fit-20261027-v3
// sigma-ui-original-finder-sector-spacing-20261027-v1

// sigma-explorer-quiet-unscored-toggle-20261028-v1

// sigma-explorer-quiet-unscored-nonempty-compact-20261028-v2

// sigma-explorer-red-unscored-and-right-panel-collapse-20261028-v1
// sigma-explorer-toolbar-panel-help-tilecache-20261029-v1
// sigma-unscored-hidden-by-default-and-rowwise-names-20261029-v1
// sigma-explorer-hollow-overlay-header-repair-20261029-v1
// sigma-explorer-scope-dedup-link-outline-20261029-v2
// sigma-explorer-strict-triangle-sources-header-paint-v3.1-20261029
