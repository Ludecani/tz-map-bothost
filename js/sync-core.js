/* Shared compact-sync helpers (LWW). Safe to load before map UI. */
(function (global) {
  'use strict';

  function normalizeCompact(doc) {
    var out = { v: 1, r: 'tz-map-novgorod', t: 0, seq: 0, m: {} };
    if (!doc || typeof doc !== 'object') return out;
    out.v = Number(doc.v) || 1;
    out.r = String(doc.r || out.r).slice(0, 64);
    out.t = Number(doc.t) || 0;
    out.seq = Math.max(0, Number(doc.seq) || 0);
    var m = doc.m && typeof doc.m === 'object' ? doc.m : {};
    Object.keys(m).forEach(function (idx) {
      var row = m[idx];
      if (!row || !row.length) return;
      var code = Number(row[0]);
      if (!(code === 0 || code === 1 || code === 2 || code === 3 || code === 4 || code === 5)) return;
      out.m[String(idx)] = [
        code,
        row[1] != null ? String(row[1]).slice(0, 24) : '',
        Number(row[2]) || 0
      ];
    });
    return out;
  }

  function mergeCompactDocs(remoteDoc, localDoc) {
    var base = normalizeCompact(remoteDoc);
    var incoming = normalizeCompact(localDoc);
    var outM = {};
    Object.keys(base.m).forEach(function (idx) {
      outM[idx] = base.m[idx].slice(0);
    });
    var changed = false;
    Object.keys(incoming.m).forEach(function (idx) {
      var loc = incoming.m[idx];
      var rem = outM[idx];
      var locAt = Number(loc[2]) || 0;
      var remAt = rem ? (Number(rem[2]) || 0) : 0;
      if (!rem || locAt >= remAt) {
        if (!rem || rem[0] !== loc[0] || rem[1] !== loc[1] || remAt !== locAt) changed = true;
        outM[idx] = loc.slice(0);
      }
    });
    var tVals = [base.t, incoming.t];
    Object.keys(outM).forEach(function (idx) {
      tVals.push(Number(outM[idx][2]) || 0);
    });
    var seq = Math.max(base.seq, incoming.seq);
    if (changed) seq += 1;
    return {
      v: 1,
      r: incoming.r || base.r,
      t: Math.max.apply(null, tVals.concat([0])),
      seq: seq,
      m: outM
    };
  }

  function statusFromCode(code) {
    var c = Number(code);
    if (c === 1) return 'working';
    if (c === 2) return 'done';
    if (c === 3) return 'base_station';
    if (c === 4) return 'scheme_clarify';
    if (c === 5) return 'suv_needed';
    return 'none';
  }

  function codeFromStatus(status) {
    if (status === 'working') return 1;
    if (status === 'done') return 2;
    if (status === 'base_station') return 3;
    if (status === 'scheme_clarify') return 4;
    if (status === 'suv_needed') return 5;
    return 0;
  }

  global.TzSyncCore = {
    normalizeCompact: normalizeCompact,
    mergeCompactDocs: mergeCompactDocs,
    statusFromCode: statusFromCode,
    codeFromStatus: codeFromStatus
  };
})(typeof window !== 'undefined' ? window : globalThis);
