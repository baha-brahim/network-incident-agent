# ruff: noqa: E501, RUF001
"""The grading page: one self-contained HTML document (inline CSS and script, no requests).

`human.py` fills the two placeholders: the title and the JSON data. The data holds the reports,
their items, the rubric and the glossary; it never holds a grader verdict or the planted truth.

The reading aids (plain-English box headers, highlighting of shared IDs, times and numbers,
folding of lines, glossary tooltips) are computed here from the embedded text. They only label,
colour and fold the text the grader model read; every line stays available behind "show all".
"""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>__TITLE__</title>
<style>
:root {
  color-scheme: light dark;
  --bg: #f4f5f7; --panel: #ffffff; --text: #1a1e24; --muted: #5a6573; --border: #d3d9e0;
  --accent: #2354cf; --accent-text: #ffffff; --code: #eceff3; --focus: #2354cf;
  --ok: #17703e; --ok-bg: #ddf2e5; --part: #8f5200; --part-bg: #fcebc6;
  --bad: #a8261c; --bad-bg: #fad9d5; --nv: #424b57; --nv-bg: #e2e5ea;
  --warn-bg: #fff4d6;
  --hl-id: #bcd5ff; --hl-num: #ffd978; --miss: #c2410c; --gl: #6b7684;
  --claim-bar: #2354cf;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0e1217; --panel: #171c23; --text: #e7eaef; --muted: #9ba6b3; --border: #2c343e;
    --accent: #7ba3ff; --accent-text: #0b1220; --code: #0f1419; --focus: #7ba3ff;
    --ok: #62d78e; --ok-bg: #12301f; --part: #f2b950; --part-bg: #3a2b0b;
    --bad: #ff8d83; --bad-bg: #3e1814; --nv: #b2bcc8; --nv-bg: #242b34;
    --warn-bg: #3a2f0e;
    --hl-id: #2c4f94; --hl-num: #6b5310; --miss: #ff9a62; --gl: #8e9aa8;
    --claim-bar: #7ba3ff;
  }
}
* { box-sizing: border-box; }
html { scroll-padding-top: calc(var(--top-h, 9rem) + .5rem); }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
button, input, textarea { font: inherit; color: inherit; }
button { cursor: pointer; }
:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
code, pre, kbd { font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; }

.top {
  position: sticky; top: 0; z-index: 5; background: var(--panel);
  border-bottom: 1px solid var(--border); padding: .6rem 1rem .7rem;
}
.top-row { display: flex; gap: .75rem; align-items: center; flex-wrap: wrap; max-width: 1200px; margin: 0 auto; }
.top-row + .top-row { margin-top: .5rem; }
.title { font-weight: 650; }
.counts { color: var(--muted); font-size: .95rem; }
.grow { flex: 1 1 auto; }
.bar { flex: 1 1 12rem; height: .6rem; border-radius: 99px; background: var(--code); overflow: hidden; border: 1px solid var(--border); }
.bar > span { display: block; height: 100%; background: var(--accent); width: 0; transition: width .15s; }
.dots { display: flex; gap: .25rem; flex-wrap: wrap; }
.dot {
  min-width: 1.7rem; height: 1.7rem; padding: 0 .3rem; border-radius: .4rem; font-size: .8rem;
  border: 1px solid var(--border); background: var(--panel); color: var(--muted);
}
.dot.done { background: var(--ok-bg); color: var(--ok); border-color: var(--ok); }
.dot.some { background: var(--part-bg); color: var(--part); border-color: var(--part); }
.dot.here { outline: 2px solid var(--accent); outline-offset: 1px; font-weight: 700; }
.btn {
  border: 1px solid var(--border); background: var(--panel); border-radius: .5rem;
  padding: .35rem .8rem; min-height: 2.2rem;
}
.btn:hover { border-color: var(--accent); }
.btn.primary { background: var(--accent); color: var(--accent-text); border-color: var(--accent); font-weight: 600; }
input.name { border: 1px solid var(--border); background: var(--bg); border-radius: .5rem; padding: .3rem .6rem; width: 11rem; min-height: 2.2rem; }
.saved { color: var(--muted); font-size: .85rem; }
.saved.warn { color: var(--bad); }

main { max-width: 1200px; margin: 0 auto; padding: 1rem; }
.panel { background: var(--panel); border: 1px solid var(--border); border-radius: .75rem; padding: 1rem 1.1rem; margin-bottom: 1rem; }
details.help > summary, details.gloss > summary { cursor: pointer; font-weight: 650; }
.help-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .8rem; margin: .8rem 0; }
@media (max-width: 900px) { .help-grid { grid-template-columns: minmax(0, 1fr); } }
.step { border: 1px solid var(--border); border-radius: .6rem; padding: .6rem .8rem; background: var(--bg); }
.step h3 { margin: 0 0 .2rem; font-size: 1rem; }
.step p { margin: 0; color: var(--muted); }
.step.card { border-left: 5px solid var(--claim-bar); background: var(--panel); }
.step.boxes { background: var(--code); }
.step.q { border-color: var(--accent); }
.help p.lead { margin: .2rem 0 .4rem; }
.example { border: 1px dashed var(--border); border-radius: .6rem; padding: .7rem .8rem; margin: .8rem 0; }
.example h3 { margin: 0 0 .5rem; font-size: 1rem; }
.example .item-grid { margin-bottom: .6rem; }
.example ul { margin: .3rem 0 0; padding-left: 1.2rem; }
.rubric { margin: .75rem 0 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .6rem 1.2rem; }
@media (max-width: 900px) { .rubric { grid-template-columns: minmax(0, 1fr); } }
.rubric dt { font-weight: 650; }
.rubric dd { margin: .1rem 0 0; color: var(--muted); }
.rubric dd.plain { color: var(--text); font-style: italic; }
details.sub { margin-top: .8rem; }
details.sub > summary { cursor: pointer; color: var(--muted); }
.rules { margin: .5rem 0 0; padding-left: 1.2rem; color: var(--muted); }
.keys { margin-top: .8rem; color: var(--muted); font-size: .92rem; }
kbd { border: 1px solid var(--border); border-bottom-width: 2px; border-radius: .3rem; padding: 0 .35rem; background: var(--code); font-size: .85em; }

