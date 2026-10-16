// Regression: rendered control defaults must match network state; no OSM raster UI.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'src/sigma/web/static/index.html'), 'utf8');
const js = fs.readFileSync(path.join(root, 'src/sigma/web/static/app.js'), 'utf8');

function selectedOption(id) {
  const match = html.match(new RegExp(`<select\\s+id="${id}"[^>]*>([\\s\\S]*?)<\\/select>`));
  assert(match, `Missing ${id} select`);
  const options = [...match[1].matchAll(/<option\s+([^>]*)>([^<]*)<\/option>/g)];
  const marked = options.filter(([, attributes]) => /\bselected\b/.test(attributes));
  assert.equal(marked.length, 1, `${id} must have exactly one explicitly selected option`);
  const value = marked[0][1].match(/\bvalue="([^"]+)"/);
  assert(value, `${id} selected option has no value`);
  return value[1];
}

assert.equal(selectedOption('depth'), '1', 'Direct links is the default depth');
assert.equal(selectedOption('top'), '5', 'Five per cluster is the default link cap');
const state = js.match(/const state\s*=\s*\{[^}]*depth:\s*'([^']+)'\s*,\s*top:\s*'([^']+)'/);
assert(state, 'Explorer startup state missing');
assert.equal(state[1], selectedOption('depth'), 'Depth state and HTML select must agree');
assert.equal(state[2], selectedOption('top'), 'Link cap state and HTML select must agree');
assert(!html.includes('show-basemap'), 'The broken basemap checkbox must be removed');
assert(!js.includes('show-basemap'), 'Basemap event handling must be removed');
assert(!js.includes("map.addSource('osm'"), 'No third-party raster basemap source');
assert(!js.includes("id: 'basemap'"), 'No unused raster basemap layer');
assert(!js.includes('tile.openstreetmap.org'), 'No tile request to external server');
assert(js.includes("id: 'roads-line'"), 'SIGMA road background must remain');
assert(js.includes("id: 'routes-in'"), 'Incoming network paths must remain');
assert(js.includes("id: 'routes'"), 'Outgoing network paths must remain');
console.log('PASS: Direct links + 5 per cluster default, no OSM raster UI, SIGMA roads/routes preserved.');
