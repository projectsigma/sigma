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


  // sigma-explorer-tutorial-polish-20261027-v2: readable published identifiers.
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

  function sectorDisplay(sector) {
    const rawCode = idStr(sector?.code).trim();
    const code = sparseSectorCode(rawCode);
    let name = idStr(sector?.label).trim() || rawCode;
    // The published label may be e.g. "80:72:OTHER - IO80 72 · ... · Other (80:72:OTHER)".
    const escapeRegex = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    if (rawCode) {
      name = name.replace(new RegExp('\\s*\\(' + escapeRegex(rawCode) + '\\)\\s*$', 'i'), '');
      name = name.replace(new RegExp('^' + escapeRegex(rawCode) + '\\s*[-–—:·]\\s*', 'i'), '');
    }
    name = name.replace(/^IO(?:240|80|16)\s+\d+\s*[·–—-]\s*/i, '');
    name = name.replace(/^\d+\s+(?=[A-Za-z])/, '');
    if (/:OTHER$|:O$/i.test(rawCode)) {
      name = name.replace(/\s*[·–—-]\s*Other(?:\s+industries)?\s*$/i, '');
      name = name.replace(/\s*\(others?\)\s*$/i, '');
      name = name.replace(/\s*[–—-]\s*other industries\s*$/i, '');
      name = (name.trim() || 'Other industries') + ' (others)';
    }
    return {code, name:name.trim() || code};
  }
  function economyDisplayName(value) {
    if (/io240/i.test(String(value)) && /hierarchical/i.test(String(value))) return 'Area-specific hierarchical IO economy';
    if (/^psa-2018-io80$/i.test(value)) return 'PSA 2018 · IO80';
    if (/^psa-2018-io16$/i.test(value)) return 'PSA 2018 · IO16';
    return value;
  }

  // sigma-under-the-hood-current-run-hierarchy-3a-20261102-v1:
  // Metadata is small; show useful run information before requesting the big graph.
  async function start() {
    const fetchJSON = async path => {
      const r = await fetch(path, {cache: 'no-store'});
      if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
      return r.json();
    };
    const meta = await fetchJSON('data/metadata.json');
    if (!meta || meta.schema_version !== 3 || !Array.isArray(meta.sectors)) {
      throw new Error('Incompatible Explorer metadata. Run sigma view <area> --refresh.');
    }
    // sigma-under-the-hood-gravity-tile-area-20261109-v1: stage 15 values for the figures.
    window.dispatchEvent(new CustomEvent('sigma:tile-area', {
      detail: {tile: meta.tile_area || null, area: meta.area || 'current study area'}
    }));
    // Independent summary survives missing or oversized graph.json.
    {
      const counts = meta.counts || {};
      const area = meta.area || 'current study area';
      const economy = meta.economy_id || 'not identified in run metadata';
      $('live-title').textContent = `${area} · ${economyDisplayName(economy)}`;
      $('live-title').title = `Source economic specification: ${economy}`;
      const values = [
        ['Establishments', fmt(counts.points)],
        ['Sector clusters', fmt(counts.clusters)],
        ['Directed X links', fmt(counts.edges)],
        ['Economic types', fmt(meta.sectors.length)]
      ];
      replace($('live-stats'), ...values.map(([label, value]) => {
        const block = text('div', '', 'live-stat');
        block.append(text('strong', value), text('span', label));
        return block;
      }));
      $('live-status').textContent = 'Published run summary loaded · loading cluster details…';
    }
    // Yield one frame so the summary can paint before parsing potentially large X data.
    await new Promise(resolve => setTimeout(resolve, 0));
    let graph;
    let partialGraph = false;
    let graphProblem = '';
    try {
      graph = await fetchJSON('data/graph.json');
      if (!graph || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) {
        throw new Error('data/graph.json has an incompatible shape');
      }
    } catch (error) {
      // sigma-current-run-resilience-20261103-v2: the geographic node index
      // is already part of the Explorer bundle, even when the large graph fails.
      graphProblem = String(error && (error.message || error));
      console.warn('SIGMA tutorial full X graph unavailable; using published center locations', error);
      const centers = await fetchJSON('data/nodes.geojson');
      if (!centers || !Array.isArray(centers.features)) {
        throw new Error(`Neither graph.json nor nodes.geojson is usable: ${graphProblem}`);
      }
      const fallbackNodes = centers.features.filter(f => {
        const coords = f && f.geometry && f.geometry.coordinates;
        return f && f.properties && f.properties.id != null &&
          Array.isArray(coords) && coords.length >= 2 &&
          Number.isFinite(Number(coords[0])) && Number.isFinite(Number(coords[1]));
      }).map(f => ({
        id: String(f.properties.id), type: String(f.properties.type),
        cluster: f.properties.cluster, lon: Number(f.geometry.coordinates[0]),
        lat: Number(f.geometry.coordinates[1]),
        centrality: null, members: null, in_degree: null, out_degree: null,
        route_file: null,
      }));
      if (!fallbackNodes.length) {
        throw new Error(`No usable X cluster centers in nodes.geojson: ${graphProblem}`);
      }
      graph = {nodes: fallbackNodes, edges: []};
      partialGraph = true;
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
    const economyName = economyDisplayName(economy);
    const routePresentation = meta.route_mode === 'browser'
      ? 'Routes are reconstructed on demand by the browser Web Worker from the published routing graph and checked against numeric X distances.'
      : meta.route_mode === 'precomputed'
        ? 'This bundle uses published precomputed shortest-path geometries rather than browser-native routing.'
        : 'This bundle does not record its route publication mode; browser routing or precomputed paths cannot be inferred from the missing field.';
    const number = n => fmt(n);
    const sampleParam = new URLSearchParams(location.search).get('node');
    const initial = sampleParam && nodeMap.get(sampleParam);
    let chosen = initial || [...nodes].sort(maxByCentrality).find(n => (adjacent.get(idStr(n.id)) || []).length) ||
      [...nodes].sort(maxByCentrality)[0] || null;
    const sectorSelect = $('live-sector');
    const nodeSelect = $('live-node');
    const sectorLabel = code => {
      const s = sectorMap.get(idStr(code));
      return s ? `${sectorDisplay(s).name} · ${sectorDisplay(s).code}` : `Sector ${code}`;
    };
    const nodeLabel = node => node ? `${sectorLabel(node.type)} · cluster ${node.cluster}` : 'No cluster available';
    const edgeInfo = node => (adjacent.get(idStr(node && node.id)) || []).slice().sort((x,y) =>
      (Number(y.coefficient) || 0) - (Number(x.coefficient) || 0));
    // SIGMA_DOCS_20261104_LIVE_ROLLUP: metadata-backed, never guessed from examples.
    const rolledUpParents = meta.sectors.filter(s => Array.isArray(s.rollup_children) &&
      s.rollup_children.some(c => c.rolled_up === true));
    const rollupDetailAvailable = meta.profile === 'local' &&
      meta.sectors.every(s => Array.isArray(s.rollup_children));
    const rollupRunNote = rolledUpParents.length
      ? ` Derived roll-up breakdowns are published for ${rolledUpParents.length} effective sector${rolledUpParents.length === 1 ? '' : 's'}; original tags are for provenance and point presentation only.`
      : rollupDetailAvailable ? ' The local sector breakdown shows no rolled-up sectors.'
        : ' Roll-up details are not published in this bundle, so its roll-up status is unknown.';
    const topSectors = [...meta.sectors].sort((x, y) => (y.points || 0) - (x.points || 0))
      .slice(0, 3).map(s => `${sectorDisplay(s).name}: ${number(s.points)} places`).join(' · ');
    $('live-title').textContent = `${area} · ${economyName}`;
    $('live-title').title = `Source economic specification: ${economy}`;
    $('live-status').textContent = partialGraph
      ? `Published run · cluster map available; edge/centrality details unavailable (${graphProblem})`
      : (meta.profile === 'public'
        ? 'Published aggregate profile · individual places excluded'
        : 'Published local profile · individual places available in Explorer');
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
      option.value = idStr(s.code); option.textContent = `${sectorDisplay(s).name} · ${sectorDisplay(s).code}`;
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
        const linkText = partialGraph
          ? 'The published center map is available, but incident X links and Katz centrality could not be loaded in this session.'
          : links.length ?
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
      const here = s ? sectorLabel(s.code) : 'the selected sector';
      const clusterCount = (bySector.get(idStr(node?.type)) || []).length;
      const c = k => number(counts[k]);
      const note = (what, certainty = '') => [what, certainty];
      if (partialGraph && ['roads', 'economy', 'xgraph', 'gravity', 'area', 'katz', 'score'].includes(section) && idx > 0) {
        return note('The current run statistics and center positions remain available. Detailed X edge values are unavailable in this session.', 'The full graph did not load; no absent edge or unreported centrality is being inferred.');
      }
      if (section === 'places') {
        if (idx === 0) return note(`The current ${area} bundle contains ${c('points')} canonical establishments across ${number(meta.sectors.length)} economic types. Its individual OSM and Overture source records are not exposed here.`, 'Published output; not raw source counts');
        if (idx <= 3) return note('Record candidate distances, fuzzy-name matching decisions, and canonical-source pairs are not exported to Explorer. The figure is a worked illustration, not a reconstruction of actual matching.', 'Intermediate provenance must be examined in the SIGMA pipeline outputs');
        return note(`${here}: ${number(s?.points)} establishments in this published economy. ${number(counts.unassigned_points)} establishments across the entire area have no assigned X node.`, 'Published sector assignments and node membership');
      }
      if (section === 'evidence') {
        if (idx === 0) return note('Explorer does not publish the administrative-office audit. In the published pois.parquet, admin_activity_status, admin_activity_reason and admin_original_psic record each change.', 'Worked example with invented names');
        if (idx === 1) return note(`${here} is one of ${number(meta.sectors.length)} sectors in this run. Candidate IO sets and tag statuses are in pois.parquet (economy_candidate_io240, economy_status), not in this browser bundle.`, 'Published sector list; candidate sets are not exported to Explorer');
        return note('Ownership decisions are recorded in pois.parquet as institution_promotion_status, institution_evidence_basis and institution_evidence_reference. The local Explorer exposes selected sector-basis evidence, but not the full registry match, promotion trace or source references.', 'Inspect workspace pois.parquet for complete ownership provenance; public bundles omit individual establishments');
      }
      if (section === 'hierarchy') {
        const sparse = meta.sectors.some(s => sparseSectorCode(s.code).includes(':')) || /hierarch|rollup/i.test(economy);
        if (!sparse) return note(`This run uses ${number(meta.sectors.length)} sectors of a fixed economy (${economyName}). Stage 5 builds area sectors only for a generated hierarchy (the default of sigma load).`, 'From the published sector codes');
        const forms = {detailed: 0, io80Residual: 0, io80: 0, io16Residual: 0, io16: 0, other: 0};
        for (const s of meta.sectors) {
          const code = sparseSectorCode(s.code);
          if (/^\d+:\d+:\d+$/.test(code)) forms.detailed++;
          else if (/^\d+:\d+:o$/.test(code)) forms.io80Residual++;
          else if (/^\d+:\d+$/.test(code)) forms.io80++;
          else if (/^\d+:o$/.test(code)) forms.io16Residual++;
          else if (/^\d+$/.test(code)) forms.io16++;
          else forms.other++;
        }
        if (idx === 0) return note(`This run uses ${number(meta.sectors.length)} sectors: ${forms.detailed} detailed (X:Y:Z), ${forms.io80Residual} IO80 residuals (X:Y:o), ${forms.io80} whole IO80 (X:Y), ${forms.io16Residual} IO16 residuals (X:o) and ${forms.io16} whole IO16 (X)${forms.other ? `, plus ${forms.other} with another code form` : ''}.`, 'Counted from the published sector codes');
        if (idx === 1) return note('The coarse-place policy and the parents kept whole are recorded in the hierarchy audit.json of the workspace, not in this bundle.', 'The figure uses invented counts');
        return note(`Explorer publishes derived X links and coefficients, not the aggregated transaction table. Current economic specification: ${economyName}.`, 'Consult the economy artifacts for the full table');
      }
      if (section === 'handoff') return note('The bundle does not record whether the handoff was reviewed or augmented. See places/augmentations.json and the aug_<source>__ columns in the workspace.', 'Worked example with invented records');
      if (section === 'rollup') {
        const parents = rolledUpParents;
        if (!parents.length) {
          const status = rollupDetailAvailable
            ? 'The published local sector breakdown shows no rolled-up sectors.'
            : 'A roll-up breakdown is unavailable in this bundle; whether roll-up occurred is unknown.';
          return note(idx === 0 ? `${here}: ${number(s?.points)} classified places and ${number(clusterCount)} published clusters. ${status}` : status,
            rollupDetailAvailable ? 'From published local sector metadata' : 'Missing roll-up details are not evidence that roll-up did not occur');
        }
        const first = parents[0];
        const moved = first.rollup_children.filter(c => c.rolled_up === true);
        return note(`${parents.length} effective sector${parents.length === 1 ? '' : 's'} received rolled-up sectors. Example: ${sectorDisplay(first).code} now also holds ${moved.map(c => `${sparseSectorCode(c.code)} (${number(c.places)} places)`).join(', ')}.`, 'Original codes are provenance only; the effective sector is used for clustering, X and scores');
      }
      if (section === 'gap') return note(`${here} has ${number(clusterCount)} final clusters in this run (${c('clusters')} in total). The HDBSCAN* parent label (hdbscan_cluster) and median_gap_audit.json are in the clustering artifact, not in the browser bundle.`, 'Final clusters only; the Gap decision per cluster is audited in the workspace');
      if (section === 'routes') {
        if (idx === 0) return note(example ? `A published X link of this cluster: road distance ${fmt(example.distance, 1)} ${meta.distance_unit || ''}, weight ${frac(example.weight)}.` : 'No incident X link is available for this cluster.', routePresentation);
        if (idx === 1) return note(meta.route_mode === 'browser'
          ? `This bundle has a compact routing graph (privacy: ${meta.routing_graph_privacy || 'not recorded'}).`
          : meta.route_mode === 'precomputed'
            ? 'This bundle declares precomputed route geometries from the GeoPackage paths layer.'
            : 'Route mode is not recorded in this bundle; consult the workspace run metadata for the publication method.',
          'Route publication does not change X weights or scores');
        return note(routePresentation, 'Select a link in Explorer to request its route');
      }
      if (section === 'roads') {
        if (idx === 0) return note(`${c('roads')} road features appear in this bundle (${meta.has_roads ? 'road layer included' : 'road layer omitted'}); distances use ${meta.distance_unit || 'unspecified units'}. The exact center-to-center X distances are published; ${routePresentation}`, 'Visual road feature count, not graph-vertex count');
        if (idx === 1) return note('Road junction identities and overpass connectivity are intermediate graph data and are not exposed in Explorer. The network diagram uses published results.', 'Method illustration only');
        if (idx === 2) return note(`The currently selected cluster's published road-center distances are visible on individual X links. Establishment snap offsets are not in this browser bundle.`, 'Do not equate cluster-to-cluster distances with individual place snap distances');
        return note(example ? `An actual X link connected to this cluster has published road distance ${fmt(example.distance, 1)} ${meta.distance_unit || ''}. The illustration above is not that route.` : 'No adjacent X link is available for a real road-distance example.', `The Explorer map uses center-to-center shortest paths. ${routePresentation}`);
      }
      if (section === 'clusters') {
        if (idx === 0) return note(`${here} contains ${number(clusterCount)} published clusters representing ${number(s?.points)} establishments in ${area}. Not all establishments necessarily belong to a cluster.`, 'Actual X-node cluster counts');
        return note(`This run contains ${c('clusters')} X nodes. The plotted core-distance search, minimum spanning tree, ε cuts, stability calculations, and radius trials are worked examples rather than exported intermediate results.`, 'Mathematics shown in this tutorial is illustrative');
      }
      if (section === 'centers') return note(node ? `The published center of ${nodeLabel(node)} is at latitude ${fmt(node.lat, 6)}, longitude ${fmt(node.lon, 6)}, with ${number(node.members)} member establishments.` : 'No published center selected.', 'Center method and fallback diagnostics are not contained in the browser graph');
      if (section === 'voronoi') return note(`${c('partitions')} cluster polygon features are included in the bundle. These are derived area renderings; view the selected network partitions in Explorer.`, 'A partition need not contain establishments everywhere in its area');
      if (section === 'economy') {
        if (idx === 0) return note(`Current economic specification: ${economyName}, with ${number(meta.sectors.length)} types visible in this area.${rollupRunNote} Explorer publishes derived X links, not the full national transactions matrix Z.`, 'Do not infer transaction amounts from coefficients');
        if (idx === 1) return note(example ? `For a published local X link, the input–output coefficient a is ${frac(example.coefficient)} from ${sectorLabel(nodeMap.get(idStr(example.from))?.type)} to ${sectorLabel(nodeMap.get(idStr(example.to))?.type)}.` : `No local X edge is available to illustrate coefficients.`, 'Observed in model output; not evidence of direct firm-to-firm trade');
        return note(`The economic specification is ${economyName}. Explorer does not publish the full coefficient matrix or distinguish optional preprocessing parameters here.`, 'Consult the source economic artifacts for the full table');
      }
      if (section === 'xgraph') {
        if (idx === 0) return note(`${c('clusters')} X nodes and ${c('edges')} directed X links (or ${c('linked_pairs')} linked node pairs) appear in ${area}.`, 'Sector coupling is a model, not confirmed commercial trade');
        if (idx === 1) return note(example ? `Published link: ${sectorLabel(nodeMap.get(idStr(example.from))?.type)} → ${sectorLabel(nodeMap.get(idStr(example.to))?.type)}; a = ${frac(example.coefficient)}, road distance = ${fmt(example.distance, 2)} ${meta.distance_unit || ''}, X weight = ${frac(example.weight)}.` : 'No incident X link for this cluster.', 'Displayed road distance is the actual center-to-center route. When effective_road_distance is present, the X weight uses center road distance plus both mean member-to-median road radii, capped below at 1 metre, then multiplies by the source and target cluster shares among clustered establishments of their respective economic types. This is not a trade probability');
        return note(node ? `In this run, ${nodeLabel(node)} has published centrality ${fmt(node.centrality, 6)} and degrees ${number(node.in_degree)} in / ${number(node.out_degree)} out.` : 'No cluster is selected.', 'The worked example on the left is invented');
      }
      // sigma-under-the-hood-gravity-tile-area-20261109-v1
      const tile = meta.tile_area || null;
      const hasGamma = tile && typeof tile.gamma === 'number';
      const tileKm2 = node && Number.isFinite(node.area_km2) ? node.area_km2 : null;
      const factor = node && Number.isFinite(node.area_factor) ? node.area_factor : null;
      const notPublished = 'This bundle does not publish the stage 15 regression (an older export, the correction switched off, or an exact no-op such as equal tile areas).';
      if (section === 'gravity') {
        if (idx === 0) {
          const lambda = tile && Number.isFinite(tile.x_distance_decay_lambda) ? tile.x_distance_decay_lambda : null;
          return note(example ? `Published link: ${sectorLabel(nodeMap.get(idStr(example.from))?.type)} → ${sectorLabel(nodeMap.get(idStr(example.to))?.type)}; a = ${frac(example.coefficient)}, center road distance ${fmt(example.distance, 1)} ${meta.distance_unit || ''}${Number.isFinite(example.effective_distance) ? `, effective weight distance ${fmt(example.effective_distance, 1)} ${meta.distance_unit || ''}` : ''}, X weight ${frac(example.weight)}.` : 'No incident X link for this cluster.',
            lambda == null ? 'The X distance exponent of this run is not recorded in the bundle' : `X distance exponent in this run: ${fmt(lambda, 2)}${lambda === 1 ? ' (canonical)' : ''}`);
        }
        const group = bySector.get(idStr(node?.type)) || [];
        const total = group.reduce((sum, n) => sum + (Number.isFinite(n.members) ? n.members : 0), 0);
        return note(node && total ? `${nodeLabel(node)} has ${number(node.members)} of the ${number(total)} clustered establishments of its sector in this bundle, so q = ${frac(node.members / total)}.${tileKm2 != null ? ` Its final tile is ${fmt(tileKm2, 3)} km²; that area is not a term of the X weight.` : ''}` : 'No published cluster membership is available for this cluster.',
          'q is computed from published cluster memberships; the X weight itself was computed in the pipeline');
      }
      if (section === 'area') {
        if (idx === 0) return note(node ? `${nodeLabel(node)}: ${number(node.in_degree)} incoming and ${number(node.out_degree)} outgoing published X links${tileKm2 != null ? `, final tile ${fmt(tileKm2, 3)} km²` : ''}.` : 'No cluster is selected.', 'Candidate overlaps that failed the coefficient or road test are not in the bundle');
        if (idx === 1) {
          if (!hasGamma) return note(notPublished, tile && tile.regression_status ? `Regression status: ${tile.regression_status}` : 'No exponent is borrowed from another area');
          const ci = Array.isArray(tile.ci95) && tile.ci95.every(Number.isFinite) ? ` (95% interval ${fmt(tile.ci95[0], 3)} to ${fmt(tile.ci95[1], 3)})` : '';
          const zeros = tile.degree_balance && Number.isFinite(tile.degree_balance.zero_degree_nodes) ? ` ${number(tile.degree_balance.zero_degree_nodes)} nodes have degree 0.` : '';
          return note(`This run's PPML: γ̂ = ${fmt(tile.gamma, 4)}${ci} from ${number(tile.nodes)} tiles. Doubling a tile's area multiplies its expected total degree by ${fmt(Math.pow(2, tile.gamma), 3)}.${zeros}`, 'HC1 interval; spatially dependent tiles can make it too narrow');
        }
        if (idx === 2) {
          const range = tile && Array.isArray(tile.factor_min_max) ? ` Factors in this run range from ${fmt(tile.factor_min_max[0], 3)} to ${fmt(tile.factor_min_max[1], 3)}${Number.isFinite(tile.factor_max_min_ratio) ? ` (ratio ${fmt(tile.factor_max_min_ratio, 1)})` : ''}.` : '';
          const quantiles = tile && Array.isArray(tile.factor_quantiles_p01_p50_p99) && tile.factor_quantiles_p01_p50_p99.every(Number.isFinite)
            ? ` Factors at p01 / median / p99: ${tile.factor_quantiles_p01_p50_p99.map(v => fmt(v, 3)).join(' / ')}.` : '';
          return note(factor != null ? `${nodeLabel(node)}: A = ${fmt(tileKm2, 3)} km², f = ${fmt(factor, 4)}.${range}${quantiles}` : `${notPublished}${range}${quantiles}`, 'Factors are relative; a common change of unit cancels in Katz');
        }
        return note(factor != null ? `In this run, ${nodeLabel(node)}'s ${number(node.out_degree)} outgoing weights are multiplied by f = ${fmt(factor, 4)} in FW, and its ${number(node.in_degree)} incoming weights by the same f in FWᵀ.` : notPublished, 'sigma_X_edges.csv keeps the original, unadjusted weights W');
      }
      if (section === 'katz') {
        if (idx === 0) return note(node ? `In this run, ${nodeLabel(node)} has published centrality ${fmt(node.centrality, 6)} and degrees ${number(node.in_degree)} in / ${number(node.out_degree)} out.` : 'No cluster is selected.', 'The walk in the figure is invented');
        const raw = node && Number.isFinite(node.katz_in_raw) && Number.isFinite(node.katz_out_raw);
        if (idx === 1) return note(raw ? `${nodeLabel(node)}: Kin = ${fmt(node.katz_in_raw, 4)}, Kout = ${fmt(node.katz_out_raw, 4)}, computed on the adjusted operators${factor != null ? ` (its own f = ${fmt(factor, 4)})` : ''}.` : 'Raw incoming and outgoing Katz values are not published in this bundle.', (tile && Number.isFinite(tile.shared_alpha) ? `This run's shared α = ${tile.shared_alpha.toExponential(4)} (${tile.spectral_scale_method || 'scale method not recorded'}).` : 'Shared α is not published for this run'));
        if (idx === 2) {
          const all = nodes.every(n => Number.isFinite(n.katz_in_raw) && Number.isFinite(n.katz_out_raw));
          if (!raw || !all) return note('The raw components needed to repeat the geometric mean are not published in this bundle.', 'Published combined centrality only');
          const norm = Math.sqrt(nodes.reduce((sum, n) => sum + n.katz_in_raw * n.katz_out_raw, 0));
          const g = Math.sqrt(node.katz_in_raw * node.katz_out_raw);
          return note(`${nodeLabel(node)}: g = √(${fmt(node.katz_in_raw, 3)} × ${fmt(node.katz_out_raw, 3)}) = ${fmt(g, 4)}; g / ‖g‖₂ = ${fmt(g / norm, 6)} (published C = ${fmt(node.centrality, 6)}).`, 'Recomputed in the browser from the published raw components of every node');
        }
        if (!tile || !Array.isArray(tile.area_deciles) || !tile.area_deciles.length) return note(notPublished, 'Use the Metro Manila figures only as an example');
        const d = tile.area_deciles, u = tile.unadjusted || {};
        const rho = v => Number.isFinite(v) ? fmt(v, 3) : 'not available';
        return note(`This run: smallest-area decile ${fmt(d[0].relative_mean_adjusted_degree, 2)} × and largest ${fmt(d[d.length - 1].relative_mean_adjusted_degree, 2)} × the mean of f·k. Area–Katz Spearman ${rho(u.area_katz_spearman_rho)} without the correction, ${rho(tile.area_katz_spearman_rho)} with it. Choose "this run" in the figure.`, 'Diagnostics describe this run only; they are not economic validation');
      }
      if (section === 'score') {
        if (idx === 0) return note(`Published establishment-score range in ${area}: ${fmt(meta.score_range?.[0], 6)} to ${fmt(meta.score_range?.[1], 6)}.`, meta.profile === 'public' ? 'Individual establishment records are omitted from this bundle' : 'Inspect an individual published establishment score by selecting its point in Explorer');
        return note(node ? `For ${nodeLabel(node)}, the published cluster centrality is ${fmt(node.centrality, 6)}. The tutorial’s point-level worked example is illustrative.` : 'Choose an X cluster above to inspect its published centrality.', 'No artificial establishment score is derived from the cluster center');
      }
      return note(`This is a ${meta.profile || 'unknown'} profile for ${area}, using ${economyName}. Top sectors by place count: ${topSectors || 'none published'}.`, 'The dataset is a snapshot of previously computed SIGMA outputs, not a live economic feed');
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
    // sigma-current-run-resilience-20261103-v2: do not destroy a valid
    // metadata summary just because a graph-dependent panel failed later.
    const summaryReady = $('live-stats') && $('live-stats').children.length > 0;
    const message = String(error && (error.message || error));
    $('live-status').textContent = summaryReady
      ? `Published run summary available · detail error: ${message}`
      : `Published run could not be loaded: ${message}`;
    if (!summaryReady) $('live-title').textContent = 'Tutorial examples only';
    $('live-focus').textContent = summaryReady
      ? `The statistics above are from the published run. Cluster details failed: ${message}`
      : `The current run could not be loaded: ${message}. The worked illustrations below remain available.`;
    $('live-sector').disabled = true;
    $('live-node').disabled = true;
    $('live-open-cluster').hidden = true;
    console.error('SIGMA guided tour', error);
  });
})();
// sigma-explorer-tutorial-polish-20261027-v2
