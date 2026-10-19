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
(() => {
  const $ = id => document.getElementById(id);
  const EMPTY = () => ({type: 'FeatureCollection', features: []});
  const COLOR = {both: '#7b3fa0', outgoing: '#c0392b', incoming: '#1f6fb2', focus: '#16382a', other: '#9aa8a0'};
  const LIMIT = {graphNodes: 300, graphEdges: 1500, tableRows: 250, labelledNodes: 12};
  const showError = error => {
    $('error').hidden = false;
    $('error').textContent = `SIGMA Explorer: ${String((error && error.message) || error)}`;
  };
  if (location.protocol === 'file:') {
    showError('Open this page through "sigma view" (or any HTTP server). Browsers block data loading from file:// pages.');
    return;
  }
  if (!window.maplibregl || !window.cytoscape || !window.SigmaGraph) {
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
  let tileEpoch = 0, routeEpoch = 0, hoverEpoch = 0;
  let ready = false;             // map layers exist

  // Explicit light default: no OS dark-mode inheritance and no stored setting.
  let themeMode = 'light';
  function applyTheme(choice) {
    themeMode = choice === 'dark' ? 'dark' : 'light';
    const dark = themeMode === 'dark';
    document.documentElement.dataset.theme = themeMode;
    $('theme-mode').value = themeMode;
    if (ready && map && map.getLayer && map.getLayer('centers')) {
      const ids = network ? [...network.ring.keys()] : null;
      const inNetwork = ['in', ['get', 'id'], ['literal', ids || []]];
      const face = themeMode === 'dark' ? 'dark_center_icon' : 'center_icon';
      const linked = themeMode === 'dark' ? 'dark_linked_center_icon' : 'linked_center_icon';
      map.setLayoutProperty('centers', 'icon-image', ids ?
        ['case', inNetwork, ['get', linked], ['get', face]] : ['get', face]);
    }
    // MapLibre paints are independent of HTML/CSS; restyle geographic context.
    if (map && map.getLayer) {
      const paint = (layer, key, value) => {
        if (map.getLayer(layer)) map.setPaintProperty(layer, key, value);
      };
      paint('background', 'background-color', dark ? '#15231c' : '#f4f6f5');
      paint('boundary-fill', 'fill-color', dark ? '#22352a' : '#ffffff');
      paint('boundary-line', 'line-color', dark ? '#678a78' : '#71847b');
      paint('roads-line', 'line-color', dark ? '#9eb6a6' : '#949b9b');
      paint('roads-line', 'line-opacity', network ? (dark ? 0.29 : 0.18) : (dark ? 0.53 : 0.38));
      paint('partition-focus-line', 'line-color', dark ? '#b0dfc1' : COLOR.focus);
      paint('routes-casing', 'line-color', dark ? '#17281f' : '#ffffff');
      // Against a dark map, muted/dark strokes avoid bright halos around
      // thousands of colored establishments. Preserve the focus outline.
      paint('establishments', 'circle-stroke-color', network ?
        ['case', ['==', ['get', 'node_id'], network.focus], dark ? '#81c5a1' : COLOR.focus,
          dark ? '#20372a' : '#ffffff'] : (dark ? '#20372a' : '#ffffff'));
      paint('partition-linked-fill', 'fill-opacity', dark ? 0.17 : 0.105);
      paint('partition-focus-fill', 'fill-opacity', dark ? 0.19 : 0.25);
      paint('partition-linked-line', 'line-opacity', dark ? 0.70 : 0.78);
      paint('partition-focus-line', 'line-color', dark ? '#85bd9e' : COLOR.focus);
      paint('routes', 'line-color', dark ? '#ef9d8b' : COLOR.outgoing);
      paint('routes-in', 'line-color', dark ? '#8cc8e9' : COLOR.incoming);
      paint('selected-point', 'circle-stroke-color', dark ? '#e9aa55' : '#d99d2c');
      if (state.partitions === 'network' && network) {
        paint('partition-line', 'line-color', dark ? '#627d69' : '#cad6cf');
        paint('partition-line', 'line-opacity', dark ? 0.18 : 0.22);
      }
    }
    // Theme Cytoscape's canvas explicitly. No text backgrounds on any node:
    // these used to obscure the focal circle with a bright label rectangle.
    if (cy && cy.style) {
      const quiet = dark ? '#79988a' : '#9eafa5';
      const outward = dark ? '#ef9d8b' : '#b35a4f';
      const inward = dark ? '#8cc8e9' : '#39779a';
      cy.style()
        .selector('node').style({
          'border-color': dark ? '#20362b' : '#f0f4f1'
        })
        .selector('node.labelled').style({
          color: dark ? '#d2e1d6' : '#4b5e53',
          'text-background-opacity': 0,
          'text-outline-width': 0
        })
        .selector('node.focus').style({
          'background-color': dark ? '#4d9872' : '#255b45',
          'border-color': dark ? '#a5d2b7' : '#a5c3b1',
          color: dark ? '#e5f4e9' : '#245541',
          'text-valign': 'bottom', 'text-margin-y': 7,
          'text-background-opacity': 0
        })
        .selector('edge').style({
          'line-color': quiet, 'target-arrow-color': quiet,
          'source-arrow-color': quiet, opacity: dark ? 0.28 : 0.20
        })
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
  const getRoutes = path => {
    if (!routeCache.has(path)) {
      routeCache.set(path, getJSON(path).then(SigmaGraph.expandRoutes).catch(err => { routeCache.delete(path); throw err; }));
    }
    return routeCache.get(path);
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
  const fmtDist = v => {
    if (!isNum(v)) return '—';
    if (meta.distance_unit !== 'm') return `${fmtNum(v, 1)} ${meta.distance_unit}`;
    return v >= 1000 ? `${(v / 1000).toFixed(v >= 10000 ? 1 : 2)} km` : `${Math.round(v)} m`;
  };
  // Refinement overlay: all help icons use one viewport-positioned tooltip.
  // Unlike a CSS-only tooltip, this is not clipped by the scrolling side panel.
  const statHelp = {'SIGMA score': 'Published SIGMA score for the selected establishment, when present; point size in the map reflects this score. Not a technical coefficient.', 'Cluster centrality': 'Published centrality of the selected sector-cluster node, distinct from individual input-output link strengths.', 'Establishments in cluster': 'Number of establishments assigned to this sector-cluster in the published result.', 'Linked clusters': 'Distinct adjacent cluster nodes in the full X graph, before the current sector, direction and strongest-link filters.', 'X edges in / out': 'Published number of directed edges entering / leaving this X node, before the current screen filters.', 'PSIC': 'Philippine Standard Industrial Classification code of the selected establishment when available. A dash means unavailable.'};
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

  const sectorLabel = code => (sectors.get(code) || {}).label || code;
  const sectorColor = code => (sectors.get(code) || {}).color || '#657f78';
  const nodeLabel = n => `${sectorLabel(n.type)} · cluster ${n.cluster}`;
  const shortLabel = n => `${n.type}·${n.cluster}`;
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
      setData('points', EMPTY());
      visibility('overview-counts', false);
      updateStatus(meta.profile === 'public' ? 'Public profile: establishment-level locations are not included. Select a cluster center.' : null);
      return;
    }
    if (total > meta.point_budget) {
      setData('points', EMPTY());
      visibility('overview-counts', true);
      updateStatus(`${total.toLocaleString()} establishments in view (more than ${meta.point_budget.toLocaleString()}). The green shading shows where they are; zoom in to see individual establishments.`);
      return;
    }
    visibility('overview-counts', false);
    try {
      const groups = await Promise.all(keys.map(key => getJSON(`data/tiles/${z}/${key}.geojson`)));
      if (epoch !== tileEpoch) return;
      setData('points', {type: 'FeatureCollection', features: groups.flatMap(g => g.features)});
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

  function applyEmphasis() {
    const ids = network ? [...network.ring.keys()] : null;
    const focus = network ? network.focus : '';
    const inNet = ['in', ['get', 'node_id'], ['literal', ids || []]];
    const isFocus = ['==', ['get', 'node_id'], focus];
    map.setPaintProperty('establishments', 'circle-opacity', ids ? ['case', isFocus, 0.96, inNet, 0.90, 0.025] : 0.78);
    map.setPaintProperty('establishments', 'circle-stroke-opacity', ids ? ['case', inNet, 1, 0.025] : 1);
    map.setPaintProperty('establishments', 'circle-stroke-width', ids ? ['case', isFocus, 0.9, 0.35] : 0.35);
    map.setPaintProperty('establishments', 'circle-stroke-color', ids ? ['case', isFocus, COLOR.focus, '#ffffff'] : '#ffffff');
    const centerIn = ['in', ['get', 'id'], ['literal', ids || []]];
    // Linked clusters are sector-filled with thin blue outlines. The focused
    // triangle is handled by the larger selected-center symbol above this layer.
    // Alternate icon assets remove white triangle interiors in dark mode;
    // linked and focused sector colors remain intact.
    const baseIcon = themeMode === 'dark' ? 'dark_center_icon' : 'center_icon';
    const connectedIcon = themeMode === 'dark' ? 'dark_linked_center_icon' : 'linked_center_icon';
    map.setLayoutProperty('centers', 'icon-image', ids ?
      ['case', centerIn, ['get', connectedIcon], ['get', baseIcon]] :
      ['get', baseIcon]);
    map.setPaintProperty('centers', 'icon-opacity', ids ?
      ['case', ['==', ['get', 'id'], focus], 0, centerIn, 1, 0.16] : 1);
    map.setFilter('establishments', notHidden());
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

  async function showRoutes() {
    const epoch = ++routeEpoch;
    ++hoverEpoch;
    setData('route-hover', EMPTY());
    const n = network && nodeIndex.get(network.focus);
    if (!n || !n.route_file || !network.direct.length) { setData('routes', EMPTY()); return; }
    try {
      const fc = await getRoutes(n.route_file);
      if (epoch !== routeEpoch) return;
      const keep = new Map(network.direct.map(r => [r.other, r]));
      const strongest = Math.max(1e-12, ...network.direct.map(r => r.strength));
      const features = fc.features.filter(f => {
        const r = keep.get(f.properties.other);
        if (!r) return false;
        return f.properties.direction === 'outgoing' ? !!r.out : !!r.in;
      }).map(f => {
        const c = f.properties.coefficient;
        return {...f, properties: {...f.properties,
          kind: f.properties.direction,
          wn: Math.sqrt((isNum(c) ? c : 0) / strongest),
        }};
      });
      features.sort((a, b) => a.properties.wn - b.properties.wn);
      setData('routes', {type: 'FeatureCollection', features});
    } catch (err) { if (epoch === routeEpoch) showError(err); }
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
    $('connections-section').hidden = !selection;
    $('central-section').hidden = !!selection;
    $('selection-actions').hidden = !selection;
    if (!selection) {
      $('selected-code').textContent = '';
      $('place-name').textContent = 'No selection';
      $('place-description').textContent = 'Click an establishment or a cluster center on the map. Its cluster and the clusters linked to it in network X are then shown on the map and below.';
      $('stats').replaceChildren();
      return;
    }
    const n = nodeIndex.get(selection.id), p = selection.point;
    $('selected-code').textContent = `Sector ${n.type} · Cluster ${n.cluster}`;
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

  // ------------------------------------------------------------------ network diagram
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
      return {group: 'nodes', data: {id, label: shortLabel(n), color: sectorColor(n.type), ring, level: maxRing - ring + 1},
        classes: id === network.focus ? 'focus' : ''};
    });
    const directedIds = new Set(network.edges.map(e => `${e.source}\u0000${e.target}`));
    network.edges.forEach((e, i) => {
      if (!network.ring.has(e.source) || !network.ring.has(e.target)) return;
      const outgoing = e.source === network.focus;
      const incoming = e.target === network.focus;
      const reciprocal = directedIds.has(`${e.target}\u0000${e.source}`);
      const classes = [outgoing || incoming ? 'focus-edge' : '', outgoing ? 'outgoing' : '',
        incoming ? 'incoming' : '', reciprocal ? 'reciprocal' : ''].join(' ');
      elements.push({group: 'edges', data: {id: `e${i}`, source: e.source, target: e.target,
        wn: Math.sqrt(e.strength / strongest), coefficient: e.coefficient,
        distance: e.distance, weight: e.weight}, classes});
    });
    cy.add(elements);
    if (ids.length <= LIMIT.labelledNodes) cy.nodes().addClass('labelled');
    cy.layout({name: 'concentric', concentric: n => n.data('level'), levelWidth: () => 1, minNodeSpacing: 6,
      startAngle: 1.5 * Math.PI, clockwise: true, equidistant: true, avoidOverlap: true, animate: false, fit: true, padding: 26}).run();
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

  // ------------------------------------------------------------------ selection
  function refresh() {
    network = selection && nodeIndex.has(selection.id) ? buildNetwork(selection.id) : null;
    renderSectors();  // Re-rank sectors when selection or Strongest changes.
    renderSelection();
    drawGraph();
    renderConnections();
    if (!ready) return;
    applyEmphasis();
    showRoutes();
    updateStatus();
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
    setData('selected-center', {type: 'FeatureCollection', features: isNum(n.lon) ? [
      {type: 'Feature', properties: {type: n.type, icon: selectedIconByType.get(String(n.type)) || 'sigma-center-selected-default'}, geometry: {type: 'Point', coordinates: [n.lon, n.lat]}}] : []});
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

  function renderSectors() {
    const list = $('sector-list');
    list.replaceChildren();
    const linked = displayedSectorStrength();
    const codeOrder = (a, b) => String(a.code).localeCompare(String(b.code), undefined,
      {numeric: true, sensitivity: 'base'});
    const ordered = [...sectors.values()].sort((a, b) => {
      if (!network || hidden.size === sectors.size) return codeOrder(a, b);
      if (network) {
        const aa = linked.get(a.code), bb = linked.get(b.code);
        if ((aa !== undefined) !== (bb !== undefined)) return aa !== undefined ? -1 : 1;
        if (aa !== undefined && aa !== bb) return bb - aa;
      }
      const ga = globalSectorStrength.get(a.code) ?? -1;
      const gb = globalSectorStrength.get(b.code) ?? -1;
      return (gb - ga) || String(a.label).localeCompare(String(b.label));
    });
    for (const s of ordered) {
      const box = el('input', {type: 'checkbox', checked: !hidden.has(s.code)});
      box.addEventListener('change', () => { box.checked ? hidden.delete(s.code) : hidden.add(s.code); sectorsChanged(); });
      const inSelection = network && linked.has(s.code);
      const score = inSelection ? linked.get(s.code) : globalSectorStrength.get(s.code);
      const description = inSelection ? 'Strongest visible direct link to selected cluster' :
        'Largest link coefficient anywhere in the published graph' ;
      list.append(el('label', {className: 'sector-item',
          title: `${s.label}: ${s.points.toLocaleString()} establishments, ${s.clusters} clusters. ${description}: ${isNum(score) ? fmtCoef(score) : 'not available'}`},
        box, swatch(s.code), el('span', {className: 'name', textContent: s.label}),
        el('span', {className: 'sector-strength', title: description,
          textContent: isNum(score) ? fmtCoef(score) : '—'}),
        el('span', {className: 'count', textContent: s.points.toLocaleString()})));
    }
    $('sector-count').textContent = `${sectors.size - hidden.size} of ${sectors.size} shown`;
  }

  function sectorsChanged() {
    renderSectors();
    renderCentral();
    refresh();
  }

  // ------------------------------------------------------------------ map popups
  function describe(feature) {
    const p = feature.properties, id = feature.layer.id;
    if (id === 'establishments') {
      return [p.name, sectorLabel(p.type), `Cluster ${p.type}·${p.cluster} · SIGMA score ${fmtNum(p.score)}`];
    }
    if (id === 'centers') {
      const n = nodeIndex.get(p.id);
      return n ? [nodeLabel(n), `${fmtNum(n.members, 0)} establishments · centrality ${fmtNum(n.centrality)}`, 'Cluster center'] : [p.id];
    }
    return null;
  }

  // Routes of reciprocal edges, and routes that share the first road segments, lie on the
  // same pixels. List every route under the cursor, one block per linked cluster.
  function describeRoutes(hits) {
    const focus = network && nodeIndex.get(network.focus);
    if (!focus) return [];
    const byOther = new Map();
    for (const h of hits) {
      const p = h.properties;
      if (!byOther.has(p.other)) byOther.set(p.other, {});
      byOther.get(p.other)[p.kind] = p;
    }
    const blocks = [];
    for (const [other, rel] of byOther) {
      const n = nodeIndex.get(other);
      if (!n) continue;
      const rows = [];
      if (rel.outgoing) rows.push(`→ Supplies inputs to it: a = ${fmtCoef(rel.outgoing.coefficient)} (X weight ${fmtNum(rel.outgoing.weight)})`);
      if (rel.incoming) rows.push(`← Uses inputs from it: a = ${fmtCoef(rel.incoming.coefficient)} (X weight ${fmtNum(rel.incoming.weight)})`);
      rows.push(`Road distance ${fmtDist((rel.outgoing || rel.incoming).distance)}`);
      const strength = Math.max(rel.outgoing ? rel.outgoing.coefficient || 0 : 0, rel.incoming ? rel.incoming.coefficient || 0 : 0);
      blocks.push({title: `${shortLabel(focus)} and ${nodeLabel(n)}`, rows, strength});
    }
    return blocks.sort((a, b) => b.strength - a.strength);
  }

  const POPUP_BLOCKS = 3;
  function onHover(event) {
    const layers = ['centers', 'establishments', 'routes', 'routes-in'].filter(l => map.getLayer(l) && map.getLayoutProperty(l, 'visibility') !== 'none');
    const hits = map.queryRenderedFeatures(event.point, {layers});
    const places = hits.filter(h => h.layer.id === 'centers' || h.layer.id === 'establishments');
    map.getCanvas().style.cursor = places.length ? 'pointer' : '';
    let content = null;
    if (places.length) {
      const lines = describe(places[0]);
      if (lines) content = el('div', {}, el('div', {className: 'popup-title', textContent: lines[0]}),
        ...lines.slice(1).map(text => el('div', {className: 'popup-row', textContent: text})));
    } else {
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

  function onClick(event) {
    popup.remove();
    const layers = ['centers', 'establishments'].filter(l => map.getLayer(l) && map.getLayoutProperty(l, 'visibility') !== 'none');
    const hits = map.queryRenderedFeatures(event.point, {layers});
    if (!hits.length) return;
    const f = hits[0];
    if (f.layer.id === 'centers') selectNode(f.properties.id);
    else selectNode(f.properties.node_id, {...f.properties, coordinates: f.geometry.coordinates});
  }

  // ------------------------------------------------------------------ setup
  // A white inverted triangle with a sector-colored outline for each economic type.
  // Canvas images are registered once after MapLibre's style has loaded.
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
      addTriangle(darkName, '#21392b', sectorFill);
      addTriangle(darkLinkedName, sectorFill, '#8cc8e9');
      centerIconByType.set(key, name);
      linkedCenterIconByType.set(key, linkedName);
      darkCenterIconByType.set(key, darkName);
      darkLinkedIconByType.set(key, darkLinkedName);
      index++;
    }
    addTriangle(baseFallback, '#ffffff', '#657f78');
    addTriangle(linkedFallback, '#657f78', COLOR.incoming);
    addTriangle(darkFallback, '#21392b', '#657f78');
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
    const width = (a, b) => ['interpolate', ['linear'], ['get', 'wn'], 0, a, 1, b];
    map.addLayer({id: 'routes-casing', type: 'line', source: 'routes', layout: {'line-join': 'round', 'line-cap': 'round'},
      paint: {'line-color': '#ffffff', 'line-width': width(1.35, 3.25), 'line-opacity': 0.85}});
    map.addLayer({id: 'routes', type: 'line', source: 'routes', filter: ['==', ['get', 'kind'], 'outgoing'],
      layout: {'line-join': 'round', 'line-cap': 'round'},
      paint: {'line-color': COLOR.outgoing, 'line-width': width(0.7, 2.2), 'line-opacity': 0.86}});
    map.addLayer({id: 'routes-in', type: 'line', source: 'routes', filter: ['==', ['get', 'kind'], 'incoming'],
      layout: {'line-join': 'round', 'line-cap': 'round'},
      paint: {'line-color': COLOR.incoming, 'line-width': width(0.7, 2.2), 'line-opacity': 0.86,
        'line-dasharray': [2, 1]}});
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
    map.addLayer({id: 'establishments', type: 'circle', source: 'points', paint: {
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
    $('graph-fit').addEventListener('click', () => { cy.resize(); cy.fit(undefined, 35); });
    $('zoom-network').addEventListener('click', zoomToNetwork);
    $('sectors-all').addEventListener('click', () => { hidden.clear(); sectorsChanged(); });
    $('sectors-none').addEventListener('click', () => { for (const code of sectors.keys()) hidden.add(code); sectorsChanged(); });
    document.addEventListener('keydown', e => {
      if (e.key !== 'Escape') return;
      if (document.body.classList.contains('theater')) toggleTheater();
      else if (selection) clearSelection();
    });
  }

  async function initialize() {
    $('theme-mode').addEventListener('change', e => applyTheme(e.target.value));
    applyTheme('light');
    initializeHelp();
    const [metadata, graph, tiles] = await Promise.all([getJSON('data/metadata.json'), getJSON('data/graph.json'), getJSON('data/tiles.json')]);
    meta = metadata; tileIndex = tiles; tileKeys = Object.keys(tiles.tiles || {});
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

    cy = cytoscape({container: $('network'), elements: [], layout: {name: 'preset'}, style: [
      {selector: 'node', style: {'background-color': 'data(color)', 'width': 14, 'height': 14, 'border-width': 1, 'border-color': '#f0f4f1', 'opacity': 0.96, 'label': ''}},
      {selector: 'node.labelled', style: {'label': 'data(label)', 'font-size': 10, 'font-weight': 500, 'font-family': 'system-ui, sans-serif', 'color': '#4b5e53', 'text-valign': 'bottom', 'text-halign': 'center', 'text-margin-y': 7, 'text-background-opacity': 0, 'text-outline-width': 0}},
      {selector: 'node[ring >= 2]', style: {'width': 11, 'height': 11, 'opacity': 0.84}},
      {selector: 'node.focus', style: {'width': 28, 'height': 28, 'background-color': '#255b45', 'border-width': 1.5, 'border-color': '#a5c3b1', 'opacity': 1, 'label': 'data(label)', 'font-family': 'system-ui, sans-serif', 'font-size': 11, 'font-weight': 'bold', 'color': '#245541', 'text-valign': 'bottom', 'text-halign': 'center', 'text-margin-y': 7, 'text-outline-width': 0, 'text-background-opacity': 0, 'z-index': 10}},
      {selector: 'edge', style: {'width': 'mapData(wn, 0, 1, 0.3, 1.3)', 'line-color': '#9eafa5', 'opacity': 0.20, 'curve-style': 'bezier', 'control-point-step-size': 13, 'target-arrow-color': '#9eafa5', 'source-arrow-color': '#9eafa5', 'arrow-scale': 0.52}},
      {selector: 'edge', style: {'target-arrow-shape': 'triangle'}},
      {selector: 'edge.focus-edge', style: {'opacity': 0.78, 'z-index': 5}},
      {selector: 'edge.focus-edge.reciprocal', style: {'opacity': 0.86}},
      {selector: 'edge.focus-edge.outgoing', style: {'line-color': '#b35a4f', 'target-arrow-color': '#b35a4f', 'source-arrow-color': '#b35a4f'}},
      {selector: 'edge.focus-edge.incoming', style: {'line-color': '#39779a', 'target-arrow-color': '#39779a', 'source-arrow-color': '#39779a'}},
    ]});
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
      style: {version: 8, sources: {}, layers: [{id: 'background', type: 'background', paint: {'background-color': '#f4f6f5'}}]},
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
        map.on('mousemove', onHover);
        map.on('mouseout', () => popup.remove());
        map.on('click', onClick);
        map.on('moveend', loadVisiblePoints);
        bindControls();
        await loadVisiblePoints();
        const fromHash = decodeURIComponent(location.hash.slice(1));
        if (fromHash && nodeIndex.has(fromHash)) selectNode(fromHash, null, {fly: true});
        else refresh();
      } catch (err) { showError(err); }
    });
  }

  initialize().catch(showError);
})();