.gloss-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(21rem, 1fr)); gap: .25rem 1.2rem; margin: .6rem 0 0; font-size: .9rem; }
.gloss-grid .g { padding: .15rem 0; }
.gloss-grid .g b { font-family: ui-monospace, Consolas, monospace; font-size: .85rem; }
.gloss-grid .g.here b::before { content: "\2022 "; color: var(--accent); }
.gloss-grid .grp { grid-column: 1 / -1; margin-top: .5rem; text-transform: uppercase; letter-spacing: .05em; font-size: .72rem; color: var(--muted); font-weight: 650; }
.gloss-note { color: var(--muted); font-size: .88rem; margin: .4rem 0 0; }

.question { font-size: 1.05rem; }
.label { text-transform: uppercase; letter-spacing: .05em; font-size: .72rem; color: var(--muted); font-weight: 650; }
.report h1 { font-size: 1.25rem; margin: .15rem 0 .5rem; }
.chips { display: flex; gap: .4rem; flex-wrap: wrap; margin-bottom: .6rem; }
.chip { border: 1px solid var(--border); background: var(--code); border-radius: 99px; padding: .05rem .7rem; font-size: .88rem; }
.summary { margin: 0; }

.item { background: var(--panel); border: 2px solid var(--border); border-radius: .75rem; padding: 1rem 1.1rem; margin-bottom: 1rem; }
.item.current { border-color: var(--accent); }
.item.graded { border-left-width: 8px; }
.item.v-supported.graded { border-left-color: var(--ok); }
.item.v-partially_supported.graded { border-left-color: var(--part); }
.item.v-unsupported.graded { border-left-color: var(--bad); }
.item.v-not_verifiable.graded { border-left-color: var(--nv); }
.item-grid { display: grid; grid-template-columns: minmax(0, 5fr) minmax(0, 6fr); gap: 1.1rem; align-items: start; }
@media (max-width: 900px) { .item-grid { grid-template-columns: minmax(0, 1fr); } }
.claim-col { position: sticky; top: calc(var(--top-h, 9rem) + .6rem); max-height: calc(100vh - var(--top-h, 9rem) - 1.2rem); overflow: auto; padding: 2px; }
@media (max-width: 900px) { .claim-col { position: static; max-height: none; overflow: visible; } }
.item-head { display: flex; gap: .5rem; align-items: baseline; flex-wrap: wrap; margin-bottom: .35rem; }
.tag { font-weight: 700; font-size: 1.05rem; }
.tag-sub { color: var(--muted); font-size: .88rem; }
.basis { font-size: .8rem; border-radius: .3rem; padding: 0 .45rem; background: var(--code); border: 1px solid var(--border); color: var(--muted); }
.claim-card { border: 1px solid var(--border); border-left: 6px solid var(--claim-bar); border-radius: .6rem; padding: .6rem .9rem .8rem; margin-bottom: .8rem; background: var(--panel); box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.claim { font-size: 1.15rem; margin: .15rem 0 0; line-height: 1.5; }
.choices { display: grid; grid-template-columns: 1fr 1fr; gap: .5rem; }
@media (max-width: 420px) { .choices { grid-template-columns: 1fr; } }
.choice {
  display: flex; align-items: center; gap: .6rem; text-align: left; min-height: 4rem;
  border: 2px solid var(--border); background: var(--panel); border-radius: .6rem; padding: .45rem .75rem; font-size: 1.05rem;
}
.choice kbd { font-size: 1rem; }
.choice small { display: block; font-size: .78rem; font-weight: 400; color: var(--muted); line-height: 1.25; }
.choice:hover { border-color: var(--accent); }
.choice.on { font-weight: 700; }
.choice.on::after { content: "\2713"; margin-left: auto; }
.choice[data-v="supported"].on { background: var(--ok-bg); border-color: var(--ok); color: var(--ok); }
.choice[data-v="partially_supported"].on { background: var(--part-bg); border-color: var(--part); color: var(--part); }
.choice[data-v="unsupported"].on { background: var(--bad-bg); border-color: var(--bad); color: var(--bad); }
.choice[data-v="not_verifiable"].on { background: var(--nv-bg); border-color: var(--nv); color: var(--nv); }
.choice.on small { color: inherit; }
details.comment { margin-top: .7rem; }
details.comment > summary { cursor: pointer; color: var(--muted); }
textarea { width: 100%; min-height: 4rem; margin-top: .4rem; border: 1px solid var(--border); background: var(--bg); border-radius: .5rem; padding: .5rem; resize: vertical; }

.evidence { display: grid; gap: .7rem; align-content: start; }
.ev-legend { font-size: .82rem; color: var(--muted); display: flex; gap: .4rem .9rem; flex-wrap: wrap; align-items: center; }
.hl-id { background: var(--hl-id); border-radius: .2rem; white-space: nowrap; }
.hl-num { background: var(--hl-num); border-radius: .2rem; white-space: nowrap; }
.miss { text-decoration: underline dotted 2px var(--miss); text-underline-offset: 3px; cursor: help; }
.gl { text-decoration: underline dotted 1px var(--gl); text-underline-offset: 3px; cursor: help; }
.miss.gl { text-decoration-color: var(--miss); text-decoration-thickness: 2px; }
.evbox { background: var(--code); border: 1px solid var(--border); border-radius: .5rem; padding: .55rem .7rem .6rem; }
.ev-top { display: flex; gap: .45rem; align-items: center; flex-wrap: wrap; font-size: .8rem; color: var(--muted); }
.ev-ref { font-family: ui-monospace, Consolas, monospace; font-weight: 700; color: var(--text); background: var(--panel); border: 1px solid var(--border); border-radius: .3rem; padding: 0 .35rem; }
.ev-title { font-weight: 650; margin: .15rem 0 .1rem; }
.ev-raw { font-family: ui-monospace, Consolas, monospace; font-size: .72rem; color: var(--muted); overflow-wrap: anywhere; margin-bottom: .35rem; }
.badge { border-radius: .3rem; padding: 0 .4rem; font-size: .75rem; background: var(--warn-bg); border: 1px solid var(--part); color: var(--part); }
.matches { margin-left: auto; }
.ev-body { font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; font-size: .82rem; line-height: 1.45; border-top: 1px solid var(--border); padding-top: .35rem; }
.ln { white-space: pre-wrap; overflow-wrap: anywhere; padding: 0 .1rem; }
.ln.rel { border-left: 3px solid var(--accent); padding-left: .35rem; margin-left: -.4rem; }
.gap { display: block; width: 100%; text-align: left; background: none; border: 0; color: var(--muted); padding: .1rem 0; font-size: .78rem; font-family: inherit; }
.gap:hover { color: var(--accent); }
.more { margin-top: .35rem; background: none; border: 0; padding: 0; color: var(--accent); font-size: .84rem; text-decoration: underline; }
.none { color: var(--muted); font-style: italic; }
.nav { display: flex; gap: .6rem; align-items: center; margin: 1.2rem 0 3rem; flex-wrap: wrap; }
.msg { margin: .5rem 0 0; padding: .5rem .8rem; border-radius: .5rem; background: var(--warn-bg); border: 1px solid var(--border); }
.msg[hidden] { display: none; }
</style>
</head>
<body>
<header class="top" id="top">
  <div class="top-row">
    <span class="title" id="title"></span>
    <span class="counts" id="counts"></span>
    <div class="bar" aria-hidden="true"><span id="bar"></span></div>
    <span class="saved" id="saved"></span>
  </div>
  <div class="top-row">
    <div class="dots" id="dots" role="navigation" aria-label="Reports"></div>
    <span class="grow"></span>
    <label class="counts" for="rater">Your name</label>
    <input class="name" id="rater" autocomplete="off" placeholder="for the export">
    <button class="btn" id="help-btn" type="button" title="Show or hide how this works (?)">How this works</button>
    <button class="btn" id="gloss-btn" type="button" title="Show or hide the glossary (G)">Glossary</button>
    <button class="btn" id="import-btn" type="button">Import</button>
    <button class="btn primary" id="export-btn" type="button">Export</button>
    <input id="import-file" type="file" accept=".json,application/json" hidden>
  </div>
  <div class="top-row"><div class="msg" id="msg" hidden role="status"></div></div>
</header>
<main id="main"></main>
<script type="application/json" id="pack-data">__DATA__</script>
<script>
(function () {
  'use strict';
  var DATA = JSON.parse(document.getElementById('pack-data').textContent);
  var VERDICTS = DATA.rubric.verdicts;
  var GLOSSARY = DATA.glossary || [];
  var STORE_PREFIX = 'incident-grading:';
  var STORE_KEY = STORE_PREFIX + DATA.pack_id;
  var state = { rater: '', grades: {}, notes: {}, r: 0, i: 0, helpSeen: false };
  var storageOk = true;
  var unfolded = {};      // evidence boxes shown in full, by item and reference (kept while the page is open)
  var glossOpen = false;

  // --- saved session -------------------------------------------------------------------------

  function adopt(s, overwrite) {
    if (!s || typeof s !== 'object') return;
    if (s.rater && (overwrite || !state.rater)) state.rater = s.rater;
    Object.keys(s.grades || {}).forEach(function (k) {
      var g = s.grades[k], cur = state.grades[k];
      if (!g) return;
      if (!cur) { state.grades[k] = { v: g.v || null, c: g.c || '' }; return; }
      if (!cur.v && g.v) cur.v = g.v;
      if (!cur.c && g.c) cur.c = g.c;
    });
    Object.keys(s.notes || {}).forEach(function (k) { if (s.notes[k] && !state.notes[k]) state.notes[k] = s.notes[k]; });
    if (s.helpSeen) state.helpSeen = true;
  }
  function load() {
    try {
      var raw = window.localStorage.getItem(STORE_KEY);
      if (raw) {
        var s = JSON.parse(raw);
        adopt(s, true);
        state.r = Math.min(s.r || 0, DATA.reports.length - 1); state.i = s.i || 0;
        return;
      }
      // First visit of this pack: carry over the grades of a session saved by an earlier page
      // (the key follows the pack content, which changes when the pack or the page is rebuilt).
      for (var n = 0; n < window.localStorage.length; n++) {
        var k = window.localStorage.key(n);
        if (!k || k.indexOf(STORE_PREFIX) !== 0 || k === STORE_KEY) continue;
        try { adopt(JSON.parse(window.localStorage.getItem(k)), false); } catch (e2) { /* unreadable: skip */ }
      }
    } catch (e) { storageOk = false; }
  }
  function save() {
    var el = document.getElementById('saved');
    try {
      window.localStorage.setItem(STORE_KEY, JSON.stringify(state));
      el.textContent = storageOk ? 'Saved in this browser' : '';
      el.className = 'saved';
    } catch (e) {
      storageOk = false;
      el.textContent = 'Autosave is unavailable here: export often';
      el.className = 'saved warn';
    }
  }

  function key(report, item) { return report.case_id + '|' + item.index; }
  function gradeOf(report, item) { return state.grades[key(report, item)] || null; }
  function reportDone(report) {
    return report.items.filter(function (it) { return gradeOf(report, it) && gradeOf(report, it).v; }).length;
  }
  function totals() {
    var done = 0, all = 0;
    DATA.reports.forEach(function (r) { done += reportDone(r); all += r.items.length; });
    return { done: done, all: all };
  }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  // --- reading aids: tokens, highlighting, glossary ---------------------------------------------

  var MONTHS = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };
  // groups: 1-5 ISO date and optional time; 6-7 "21 Sep"; 8-9 time; 10 reference or node ID; 11 alarm type; 12 number with unit; 13 other number; 14-15 "Sep 21"
  var TOKEN_SRC = [
    '\\b(\\d{4})-(\\d{2})-(\\d{2})(?:[ T](\\d{1,2}):(\\d{2})(?::\\d{2})?)?',
    '\\b(\\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\\b',
    '\\b(\\d{1,2}):(\\d{2})(?::\\d{2})?\\b',
    '\\b((?:S|LNK|AGG|CORE|C|ALM|CHG|MW|EVT|ALR|ANM|RB)-[A-Z0-9]+(?:-[A-Z0-9]+)*(?:#\\d+)?)',
    '\\b([A-Z]{2,}(?:_[A-Z]+)+)\\b',
    '\\b(\\d{1,3}(?:,\\d{3})+(?:\\.\\d+)?|\\d+(?:\\.\\d+)?)\\s?(?:%|ms|MB|GB|Gbps|Mbps|km|dB|min|h|s|hours?|minutes?|days?|percent|users?|sites?|cells?|alarms?|nodes?|links?|changes?|alerts?)(?![A-Za-z_])',
    '\\b(\\d+\\.\\d+|(?!(?:19|20)\\d\\d\\b)\\d{3,})\\b',
    '\\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* (\\d{1,2})\\b(?!:)'
  ].join('|');
  var ID_TERM = { S: 'S-', C: 'C-', LNK: 'LNK-', AGG: 'AGG-', CORE: 'CORE-', ALM: 'ALM', CHG: 'CHG', MW: 'MW', EVT: 'EVT', ALR: 'ALR', ANM: 'ANM', RB: 'RB' };
  var TERMS = {}, WORDS = [];
  GLOSSARY.forEach(function (g) {
    TERMS[g.term] = g;
    g.match.forEach(function (src) { WORDS.push({ src: src, g: g }); });
  });
  WORDS.sort(function (a, b) { return b.src.length - a.src.length; });
  var WORD_RE_SRC = WORDS.map(function (w) { return '(?:' + w.src + ')'; }).join('|');
  WORDS.forEach(function (w) { w.full = new RegExp('^(?:' + w.src + ')$', 'i'); });

  function pad2(v) { return (v.length < 2 ? '0' : '') + v; }
  function numKey(s) { return 'n:' + String(parseFloat(s.replace(/,/g, ''))); }
  function glossOfWord(text) {
    for (var n = 0; n < WORDS.length; n++) if (WORDS[n].full.test(text)) return WORDS[n].g;
    return null;
  }

  var tokenCache = {};
  function tokensOf(text) {
    if (tokenCache[text]) return tokenCache[text];
    var out = [], m, re = new RegExp(TOKEN_SRC, 'g');
    while ((m = re.exec(text)) !== null) {
      var s = m.index;
      if (m[1]) {
        out.push({ s: s, e: s + 10, t: 'date', key: 'd:' + m[2] + '-' + m[3] });
        if (m[4]) {
          var tail = m[0].length;
          out.push({ s: s + 11, e: s + tail, t: 'time', key: 't:' + pad2(m[4]) + ':' + m[5] });
        }
      } else if (m[6]) {
        out.push({ s: s, e: s + m[0].length, t: 'date', key: 'd:' + pad2(String(MONTHS[m[7].toLowerCase()])) + '-' + pad2(m[6]) });
      } else if (m[8]) {
        out.push({ s: s, e: s + m[0].length, t: 'time', key: 't:' + pad2(m[8]) + ':' + m[9] });
      } else if (m[10]) {
        out.push({ s: s, e: s + m[0].length, t: 'id', key: 'id:' + m[10], gl: TERMS[ID_TERM[m[10].split('-')[0]]] || null });
      } else if (m[11]) {
        out.push({ s: s, e: s + m[0].length, t: 'id', key: 'id:' + m[11], gl: glossOfWord(m[11]) });
      } else if (m[12]) {
        out.push({ s: s, e: s + m[0].length, t: 'num', key: numKey(m[12]) });
      } else if (m[13]) {
        out.push({ s: s, e: s + m[0].length, t: 'num', key: numKey(m[13]) });
      } else if (m[14]) {
        out.push({ s: s, e: s + m[0].length, t: 'date', key: 'd:' + pad2(String(MONTHS[m[14].toLowerCase()])) + '-' + pad2(m[15]) });
      }
    }
    if (WORD_RE_SRC) {
      var wre = new RegExp(WORD_RE_SRC, 'gi'), w;
      while ((w = wre.exec(text)) !== null) {
        if (!w[0]) { wre.lastIndex++; continue; }
        var s2 = w.index, e2 = s2 + w[0].length;
        var clash = out.some(function (t) { return t.s < e2 && s2 < t.e; });
        if (!clash) out.push({ s: s2, e: e2, t: 'gl', key: null, gl: glossOfWord(w[0]) });
      }
    }
    out.sort(function (a, b) { return a.s - b.s; });
    tokenCache[text] = out;
    return out;
  }

  // What is shared between the sentence and the cited text, computed once per item.
  var sharedCache = {};
  function sharedOf(report, item) {
    var k = key(report, item);
    if (sharedCache[k]) return sharedCache[k];
    var claimKeys = {}, evKeys = {};
    tokensOf(item.claim).forEach(function (t) { if (t.key) claimKeys[t.key] = true; });
    item.evidence.forEach(function (ev) {
      tokensOf(ev.text).forEach(function (t) { if (t.key) evKeys[t.key] = true; });
    });
    sharedCache[k] = { claim: claimKeys, ev: evKeys, hasEvidence: item.evidence.length > 0 };
    return sharedCache[k];
  }

  // Write `text` into `parent`, marking tokens. `hl`: keys to highlight; `markMiss`: underline
  // the tokens that are not in `hl` (used on the sentence, where `hl` is the evidence).
  function annotate(parent, text, hl, markMiss) {
    var pos = 0;
    tokensOf(text).forEach(function (t) {
      if (t.s > pos) parent.appendChild(document.createTextNode(text.slice(pos, t.s)));
      pos = t.e;
      var cls = [], tips = [];
      if (t.key) {
        if (hl && hl[t.key]) cls.push(t.t === 'id' ? 'hl-id' : 'hl-num');
        else if (markMiss) { cls.push('miss'); tips.push('Not found in the cited evidence'); }
      }
      if (t.gl) { cls.push('gl'); tips.push(t.gl.term + ': ' + t.gl.text); }
      var chunk = text.slice(t.s, t.e);
      if (!cls.length) { parent.appendChild(document.createTextNode(chunk)); return; }
      var sp = el('span', cls.join(' '), chunk);
      if (tips.length) sp.title = tips.join('\n');
      parent.appendChild(sp);
    });
    if (pos < text.length) parent.appendChild(document.createTextNode(text.slice(pos)));
  }

  function isMatch(t, hl) { return t.key && t.t !== 'date' && hl && hl[t.key]; }
  function matchCount(text, hl) {
    var n = 0;
    tokensOf(text).forEach(function (t) { if (isMatch(t, hl)) n++; });
    return n;
  }

  var ALWAYS = /^(\[\.\.\. shortened|\(repeat of|error:|\(the tool itself|\[this reference|\[text omitted)/;
  var SHORT_BOX = 8;
  // Which lines of a box to show first: the summary line, lines that share a token with the
  // sentence (with their indented detail lines) and the notices about cut or repeated output.
  function pickLines(lines, hl) {
    var show = lines.map(function (ln, n) { return n === 0 || ALWAYS.test(ln.trim()) || tokensOf(ln).some(function (t) { return isMatch(t, hl); }); });
    var base = show.slice();
    base.forEach(function (on, n) {
      if (!on) return;
      for (var j = n + 1; j < lines.length && j <= n + 3 && /^\s/.test(lines[j]) && lines[j].trim(); j++) show[j] = true;
    });
    var count = show.filter(Boolean).length;
    if (lines.length <= SHORT_BOX || count >= lines.length - 1) return null;
    return show;
  }

  // --- rendering ---------------------------------------------------------------------------------

  function renderEvidence(report, item, ev, n, isExample) {
    var shared = isExample ? exampleShared : sharedOf(report, item);
    var hl = shared.claim;
    var box = el('div', 'evbox');
    var top = el('div', 'ev-top');
    top.appendChild(el('span', 'ev-ref', ev.ref));
    if (ev.shortened) top.appendChild(el('span', 'badge', 'shortened'));
    if (!ev.found) top.appendChild(el('span', 'badge', 'not among the report evidence'));
    var all = ev.text.split('\n');
    var raw = null;
    if (ev.type === 'call' && all[0].indexOf(ev.ref + ' ' + ev.tool) === 0) raw = all.shift();
    var hits = matchCount(ev.text, hl);
    var mt = el('span', 'matches', hits ? hits + ' shared with the sentence' : 'nothing shared with the sentence');
    top.appendChild(mt);
    box.appendChild(top);
    var title = el('div', 'ev-title');
    annotate(title, ev.label || ev.ref, hl, false);
    box.appendChild(title);
    if (raw) {
      var rawEl = el('div', 'ev-raw');
      annotate(rawEl, raw, hl, false);
      box.appendChild(rawEl);
    }
    var uk = (isExample ? 'example' : key(report, item)) + '|' + ev.ref;
    var show = pickLines(all, hl);
    var full = !show || unfolded[uk];
    var body = el('div', 'ev-body');
    var run = 0;
    function flushGap() {
      if (!run) return;
      var g = el('button', 'gap', '⋯ ' + run + ' more line' + (run === 1 ? '' : 's') + ' not shown (click to show all)');
      g.type = 'button';
      g.addEventListener('click', function () { unfolded[uk] = true; rerender(); });
      body.appendChild(g);
      run = 0;
    }
    all.forEach(function (ln, k) {
      if (!full && !show[k]) { run++; return; }
      flushGap();
      var rel = tokensOf(ln).some(function (t) { return isMatch(t, hl); });
      var d = el('div', 'ln' + (rel ? ' rel' : ''));
      annotate(d, ln, hl, false);
      body.appendChild(d);
    });
    flushGap();
    box.appendChild(body);
    if (show) {
      var more = el('button', 'more', full ? 'Show only the relevant lines' : 'Show all ' + all.length + ' lines');
      more.type = 'button';
      more.dataset.role = 'fold';
      more.addEventListener('click', function () { unfolded[uk] = !full; rerender(); });
      box.appendChild(more);
    }
    box.dataset.hits = String(hits);
    return box;
  }

  function sortedEvidence(report, item) {
    var hl = sharedOf(report, item).claim;
    return item.evidence.map(function (ev, n) { return { ev: ev, n: n, hits: matchCount(ev.text, hl) }; })
      .sort(function (a, b) { return b.hits - a.hits || a.n - b.n; });
  }

  function renderChoices(report, item, n, g, isExample) {
    var choices = el('div', 'choices');
    choices.setAttribute('role', 'radiogroup');
    VERDICTS.forEach(function (v, k) {
      var b = el('button', 'choice' + (g && g.v === v.key ? ' on' : ''));
      b.type = 'button'; b.dataset.v = v.key;
      b.setAttribute('role', 'radio'); b.setAttribute('aria-checked', g && g.v === v.key ? 'true' : 'false');
      b.appendChild(el('kbd', null, String(k + 1)));
      var txt = el('span');
      txt.appendChild(el('span', null, v.label));
      txt.appendChild(el('small', null, v.plain));
      b.appendChild(txt);
      b.addEventListener('click', function () { state.i = n; setVerdict(v.key); });
      choices.appendChild(b);
    });
    return choices;
  }

  function renderItem(report, item, n) {
    var g = gradeOf(report, item);
    var shared = sharedOf(report, item);
    var sec = el('section', 'item' + (n === state.i ? ' current' : '') + (g && g.v ? ' graded v-' + g.v : ''));
    sec.dataset.n = n;
    var grid = el('div', 'item-grid');
    var left = el('div', 'claim-col');
    var head = el('div', 'item-head');
    var findings = report.items.length - 1;
    if (item.index < 0) {
      head.appendChild(el('span', 'tag', 'Root cause'));
      head.appendChild(el('span', 'tag-sub', 'the agent’s final conclusion'));
    } else {
      head.appendChild(el('span', 'tag', 'Finding ' + (item.index + 1) + ' of ' + findings));
      head.appendChild(el('span', 'tag-sub', 'one fact the agent lists to justify the conclusion'));
      var basis = el('span', 'basis', item.basis);
      basis.title = item.basis === 'observed' ? 'The agent says this is directly visible in the data.' : 'The agent says this is deduced from the data.';
      head.appendChild(basis);
    }
    left.appendChild(head);
    var card = el('div', 'claim-card');
    card.appendChild(el('div', 'label', 'The agent wrote – grade this sentence'));
    var claim = el('p', 'claim');
    annotate(claim, item.claim, shared.hasEvidence ? shared.ev : null, shared.hasEvidence);
    card.appendChild(claim);
    left.appendChild(card);
    left.appendChild(renderChoices(report, item, n, g));
    var det = el('details', 'comment');
    det.open = !!(g && g.c);
    det.appendChild(el('summary', null, 'Comment (optional)'));
    var ta = el('textarea');
    ta.value = (g && g.c) || '';
    ta.setAttribute('aria-label', 'Comment');
    ta.addEventListener('input', function () {
      var cur = state.grades[key(report, item)] || (state.grades[key(report, item)] = { v: null, c: '' });
      cur.c = ta.value; save();
    });
    ta.addEventListener('focus', function () { state.i = n; });
    det.appendChild(ta);
    left.appendChild(det);
    grid.appendChild(left);
    var right = el('div', 'evidence');
    right.appendChild(el('div', 'label', 'Facts from the database – what the agent cited for this sentence'));
    right.appendChild(legend());
    if (item.evidence.length === 0) right.appendChild(el('p', 'none', 'No evidence is cited for this sentence.'));
    sortedEvidence(report, item).forEach(function (o) { right.appendChild(renderEvidence(report, item, o.ev, o.n, false)); });
    grid.appendChild(right);
    sec.appendChild(grid);
    sec.addEventListener('click', function (e) {
      if (state.i !== n && !e.target.closest('button, textarea, summary')) { state.i = n; render(false); }
    });
    return sec;
  }

  function legend() {
    var l = el('div', 'ev-legend');
    l.appendChild(el('span', 'hl-id', 'ID'));
    l.appendChild(el('span', 'hl-num', 'time / number'));
    l.appendChild(document.createTextNode('also in the sentence'));
    l.appendChild(el('span', 'miss', 'dotted'));
    l.appendChild(document.createTextNode('in the sentence: not found in these boxes'));
    l.appendChild(el('span', 'gl', 'underlined'));
    l.appendChild(document.createTextNode('hover for a definition. Most matching box first.'));
    return l;
  }

  // The worked example uses made-up data, rendered by the same code as the real items.
  var EXAMPLE = {
    claim: 'Link LNK-TUN-02-C lost signal at 16:50.',
    ev: {
      ref: 'T1', type: 'call', tool: 'get_alarms', found: true, shortened: false,
      label: 'Alarms on S-TUN-012 and nodes below them, 21 Sep 15:00 to 19:00',
      text: 'T1 get_alarms(start=2026-09-21 15:00, end=2026-09-21 19:00, node_ids=[\'S-TUN-012\'], include_descendants=True)\n' +
        '2 alarm(s) on S-TUN-012 and nodes below, 2026-09-21 15:00 to 2026-09-21 19:00: 2 critical.\n' +
        '2026-09-21 16:50 ALM-000472 critical LINK_LOS LNK-TUN-02-C: cleared 2026-09-22 00:26\n' +
        '2026-09-21 16:51 ALM-000474 critical SITE_DOWN S-TUN-012: cleared 2026-09-22 00:29'
    }
  };
  var exampleShared = { claim: {}, ev: {}, hasEvidence: true };
  tokensOf(EXAMPLE.claim).forEach(function (t) { if (t.key) exampleShared.claim[t.key] = true; });
  tokensOf(EXAMPLE.ev.text).forEach(function (t) { if (t.key) exampleShared.ev[t.key] = true; });

  function renderExample() {
    var box = el('div', 'example');
    box.appendChild(el('h3', null, 'Worked example (made-up data, not in your pack)'));
    var grid = el('div', 'item-grid');
    var card = el('div', 'claim-card');
    card.appendChild(el('div', 'label', 'The agent wrote – grade this sentence'));
    var p = el('p', 'claim');
    annotate(p, EXAMPLE.claim, exampleShared.ev, true);
    card.appendChild(p);
    grid.appendChild(card);
    grid.appendChild(renderEvidence(null, null, EXAMPLE.ev, 0, true));
    box.appendChild(grid);
    var ul = el('ul');
    [['Supported', 'The box shows the loss-of-signal alarm (LINK_LOS) on LNK-TUN-02-C at 16:50. Everything in the sentence is there.'],
     ['Partially supported', 'If the sentence said 17:30, the link and the alarm match but the time is nowhere in the box.'],
     ['Unsupported', 'If the box only listed SITE_DOWN on S-TUN-012 and nothing on that link, it is about something else.']
    ].forEach(function (r) {
      var li = el('li');
      li.appendChild(el('b', null, r[0] + ': '));
      li.appendChild(document.createTextNode(r[1]));
      ul.appendChild(li);
    });
    box.appendChild(ul);
    return box;
  }

  function step(cls, title, text) {
    var s = el('div', 'step ' + cls);
    s.appendChild(el('h3', null, title));
    s.appendChild(el('p', null, text));
    return s;
  }

  function renderHelp() {
    var box = el('details', 'panel help');
    box.id = 'help';
    box.open = !state.helpSeen;
    box.appendChild(el('summary', null, 'How this works (30 seconds)'));
    box.appendChild(el('p', 'lead', 'Each screen is one incident report written by an automated incident agent that investigated a network problem. You do not need to know telecom: you only compare a sentence with the text under it.'));
    var grid = el('div', 'help-grid');
    grid.appendChild(step('card', '1. The white card is the agent’s sentence', 'It was written by the agent. It is a claim, not a fact. This is what you grade.'));
    grid.appendChild(step('boxes', '2. The grey boxes are facts', 'They are answers returned by the database (alarms, measurements, changes). The agent did not write them; it cited them as its proof.'));
    grid.appendChild(step('q', '3. Your one question', 'Do the boxes back the sentence? Not whether it is true in the real world, and use no outside knowledge. Check names, numbers and times literally.'));
    box.appendChild(grid);
    box.appendChild(el('p', null, 'Root cause and findings: the first card of each report is the root cause, the agent’s final conclusion (“what broke”). The cards after it are findings: the individual facts it lists to justify that conclusion. You grade each one the same way. Blue and amber marks show where the sentence and the boxes share an ID, a time or a number. A dotted orange underline in the sentence means that word or number is not in any of its boxes: a reading aid, not a verdict.'));
    box.appendChild(renderExample());
    var dl = el('dl', 'rubric');
    VERDICTS.forEach(function (v, n) {
      var row = el('div');
      row.appendChild(el('dt', null, (n + 1) + '. ' + v.label));
      row.appendChild(el('dd', 'plain', v.plain));
      row.appendChild(el('dd', null, v.definition));
      dl.appendChild(row);
    });
    box.appendChild(dl);
    var sub = el('details', 'sub');
    sub.appendChild(el('summary', null, 'The grader’s rules (the same ones the grader model follows)'));
    var ol = el('ol', 'rules');
    DATA.rubric.rules.forEach(function (t) { ol.appendChild(el('li', null, t)); });
    sub.appendChild(ol);
    box.appendChild(sub);
    var keys = el('div', 'keys');
    keys.innerHTML = '<kbd>1</kbd>-<kbd>4</kbd> verdict &middot; <kbd>0</kbd> clear &middot; ' +
      '<kbd>&uarr;</kbd><kbd>&darr;</kbd> previous / next claim &middot; <kbd>&larr;</kbd><kbd>&rarr;</kbd> previous / next report &middot; ' +
      '<kbd>Space</kbd> next ungraded claim &middot; <kbd>E</kbd> show all / fewer lines &middot; <kbd>C</kbd> comment &middot; <kbd>G</kbd> glossary &middot; <kbd>?</kbd> this panel';
    box.appendChild(keys);
    box.addEventListener('toggle', function () {
      if (!box.open && !state.helpSeen) { state.helpSeen = true; save(); }
    });
    return box;
  }

  function renderGlossary(report) {
    var box = el('details', 'panel gloss');
    box.id = 'glossary';
    box.open = glossOpen;
    box.appendChild(el('summary', null, 'Glossary – what the terms in the boxes mean'));
    var text = [report.question, report.title, report.summary];
    report.items.forEach(function (it) { text.push(it.claim); it.evidence.forEach(function (ev) { text.push(ev.label || '', ev.text); }); });
    var present = {};
    tokensOf(text.join('\n')).forEach(function (t) { if (t.gl) present[t.gl.term] = true; });
    box.appendChild(el('p', 'gloss-note', 'A dot marks the terms that occur in this report. In the text, these terms have a dotted underline: hover for the definition.'));
    var grid = el('div', 'gloss-grid');
    var last = '';
    GLOSSARY.forEach(function (g) {
      if (g.group !== last) { grid.appendChild(el('div', 'grp', g.group)); last = g.group; }
      var row = el('div', 'g' + (present[g.term] ? ' here' : ''));
      row.appendChild(el('b', null, g.term));
      row.appendChild(document.createTextNode(' – ' + g.text));
      grid.appendChild(row);
    });
    box.appendChild(grid);
    box.addEventListener('toggle', function () { glossOpen = box.open; });
    return box;
  }

  function renderTop() {
    document.getElementById('title').textContent = DATA.title;
    var t = totals();
    document.getElementById('counts').textContent = 'Report ' + (state.r + 1) + ' of ' + DATA.reports.length +
      ' · ' + t.done + ' of ' + t.all + ' claims graded';
    document.getElementById('bar').style.width = (t.all ? 100 * t.done / t.all : 0) + '%';
    var dots = document.getElementById('dots');
    dots.textContent = '';
    DATA.reports.forEach(function (r, n) {
      var d = reportDone(r);
      var b = el('button', 'dot' + (d === r.items.length ? ' done' : d ? ' some' : '') + (n === state.r ? ' here' : ''), String(n + 1));
      b.type = 'button';
      b.title = 'Report ' + (n + 1) + ': ' + d + ' of ' + r.items.length + ' graded';
      b.addEventListener('click', function () { goReport(n); });
      dots.appendChild(b);
    });
    document.getElementById('rater').value = state.rater;
  }

  function fitTop() {
    var h = document.getElementById('top').offsetHeight;
    document.documentElement.style.setProperty('--top-h', h + 'px');
  }

  function rerender() {
    var y = window.scrollY;
    render(false);
    window.scrollTo(0, y);
  }

  function render(scroll) {
    renderTop();
    var report = DATA.reports[state.r];
    state.i = Math.max(0, Math.min(state.i, report.items.length - 1));
    var main = document.getElementById('main');
    var helpWasOpen = document.getElementById('help') ? document.getElementById('help').open : !state.helpSeen;
    main.textContent = '';
    var help = renderHelp();
    help.open = helpWasOpen;
    main.appendChild(help);
    main.appendChild(renderGlossary(report));
    var head = el('section', 'panel report');
    head.appendChild(el('div', 'label', 'Question the agent was asked'));
    head.appendChild(el('p', 'question', report.question));
    head.appendChild(el('div', 'label', 'The agent’s report'));
    head.appendChild(el('h1', null, report.title));
    var chips = el('div', 'chips');
    report.chips.forEach(function (c) { chips.appendChild(el('span', 'chip', c)); });
    head.appendChild(chips);
    head.appendChild(el('p', 'summary', report.summary));
    main.appendChild(head);
    report.items.forEach(function (item, n) { main.appendChild(renderItem(report, item, n)); });
    var note = el('section', 'panel');
    note.appendChild(el('div', 'label', 'Notes on this report (optional)'));
    var ta = el('textarea');
    ta.value = state.notes[report.case_id] || '';
    ta.setAttribute('aria-label', 'Notes on this report');
    ta.addEventListener('input', function () { state.notes[report.case_id] = ta.value; save(); });
    note.appendChild(ta);
    main.appendChild(note);
    var nav = el('div', 'nav');
    var prev = el('button', 'btn', '← Previous report'); prev.type = 'button';
    prev.disabled = state.r === 0; prev.addEventListener('click', function () { goReport(state.r - 1); });
    var next = el('button', 'btn primary', state.r === DATA.reports.length - 1 ? 'Last report' : 'Next report →');
    next.type = 'button'; next.disabled = state.r === DATA.reports.length - 1;
    next.addEventListener('click', function () { goReport(state.r + 1); });
    nav.appendChild(prev); nav.appendChild(next);
    main.appendChild(nav);
    save();
    fitTop();
    if (scroll) {
      var cur = main.querySelector('.item.current');
      if (cur) cur.scrollIntoView({ block: 'start', behavior: 'smooth' });
    }
  }

  function goReport(n) {
    if (n < 0 || n >= DATA.reports.length) return;
    state.r = n; state.i = 0; render(false);
    window.scrollTo(0, 0);
  }
  function setVerdict(v) {
    var report = DATA.reports[state.r], item = report.items[state.i];
    var k = key(report, item);
    var cur = state.grades[k] || (state.grades[k] = { v: null, c: '' });
    cur.v = v;
    if (!state.helpSeen) {
      state.helpSeen = true;
      var h = document.getElementById('help');
      if (h) h.open = false;
    }
    var last = state.i === report.items.length - 1;
    if (v && !last) state.i += 1;
    render(true);
  }
  function move(delta) {
    var report = DATA.reports[state.r];
    var n = Math.max(0, Math.min(report.items.length - 1, state.i + delta));
    if (n !== state.i) { state.i = n; render(true); }
  }
  function nextUngraded() {
    var total = DATA.reports.length;
    for (var step = 0; step < total; step++) {
      var r = (state.r + step) % total, report = DATA.reports[r];
      for (var i = 0; i < report.items.length; i++) {
        if (step === 0 && i <= state.i) continue;
        var g = gradeOf(report, report.items[i]);
        if (!g || !g.v) { state.r = r; state.i = i; render(true); return; }
      }
    }
    for (var i2 = 0; i2 < state.i; i2++) {
      var g2 = gradeOf(DATA.reports[state.r], DATA.reports[state.r].items[i2]);
      if (!g2 || !g2.v) { state.i = i2; render(true); return; }
    }
    flash('Every claim has a verdict. Export when you are ready.');
  }
  // E: show every line of the boxes of the current claim, or fold them back.
  function toggleLines() {
    var report = DATA.reports[state.r], item = report.items[state.i];
    var boxes = item.evidence.filter(function (ev) {
      return pickLines(ev.text.split('\n'), sharedOf(report, item).claim) !== null;
    });
    var anyFolded = boxes.some(function (ev) { return !unfolded[key(report, item) + '|' + ev.ref]; });
    boxes.forEach(function (ev) { unfolded[key(report, item) + '|' + ev.ref] = anyFolded; });
    rerender();
  }

  var msgTimer = null;
  function flash(text) {
    var m = document.getElementById('msg');
    m.textContent = text; m.hidden = false;
    fitTop();
    window.clearTimeout(msgTimer);
    msgTimer = window.setTimeout(function () { m.hidden = true; fitTop(); }, 6000);
  }

  function exportGrades() {
    var name = state.rater.trim();
    if (!name) { flash('Enter your name first; it goes into the export.'); document.getElementById('rater').focus(); return; }
    var out = [];
    DATA.reports.forEach(function (r) {
      var findings = [];
      r.items.forEach(function (it) {
        var g = gradeOf(r, it);
        if (g && g.v) findings.push({ index: it.index, verdict: g.v, reason: g.c || '' });
      });
      var note = (state.notes[r.case_id] || '').trim();
      if (findings.length || note) {
        out.push({ case_id: r.case_id, grader: 'human:' + name, findings: findings, comments: note,
                   extra: { complete: findings.length === r.items.length, pack_id: DATA.pack_id } });
      }
    });
    if (!out.length) { flash('Nothing to export yet.'); return; }
    var blob = new Blob([JSON.stringify(out, null, 2) + '\n'], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = 'human_grades.json';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    window.setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    flash('Exported ' + out.length + ' reports to human_grades.json.');
  }

  function importGrades(file) {
    var reader = new FileReader();
    reader.onload = function () {
      try {
        var list = JSON.parse(reader.result);
        if (!Array.isArray(list)) throw new Error('not a list');
        var known = {}, count = 0;
        DATA.reports.forEach(function (r) { known[r.case_id] = r; });
        list.forEach(function (g) {
          var r = known[g.case_id];
          if (!r) return;
          (g.findings || []).forEach(function (f) {
            var ok = VERDICTS.some(function (v) { return v.key === f.verdict; });
            if (!ok) return;
            state.grades[r.case_id + '|' + f.index] = { v: f.verdict, c: f.reason || '' };
            count++;
          });
          if (g.comments) state.notes[r.case_id] = g.comments;
          if (!state.rater && typeof g.grader === 'string' && g.grader.indexOf('human:') === 0) state.rater = g.grader.slice(6);
        });
        render(false);
        flash('Imported ' + count + ' grades.');
      } catch (e) { flash('That file is not a grading export: ' + e.message); }
    };
    reader.readAsText(file);
  }

  document.getElementById('export-btn').addEventListener('click', exportGrades);
  document.getElementById('import-btn').addEventListener('click', function () { document.getElementById('import-file').click(); });
  document.getElementById('import-file').addEventListener('change', function (e) {
    if (e.target.files && e.target.files[0]) importGrades(e.target.files[0]);
    e.target.value = '';
  });
  document.getElementById('help-btn').addEventListener('click', toggleHelp);
  document.getElementById('gloss-btn').addEventListener('click', toggleGlossary);
  document.getElementById('rater').addEventListener('input', function (e) { state.rater = e.target.value; save(); });
  function toggleHelp() {
    var h = document.getElementById('help');
    h.open = !h.open;
    if (!h.open) { state.helpSeen = true; save(); }
    if (h.open) h.scrollIntoView({ block: 'start' });
  }
  function toggleGlossary() {
    var g = document.getElementById('glossary');
    g.open = !g.open;
    glossOpen = g.open;
    if (g.open) g.scrollIntoView({ block: 'start' });
  }
  window.addEventListener('resize', fitTop);

  document.addEventListener('keydown', function (e) {
    var t = e.target;
    if (t && (t.tagName === 'TEXTAREA' || t.tagName === 'INPUT')) {
      if (e.key === 'Escape') t.blur();
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    var k = e.key;
    if (k >= '1' && k <= String(VERDICTS.length)) { setVerdict(VERDICTS[Number(k) - 1].key); }
    else if (k === '0' || k === 'Backspace') { setVerdict(null); }
    else if (k === 'ArrowDown' || k === 'j') { move(1); }
    else if (k === 'ArrowUp' || k === 'k') { move(-1); }
    else if (k === 'ArrowRight') { goReport(state.r + 1); }
    else if (k === 'ArrowLeft') { goReport(state.r - 1); }
    else if (k === ' ' || k === 'Enter') { if (t && t.tagName === 'BUTTON') return; nextUngraded(); }
    else if (k === 'c' || k === 'C') {
      var cur = document.querySelector('.item.current details.comment');
      if (cur) { cur.open = true; cur.querySelector('textarea').focus(); }
    }
    else if (k === 'e' || k === 'E') { toggleLines(); }
    else if (k === 'g' || k === 'G') { toggleGlossary(); }
    else if (k === '?') { toggleHelp(); }
    else { return; }
    e.preventDefault();
  });

  load();
  render(false);
  window.__grading = { state: state, data: DATA };
})();
</script>
</body>
</html>
"""
