/* Ops table sorting — makes every data table's column headers clickable to sort
 * A→Z / Z→A (with ▲▼ arrows), like a spreadsheet. Founder 2026-07-18.
 *
 * SAFE BY DESIGN:
 *  - Only touches tables that have a <thead> with <th> cells and a <tbody> with
 *    2+ rows. Layout tables (no <thead>) are ignored.
 *  - Never reorders on load — it preserves the server's default order until the
 *    user clicks a header. So "latest on top" defaults set on the server stay put.
 *  - Only reorders <tbody> rows; <tfoot> totals stay pinned.
 *  - Opt OUT a table with data-no-sort, or a single column with data-no-sort.
 */
(function () {
  'use strict';

  function cellText(row, i) {
    var c = row.children[i];
    return c ? (c.getAttribute('data-sort') || c.textContent).trim() : '';
  }

  // Detect a comparable value: number (incl. ₹, A$, %, commas) or date, else text.
  var MONTHS = { jan:0,feb:1,mar:2,apr:3,may:4,jun:5,jul:6,aug:7,sep:8,oct:9,nov:10,dec:11 };
  function parseVal(s) {
    if (s === '' || s === '—' || s === '-') return { t: 'empty', v: 0 };
    // date: dd-Mon-yyyy  or  dd Mon yyyy
    var m = s.match(/(\d{1,2})[\-\s]([A-Za-z]{3})[A-Za-z]*[\-\s](\d{4})/);
    if (m && MONTHS[m[2].toLowerCase()] !== undefined) {
      return { t: 'date', v: new Date(+m[3], MONTHS[m[2].toLowerCase()], +m[1]).getTime() };
    }
    // date: yyyy-mm-dd
    m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (m) return { t: 'date', v: new Date(+m[1], +m[2] - 1, +m[3]).getTime() };
    // date: dd/mm/yyyy
    m = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/);
    if (m) return { t: 'date', v: new Date(+m[3], +m[2] - 1, +m[1]).getTime() };
    // number (strip currency, commas, %, spaces)
    var num = s.replace(/[₹$,%\s]/g, '').replace(/A\$/i, '').replace(/[^\d.\-]/g, '');
    if (num !== '' && !isNaN(num) && /\d/.test(s)) return { t: 'num', v: parseFloat(num) };
    return { t: 'text', v: s.toLowerCase() };
  }

  function sortTable(table, colIdx, dir) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.prototype.slice.call(tbody.rows);
    rows.sort(function (a, b) {
      var pa = parseVal(cellText(a, colIdx)), pb = parseVal(cellText(b, colIdx));
      // empties always sink to the bottom regardless of direction
      if (pa.t === 'empty' && pb.t !== 'empty') return 1;
      if (pb.t === 'empty' && pa.t !== 'empty') return -1;
      var r;
      if (pa.t === 'text' || pb.t === 'text') {
        r = String(pa.v).localeCompare(String(pb.v));
      } else {
        r = pa.v < pb.v ? -1 : (pa.v > pb.v ? 1 : 0);
      }
      return dir === 'desc' ? -r : r;
    });
    rows.forEach(function (r) { tbody.appendChild(r); });
  }

  function initTable(table) {
    if (table.hasAttribute('data-no-sort') || table.__sortInit) return;
    var thead = table.tHead;
    if (!thead || !table.tBodies[0] || table.tBodies[0].rows.length < 2) return;
    var headRow = thead.rows[thead.rows.length - 1];
    if (!headRow) return;
    table.__sortInit = true;

    Array.prototype.forEach.call(headRow.cells, function (th, i) {
      if (th.hasAttribute('data-no-sort')) return;
      th.style.cursor = 'pointer';
      th.style.userSelect = 'none';
      th.title = 'Click to sort';
      var arrow = document.createElement('span');
      arrow.className = 'ots-arrow';
      arrow.style.cssText = 'opacity:.35;font-size:.8em;margin-left:4px;';
      arrow.textContent = '⇅';
      th.appendChild(arrow);

      th.addEventListener('click', function () {
        var dir = th.__dir === 'asc' ? 'desc' : 'asc';
        // reset every header's arrow
        Array.prototype.forEach.call(headRow.cells, function (h) {
          h.__dir = null;
          var a = h.querySelector('.ots-arrow');
          if (a) { a.textContent = '⇅'; a.style.opacity = '.35'; }
        });
        th.__dir = dir;
        arrow.textContent = dir === 'asc' ? '▲' : '▼';
        arrow.style.opacity = '1';
        sortTable(table, i, dir);
      });
    });
  }

  function initAll() {
    document.querySelectorAll('table').forEach(initTable);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAll);
  } else {
    initAll();
  }
  // expose for pages that inject tables later
  window.opsInitTableSort = initAll;
})();
