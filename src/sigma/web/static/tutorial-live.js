/* SIGMA Explorer guided tour: a read-only lens over published Explorer data.
 * No recomputation, external API, guessed establishment transactions or
 * location services. Works with both local and public-profile bundles.
 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  // sigma-tutorial-return-url-repair-v1: preserve THIS tab's mode and cluster.
  const explorerReturnUrl = id => {
    const mode = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
    return `index.html?theme=${mode}` + (id ? `#${encodeURIComponent(id)}` : '');
  };
  const fmt = (v, dp = 0) => typeof v === 'number' && Number.isFinite(v)
    ? v.toLocaleString(undefined, {maximumFractionDigits: dp}) : '—';
  const frac = v => typeof v === 'number' && Number.isFinite(v)
    ? (Math.abs(v) && Math.abs(v) < .0001 ? v.toExponential(2) : v.toFixed(4)) : 'not published';
  const text = (tag, contents, className) => {
    const elt = document.createElement(tag);
    elt.textContent = String(contents);
    if (className) elt.className = className;
    return elt;
  };
  const replace = (parent, ...nodes) => parent.replaceChildren(...nodes);
  const a = (label, node) => {
    const link = text('a', label, 'live-inline-link');
    link.href = explorerReturnUrl(node && node.id);
    return link;
  };
  const idStr = v => v == null ? '' : String(v);
  const val = n => n && Number.isFinite(n.centrality) ? n.centrality : -Infinity;
  const maxByCentrality = (a, b) => val(b) - val(a) || idStr(a.id).localeCompare(idStr(b.id));

  async function start() {
    const responses = await Promise.all(['data/metadata.json', 'data/graph.json'].map(async path => {
      const r = await fetch(path, {cache: 'no-store'});
      if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
      return r.json();
    }));
    const [meta, graph] = responses;
    if (meta.schema_version !== 3 || !Array.isArray(meta.sectors) ||
        !Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) {
      throw new Error('Incompatible Explorer bundle. Run sigma view <area> --refresh.');
    }
    const nodes = graph.nodes;
    const edges = graph.edges;
    const nodeMap = new Map(nodes.map(n => [idStr(n.id), n]));
    const sectorMap = new Map(meta.sectors.map(s => [idStr(s.code), s]));
    const bySector = new Map();
    for (const node of nodes) {
      const code = idStr(node.type);
      if (!bySector.has(code)) bySector.set(code, []);
      bySector.get(code).push(node);
    }
    for (const group of bySector.values()) group.sort(maxByCentrality);
    const adjacent = new Map();
    for (const edge of edges) {
      for (const id of [idStr(edge.from), idStr(edge.to)]) {
        if (!adjacent.has(id)) adjacent.set(id, []);
        adjacent.get(id).push(edge);
      }
    }
    const counts = meta.counts || {};
    const area = meta.area || 'current study area';
    const economy = meta.economy_id || 'not identified in run metadata';
    const number = n => fmt(n);
    const sampleParam = new URLSearchParams(location.search).get('node');
    const initial = sampleParam && nodeMap.get(sampleParam);
    let chosen = initial || [...nodes].sort(maxByCentrality).find(n => (adjacent.get(idStr(n.id)) || []).length) ||
      [...nodes].sort(maxByCentrality)[0] || null;
    const sectorSelect = $('live-sector');
    const nodeSelect = $('live-node');
    const sectorLabel = code => {
      const s = sectorMap.get(idStr(code));
      return s ? `${s.label} (${s.code})` : `Sector ${code}`;
    };
    const nodeLabel = node => node ? `${sectorLabel(node.type)} · cluster ${node.cluster}` : 'No cluster available';
    const edgeInfo = node => (adjacent.get(idStr(node && node.id)) || []).slice().sort((x,y) =>
      (Number(y.coefficient) || 0) - (Number(x.coefficient) || 0));
    const topSectors = [...meta.sectors].sort((x, y) => (y.points || 0) - (x.points || 0))
      .slice(0, 3).map(s => `${s.label}: ${number(s.points)} places`).join(' · ');
    $('live-title').textContent = `${area} · ${economy}`;
    $('live-status').textContent = meta.profile === 'public'
      ? 'Published aggregate profile · individual places excluded'
      : 'Published local profile · individual places available in Explorer';
    const statValues = [
      ['Establishments', number(counts.points)],
      ['Sector clusters', number(counts.clusters)],
      ['Directed X links', number(counts.edges)],
      ['Economic types', number(meta.sectors.length)]
    ];
    replace($('live-stats'), ...statValues.map(([label, value]) => {
      const block = text('div', '', 'live-stat');
      block.append(text('strong', value), text('span', label));
      return block;
    }));
    for (const s of meta.sectors) {
      const option = document.createElement('option');
      option.value = idStr(s.code); option.textContent = `${s.label} (${s.code})`;
      sectorSelect.append(option);
    }
    if (!meta.sectors.length || !nodes.length) {
      sectorSelect.disabled = !meta.sectors.length;
      nodeSelect.disabled = true;
    }
    function fillNodes(code, keepId) {
      replace(nodeSelect);
      const group = bySector.get(code) || [];
      for (const node of group) {
        const opt = document.createElement('option');
        opt.value = idStr(node.id);
        opt.textContent = `Cluster ${node.cluster} · ${number(node.members)} members · C ${fmt(node.centrality, 5)}`;
        nodeSelect.append(opt);
      }
      chosen = nodeMap.get(keepId) && idStr(nodeMap.get(keepId).type) === code ? nodeMap.get(keepId) : (group[0] || null);
      if (chosen) nodeSelect.value = idStr(chosen.id);
      nodeSelect.disabled = group.length === 0;
    }
    function lens() {
      if (chosen) {
        sectorSelect.value = idStr(chosen.type);
        nodeSelect.value = idStr(chosen.id);
      }
      const target = $('live-focus');
      if (chosen) {
        const links = edgeInfo(chosen);
        const detail = text('p', `${nodeLabel(chosen)} has ${number(chosen.members)} establishments, ` +
          `${number(chosen.in_degree)} published incoming and ${number(chosen.out_degree)} outgoing X links. ` +
          `Its published centrality is ${fmt(chosen.centrality, 6)}.`, 'live-focus-description');
        const linkText = links.length ?
          `Example modeled link: ${sectorLabel(nodeMap.get(idStr(links[0].from))?.type || '?')} → ` +
          `${sectorLabel(nodeMap.get(idStr(links[0].to))?.type || '?')}, coefficient ${frac(links[0].coefficient)}.` :
          'No incident X links were published for this cluster.';
        replace(target, detail, text('p', linkText, 'live-focus-connection'));
        $('live-open-cluster').href = explorerReturnUrl(chosen.id);
        $('live-open-cluster').hidden = false;
        $('live-back-top').href = explorerReturnUrl(chosen.id);
      } else {
        replace(target, text('p', 'This published bundle has no X nodes. The original worked figures remain available.'));
        $('live-open-cluster').hidden = true;
      }
      populateNotes();
      paintGeography();
    }
    sectorSelect.addEventListener('change', () => {fillNodes(sectorSelect.value, null); lens();});
    nodeSelect.addEventListener('change', () => {chosen = nodeMap.get(nodeSelect.value) || null; lens();});

    const shortInfo = (section, idx) => {
      const node = chosen;
      const links = node ? edgeInfo(node) : [];
      const example = links[0];
      const s = node && sectorMap.get(idStr(node.type));
      const here = s ? `${s.label} (${s.code})` : 'the selected sector';
      const clusterCount = (bySector.get(idStr(node?.type)) || []).length;
      const c = k => number(counts[k]);
      const note = (what, certainty = '') => [what, certainty];
      if (section === 'places') {
        if (idx === 0) return note(`The current ${area} bundle contains ${c('points')} canonical establishments across ${number(meta.sectors.length)} economic types. Its individual OSM and Overture source records are not exposed here.`, 'Published output; not raw source counts');
        if (idx <= 3) return note('Record candidate distances, fuzzy-name matching decisions, and canonical-source pairs are not exported to Explorer. The figure is a worked illustration, not a reconstruction of actual matching.', 'Intermediate provenance must be examined in the SIGMA pipeline outputs');
        return note(`${here}: ${number(s?.points)} establishments in this published economy. ${number(counts.unassigned_points)} establishments across the entire area have no assigned X node.`, 'Published sector assignments and node membership');
      }
      if (section === 'roads') {
        if (idx === 0) return note(`${c('roads')} road features appear in this bundle (${meta.has_roads ? 'road layer included' : 'road layer omitted'}); distances use ${meta.distance_unit || 'unspecified units'}. The exact published X routes can be explored on the map.`, 'Visual road feature count, not graph-vertex count');
        if (idx === 1) return note('Road junction identities and overpass connectivity are intermediate graph data and are not exposed in Explorer. The network diagram uses published results.', 'Method illustration only');
        if (idx === 2) return note(`The currently selected cluster's published road-center distances are visible on individual X links. Establishment snap offsets are not in this browser bundle.`, 'Do not equate cluster-to-cluster distances with individual place snap distances');
        return note(example ? `An actual X link connected to this cluster has published road distance ${fmt(example.distance, 1)} ${meta.distance_unit || ''}. The illustration above is not that route.` : 'No adjacent X link is available for a real road-distance example.', 'The Explorer map shows exact published routes');
      }
      if (section === 'clusters') {
        if (idx === 0) return note(`${here} contains ${number(clusterCount)} published clusters representing ${number(s?.points)} establishments in ${area}. Not all establishments necessarily belong to a cluster.`, 'Actual X-node cluster counts');
        return note(`This run contains ${c('clusters')} X nodes. The plotted core-distance search, minimum spanning tree, ε cuts, stability calculations, and radius trials are worked examples rather than exported intermediate results.`, 'Mathematics shown in this tutorial is illustrative');
      }
      if (section === 'centers') return note(node ? `The published center of ${nodeLabel(node)} is at latitude ${fmt(node.lat, 6)}, longitude ${fmt(node.lon, 6)}, with ${number(node.members)} member establishments.` : 'No published center selected.', 'Center method and fallback diagnostics are not contained in the browser graph');
      if (section === 'voronoi') return note(`${c('partitions')} cluster polygon features are included in the bundle. These are derived area renderings; view the selected network partitions in Explorer.`, 'A partition need not contain establishments everywhere in its area');
      if (section === 'economy') {
        if (idx === 0) return note(`Current economic specification: ${economy}, with ${number(meta.sectors.length)} types visible in this area. Explorer publishes derived X links, not the full national transactions matrix Z.`, 'Do not infer transaction amounts from coefficients');
        if (idx === 1) return note(example ? `For a published local X link, the input–output coefficient a is ${frac(example.coefficient)} from ${sectorLabel(nodeMap.get(idStr(example.from))?.type)} to ${sectorLabel(nodeMap.get(idStr(example.to))?.type)}.` : `No local X edge is available to illustrate coefficients.`, 'Observed in model output; not evidence of direct firm-to-firm trade');
        return note(`The economy identifier is ${economy}. Explorer does not publish the full coefficient matrix or distinguish optional preprocessing parameters here.`, 'Consult the source economic artifacts for the full table');
      }
      if (section === 'xgraph') {
        if (idx === 0) return note(`${c('clusters')} X nodes and ${c('edges')} directed X links (or ${c('linked_pairs')} linked node pairs) appear in ${area}.`, 'Sector coupling is a model, not confirmed commercial trade');
        if (idx === 1) return note(example ? `Published link: ${sectorLabel(nodeMap.get(idStr(example.from))?.type)} → ${sectorLabel(nodeMap.get(idStr(example.to))?.type)}; a = ${frac(example.coefficient)}, road distance = ${fmt(example.distance, 2)} ${meta.distance_unit || ''}, X weight = ${frac(example.weight)}.` : 'No incident X link for this cluster.', 'The X weight is a model quantity, not a trade probability');
        if (idx <= 4) return note(node ? `In this run, ${nodeLabel(node)} has published centrality ${fmt(node.centrality, 6)} and degrees ${number(node.in_degree)} in / ${number(node.out_degree)} out.` : 'No cluster is selected.', 'Raw Katz in/out scores and α configuration are not present in the Explorer bundle');
        return note('The published X graph provides combined centrality, not the complete Katz iteration history or separately normalized sender/receiver contributions.', 'Worked diagrams remain illustrative');
      }
      if (section === 'score') {
        if (idx === 0) return note(`Published establishment-score range in ${area}: ${fmt(meta.score_range?.[0], 6)} to ${fmt(meta.score_range?.[1], 6)}.`, meta.profile === 'public' ? 'Individual establishment records are omitted from this bundle' : 'Inspect an individual published establishment score by selecting its point in Explorer');
        return note(node ? `For ${nodeLabel(node)}, the published cluster centrality is ${fmt(node.centrality, 6)}. The tutorial’s point-level worked example is illustrative.` : 'Choose an X cluster above to inspect its published centrality.', 'No artificial establishment score is derived from the cluster center');
      }
      return note(`This is a ${meta.profile || 'unknown'} profile for ${area}, using ${economy}. Top sectors by place count: ${topSectors || 'none published'}.`, 'The dataset is a snapshot of previously computed SIGMA outputs, not a live economic feed');
    };
    const notes = [];
    for (const scrolly of document.querySelectorAll('.scrolly')) {
      const id = scrolly.dataset.fig;
      for (const [idx, article] of [...scrolly.querySelectorAll('.step')].entries()) {
        const panel = text('div', '', 'live-step');
        const caption = text('div', `CURRENT RUN · ${area.toUpperCase()}`, 'live-step-title');
        const body = text('p', '', 'live-step-content');
        const foot = text('div', '', 'live-step-caution');
        panel.append(caption, body, foot);
        article.append(panel);
        notes.push({id, idx, body, foot});
      }
    }
    function populateNotes() {
      for (const item of notes) {
        const [desc, caution] = shortInfo(item.id, item.idx);
        item.body.textContent = desc;
        item.foot.textContent = caution;
      }
    }
    function paintGeography() {
      const svg = $('live-map');
      const ns = 'http://www.w3.org/2000/svg';
      const make = (tag, attrs) => {
        const item = document.createElementNS(ns, tag);
        for (const [name, value] of Object.entries(attrs || {})) item.setAttribute(name, String(value));
        return item;
      };
      replace(svg);
      const pts = nodes.filter(n => Number.isFinite(n.lon) && Number.isFinite(n.lat));
      if (!pts.length) {svg.append(make('text', {x: 18, y: 30, fill: 'var(--muted)'}));svg.lastChild.textContent='No cluster center coordinates available.';return;}
      const b = meta.bounds && meta.bounds.length === 4 ? meta.bounds : [Math.min(...pts.map(n=>n.lon)), Math.min(...pts.map(n=>n.lat)), Math.max(...pts.map(n=>n.lon)), Math.max(...pts.map(n=>n.lat))];
      const lat0 = (b[1] + b[3]) / 2 * Math.PI / 180;
      const dx = Math.max(0.000001, (b[2] - b[0]) * Math.cos(lat0));
      const dy = Math.max(0.000001, b[3] - b[1]);
      const factor = Math.min(550 / dx, 220 / dy);
      const width = dx * factor, height = dy * factor;
      const x0 = (620 - width) / 2, y0 = (275 - height) / 2;
      const xy = n => [x0 + ((n.lon - b[0]) * Math.cos(lat0)) * factor,
        275 - y0 - (n.lat - b[1]) * factor];
      const bg = make('rect', {x: x0, y: y0, width, height, rx: 4, fill: 'transparent', stroke: 'var(--line)', 'stroke-dasharray': '4 5'});
      svg.append(bg);
      const sorted = [...pts].sort((u, v) => idStr(u.id).localeCompare(idStr(v.id)));
      const step = Math.max(1, Math.ceil(sorted.length / 900));
      const samples = sorted.filter((_, i) => i % step === 0);
      if (chosen && !samples.includes(chosen) && Number.isFinite(chosen.lon) && Number.isFinite(chosen.lat)) samples.push(chosen);
      for (const node of samples) {
        if (node === chosen) continue;
        const [x, y] = xy(node);
        const sector = sectorMap.get(idStr(node.type));
        const dot = make('circle', {cx: x, cy: y, r: 2.5, fill: sector?.color || 'var(--grey)', opacity: 0.57, tabindex: 0, role: 'button', 'aria-label': `Select ${nodeLabel(node)}`});
        dot.append(make('title'));
        dot.firstChild.textContent = nodeLabel(node);
        dot.addEventListener('click', () => choose(node));
        dot.addEventListener('keydown', e => {if (e.key === 'Enter' || e.key === ' ') {e.preventDefault();choose(node);}});
        svg.append(dot);
      }
      if (chosen && Number.isFinite(chosen.lon) && Number.isFinite(chosen.lat)) {
        const [x, y] = xy(chosen);
        svg.append(make('circle', {cx: x, cy: y, r: 9, fill: 'none', stroke: 'var(--ink)', 'stroke-width': 2}));
        svg.append(make('circle', {cx: x, cy: y, r: 4.5, fill: sectorMap.get(idStr(chosen.type))?.color || 'var(--teal)', stroke: '#fff', 'stroke-width': 1.5}));
      }
    }
    function choose(node) {
      chosen = node;
      fillNodes(idStr(node.type), idStr(node.id));
      lens();
    }
    if (chosen) fillNodes(idStr(chosen.type), idStr(chosen.id));
    else if (meta.sectors[0]) fillNodes(idStr(meta.sectors[0].code), null);
    lens();
  }
  start().catch(error => {
    $('live-status').textContent = `Published run could not be loaded: ${error.message || error}`;
    $('live-title').textContent = 'Tutorial examples only';
    $('live-focus').textContent = 'The methodological walkthrough below still works. Open this tutorial from a freshly generated SIGMA Explorer bundle to show area-specific evidence.';
    $('live-sector').disabled = true;
    $('live-node').disabled = true;
    $('live-open-cluster').hidden = true;
    console.error('SIGMA guided tour', error);
  });
})();
