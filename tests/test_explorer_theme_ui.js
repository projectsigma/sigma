// SIGMA Explorer v4: one visual tooltip + explicit light/dark switch.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = path.join(__dirname,'../src/sigma/web/static');
const html = fs.readFileSync(path.join(base,'index.html'),'utf8');
const js = fs.readFileSync(path.join(base,'app.js'),'utf8');
const css = fs.readFileSync(path.join(base,'style.css'),'utf8');
assert.match(html, /<html lang="en" data-theme="light">/);
// sigma-action-label-toggle-v1: a button, not the legacy Theme dropdown.
assert.match(html, /id="theme-toggle"[^>]*aria-pressed="false"/);
assert.match(html, /id="theme-toggle"[^>]*>[\s\S]*?<span>Dark mode<\/span><\/button>/);
assert(!html.includes('id="theme-mode"'), 'Legacy theme dropdown must be removed');
assert(html.indexOf('id="theme-toggle"') > html.indexOf('href="DATA_NOTICE.txt"'),
  'Theme button must be the rightmost Explorer header control');
assert.match(js, /\$\('theme-toggle'\)\.addEventListener\('click'/);
assert.match(js, /const nextLabel = dark \? 'Light mode' : 'Dark mode'/);
const tutorial = fs.readFileSync(path.join(base,'tutorial.html'),'utf8');
assert.match(tutorial, /sigma-action-label-toggle-v1/);
assert.match(tutorial, /const nextLabel = dark \? 'Light mode' : 'Dark mode'/);
const icons = [...html.matchAll(/<span\b[^>]*\bclass="control-help[^\"]*"[^>]*>/g)];
assert(icons.length>=8, 'Missing ? help icons');
for (const icon of icons) assert(!/\btitle=/.test(icon[0]), 'Native title tooltip remains on ? help icon');
assert(!js.includes("className: 'control-help', title: description"), 'Dynamic help has native title');
assert.match(js, /function applyTheme\(choice\)/);
assert.match(js, /document\.documentElement\.dataset\.theme = themeMode/);
assert.match(js, /applyTheme\('light'\)/);
assert.match(js, /addLayers\(data\);\s*applyTheme\(themeMode\)/);
assert.match(js, /roads-line', 'line-opacity',[\s\S]*?themeMode === 'dark'/);
assert.match(css, /sigma-explorer-theme-20261019-v4/);
assert.match(css, /html\[data-theme="dark"\] #network/);
assert.match(css, /\.sigma-help-popup \{ background:#22352a/);
console.log('PASS: one help tooltip, light default, map/diagram/dark panel theming.');
