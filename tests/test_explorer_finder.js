// SIGMA Explorer establishment finder: real name ranking, optional sector,
// stable tile offset, browser integration and local/public privacy contracts.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.join(__dirname, '..');
const read = p => fs.readFileSync(path.join(root, p), 'utf8');
const finder = require('../src/sigma/web/static/establishment-finder.js');
const grouped = new Map([
  ['55', [['Cocólife', '1/2', 0, 18], ['Cocolife', '1/2', 1, 19], ['Sari-Sari Cocolife', '1/3', 2, 5]]],
  ['66', [['Cocolife', '8/9', 5, 8], ['Bank', '8/9', 0, 1]]],
]);
assert.equal(finder.normalize('  Cocólife  '), 'cocolife');
let r = finder.search(grouped, 'cocolife');
assert.equal(r.total, 4);
assert.deepEqual(r.matches.map(m => m.sector), ['55', '66', '55', '55']);
assert.deepEqual(r.matches.slice(0, 3).map(m => m.offset).sort((a,b) => a-b), [0, 1, 5]);
assert.equal(r.matches[3].offset, 2);
assert.equal(finder.search(new Map([['66', grouped.get('66')]]), 'cocolife').total, 1);
assert.equal(finder.search(grouped, 'co').matches.length, 4);
assert.equal(finder.search(grouped, 'c').total, 0);
assert.equal(finder.search(grouped, 'zzz').total, 0);
assert.equal(finder.search(grouped, 'coco', 2).matches.length, 2);
const app = read('src/sigma/web/static/app.js');
const html = read('src/sigma/web/static/index.html');
const builder = read('src/sigma/web/builder.py');
const css = read('src/sigma/web/static/style.css');
const workflow = read('.github/workflows/explorer_js.yml');
assert.match(html, /id="finder-query"/);
assert.match(html, /id="finder-sector"/);
assert.match(html, /id="finder-results"/);
assert.match(html, /establishment-finder\.js/);
assert.match(app, /function initializeFinder\(\)/);
assert.match(app, /async function loadFinderRows\(codes\)/);
assert.match(app, /async function pickFinderResult\(hit\)/);
assert.match(app, /const point = \{\.\.\.feature\.properties, coordinates\}/);
assert.match(app, /map\.easeTo\(\{center: coordinates, zoom:/);
assert.match(app, /if \(!meta\.has_establishment_finder \|\| !meta\.has_points\)/);
assert.match(builder, /if profile == "local":\s*index:/);
assert.match(builder, /"has_establishment_finder": profile == "local"/);
assert.match(css, /sigma-establishment-finder-v1/);
assert.match(workflow, /node tests\/test_explorer_finder\.js/);
console.log('PASS: finder ranking, sector filter, click-to-point, privacy and CI contracts.');
