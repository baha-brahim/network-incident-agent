# ruff: noqa: E501
"""The grading page: one self-contained HTML document (inline CSS and script, no requests).

`human.py` fills the two placeholders: the title and the JSON data. The data holds the reports,
their items and the rubric; it never holds a grader verdict or the planted truth.
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
  --accent: #2354cf; --accent-text: #ffffff; --code: #f0f2f5; --focus: #2354cf;
  --ok: #17703e; --ok-bg: #ddf2e5; --part: #8f5200; --part-bg: #fcebc6;
  --bad: #a8261c; --bad-bg: #fad9d5; --nv: #424b57; --nv-bg: #e2e5ea;
  --warn-bg: #fff4d6;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0e1217; --panel: #171c23; --text: #e7eaef; --muted: #9ba6b3; --border: #2c343e;
    --accent: #7ba3ff; --accent-text: #0b1220; --code: #0f1419; --focus: #7ba3ff;
    --ok: #62d78e; --ok-bg: #12301f; --part: #f2b950; --part-bg: #3a2b0b;
    --bad: #ff8d83; --bad-bg: #3e1814; --nv: #b2bcc8; --nv-bg: #242b34;
    --warn-bg: #3a2f0e;
  }
}
* { box-sizing: border-box; }
html { scroll-padding-top: 9.5rem; }
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
details.help > summary { cursor: pointer; font-weight: 650; }
.rubric { margin: .75rem 0 0; display: grid; gap: .6rem; }
.rubric dt { font-weight: 650; }
.rubric dd { margin: .1rem 0 0; color: var(--muted); }
.rules { margin: .8rem 0 0; padding-left: 1.2rem; color: var(--muted); }
.keys { margin-top: .8rem; color: var(--muted); font-size: .92rem; }
kbd { border: 1px solid var(--border); border-bottom-width: 2px; border-radius: .3rem; padding: 0 .35rem; background: var(--code); font-size: .85em; }

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
.item-grid { display: grid; grid-template-columns: minmax(0, 5fr) minmax(0, 6fr); gap: 1.1rem; }
@media (max-width: 900px) { .item-grid { grid-template-columns: minmax(0, 1fr); } }
.item-head { display: flex; gap: .5rem; align-items: center; margin-bottom: .35rem; }
.tag { font-weight: 700; }
.basis { font-size: .8rem; border-radius: .3rem; padding: 0 .45rem; background: var(--code); border: 1px solid var(--border); color: var(--muted); }
.claim { font-size: 1.12rem; margin: .2rem 0 .7rem; }
.cites { color: var(--muted); font-size: .9rem; margin-bottom: .8rem; overflow-wrap: anywhere; }
.cites code { background: var(--code); border-radius: .25rem; padding: 0 .3rem; }
.choices { display: grid; grid-template-columns: 1fr 1fr; gap: .5rem; }
@media (max-width: 420px) { .choices { grid-template-columns: 1fr; } }
.choice {
  display: flex; align-items: center; gap: .55rem; text-align: left; min-height: 3.1rem;
  border: 2px solid var(--border); background: var(--panel); border-radius: .6rem; padding: .4rem .75rem; font-size: 1.02rem;
}
.choice kbd { font-size: .95rem; }
.choice:hover { border-color: var(--accent); }
.choice.on { font-weight: 700; }
.choice.on::after { content: "\2713"; margin-left: auto; }
.choice[data-v="supported"].on { background: var(--ok-bg); border-color: var(--ok); color: var(--ok); }
.choice[data-v="partially_supported"].on { background: var(--part-bg); border-color: var(--part); color: var(--part); }
.choice[data-v="unsupported"].on { background: var(--bad-bg); border-color: var(--bad); color: var(--bad); }
.choice[data-v="not_verifiable"].on { background: var(--nv-bg); border-color: var(--nv); color: var(--nv); }
details.comment { margin-top: .7rem; }
details.comment > summary { cursor: pointer; color: var(--muted); }
textarea { width: 100%; min-height: 4rem; margin-top: .4rem; border: 1px solid var(--border); background: var(--bg); border-radius: .5rem; padding: .5rem; resize: vertical; }

.evidence { display: grid; gap: .6rem; align-content: start; }
.ev-head { display: flex; gap: .5rem; align-items: center; font-size: .85rem; color: var(--muted); margin-bottom: .15rem; }
.ev-head strong { color: var(--text); font-family: ui-monospace, Consolas, monospace; }
.badge { border-radius: .3rem; padding: 0 .4rem; font-size: .75rem; background: var(--warn-bg); border: 1px solid var(--part); color: var(--part); }
pre.ev {
  margin: 0; background: var(--code); border: 1px solid var(--border); border-radius: .5rem; padding: .6rem .7rem;
  font-size: .82rem; line-height: 1.45; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 15rem; overflow: auto;
}
.none { color: var(--muted); font-style: italic; }
.nav { display: flex; gap: .6rem; align-items: center; margin: 1.2rem 0 3rem; flex-wrap: wrap; }
.msg { margin: .5rem 0 0; padding: .5rem .8rem; border-radius: .5rem; background: var(--warn-bg); border: 1px solid var(--border); }
.msg[hidden] { display: none; }
</style>
</head>
<body>
<header class="top">
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
    <button class="btn" id="help-btn" type="button" title="Show or hide the instructions (?)">Instructions</button>
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
  var STORE_KEY = 'incident-grading:' + DATA.pack_id;
  var state = { rater: '', grades: {}, notes: {}, r: 0, i: 0, helpSeen: false };
  var storageOk = true;

  function load() {
    try {
      var raw = window.localStorage.getItem(STORE_KEY);
      if (raw) {
        var s = JSON.parse(raw);
        state.rater = s.rater || ''; state.grades = s.grades || {}; state.notes = s.notes || {};
        state.r = Math.min(s.r || 0, DATA.reports.length - 1); state.i = s.i || 0; state.helpSeen = !!s.helpSeen;
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

  function renderHelp() {
    var box = el('details', 'panel help');
    box.id = 'help';
    box.open = !state.helpSeen;
    box.appendChild(el('summary', null, 'How to grade'));
    box.appendChild(el('p', null, 'For each claim, decide whether the evidence the report cites backs it. ' +
      'You are not judging whether the claim is true in the real world, only whether the cited text supports it.'));
    var dl = el('dl', 'rubric');
    VERDICTS.forEach(function (v, n) {
      var row = el('div');
      row.appendChild(el('dt', null, (n + 1) + '. ' + v.label));
      row.appendChild(el('dd', null, v.definition));
      dl.appendChild(row);
    });
    box.appendChild(dl);
    var ol = el('ol', 'rules');
    DATA.rubric.rules.forEach(function (t) { ol.appendChild(el('li', null, t)); });
    box.appendChild(ol);
    var keys = el('div', 'keys');
    keys.innerHTML = '<kbd>1</kbd>-<kbd>4</kbd> verdict &middot; <kbd>0</kbd> clear &middot; ' +
      '<kbd>&uarr;</kbd><kbd>&darr;</kbd> previous / next claim &middot; <kbd>&larr;</kbd><kbd>&rarr;</kbd> previous / next report &middot; ' +
      '<kbd>Space</kbd> next ungraded claim &middot; <kbd>C</kbd> comment &middot; <kbd>?</kbd> this panel';
    box.appendChild(keys);
    box.addEventListener('toggle', function () {
      if (!box.open && !state.helpSeen) { state.helpSeen = true; save(); }
    });
    return box;
  }

  function renderEvidence(ev) {
    var wrap = el('div');
    var head = el('div', 'ev-head');
    head.appendChild(el('strong', null, ev.ref));
    if (ev.shortened) head.appendChild(el('span', 'badge', 'shortened'));
    if (!ev.found) head.appendChild(el('span', 'badge', 'not among the report evidence'));
    wrap.appendChild(head);
    wrap.appendChild(el('pre', 'ev', ev.text));
    return wrap;
  }

  function renderItem(report, item, n) {
    var g = gradeOf(report, item);
    var sec = el('section', 'item' + (n === state.i ? ' current' : '') + (g && g.v ? ' graded v-' + g.v : ''));
    sec.dataset.n = n;
    var grid = el('div', 'item-grid');
    var left = el('div');
    var head = el('div', 'item-head');
    head.appendChild(el('span', 'tag', item.index < 0 ? 'Stated root cause' : 'Finding ' + (item.index + 1)));
    head.appendChild(el('span', 'basis', item.basis));
    left.appendChild(head);
    left.appendChild(el('p', 'claim', item.claim));
    var cites = el('div', 'cites');
    cites.appendChild(document.createTextNode('Cites: '));
    if (item.evidence.length === 0) cites.appendChild(el('em', null, 'nothing'));
    item.evidence.forEach(function (ev, k) {
      if (k) cites.appendChild(document.createTextNode(' '));
      cites.appendChild(el('code', null, ev.ref));
    });
    left.appendChild(cites);
    var choices = el('div', 'choices');
    choices.setAttribute('role', 'radiogroup');
    VERDICTS.forEach(function (v, k) {
      var b = el('button', 'choice' + (g && g.v === v.key ? ' on' : ''));
      b.type = 'button'; b.dataset.v = v.key;
      b.setAttribute('role', 'radio'); b.setAttribute('aria-checked', g && g.v === v.key ? 'true' : 'false');
      b.appendChild(el('kbd', null, String(k + 1)));
      b.appendChild(document.createTextNode(v.label));
      b.addEventListener('click', function () { state.i = n; setVerdict(v.key); });
      choices.appendChild(b);
    });
    left.appendChild(choices);
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
    if (item.evidence.length === 0) right.appendChild(el('p', 'none', 'No evidence is cited for this claim.'));
    item.evidence.forEach(function (ev) { right.appendChild(renderEvidence(ev)); });
    grid.appendChild(right);
    sec.appendChild(grid);
    sec.addEventListener('click', function (e) {
      if (state.i !== n && !e.target.closest('button, textarea, summary')) { state.i = n; render(false); }
    });
    return sec;
  }

  function renderTop() {
    document.getElementById('title').textContent = DATA.title;
    var t = totals();
    var report = DATA.reports[state.r];
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
    var head = el('section', 'panel report');
    head.appendChild(el('div', 'label', 'Question'));
    head.appendChild(el('p', 'question', report.question));
    head.appendChild(el('div', 'label', 'The report'));
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
    if (scroll) {
      var cur = main.querySelector('.item.current');
      if (cur) cur.scrollIntoView({ block: 'center', behavior: 'smooth' });
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

  var msgTimer = null;
  function flash(text) {
    var m = document.getElementById('msg');
    m.textContent = text; m.hidden = false;
    window.clearTimeout(msgTimer);
    msgTimer = window.setTimeout(function () { m.hidden = true; }, 6000);
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
  document.getElementById('rater').addEventListener('input', function (e) { state.rater = e.target.value; save(); });
  function toggleHelp() {
    var h = document.getElementById('help');
    h.open = !h.open;
    if (!h.open) { state.helpSeen = true; save(); }
    if (h.open) h.scrollIntoView({ block: 'start' });
  }

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
