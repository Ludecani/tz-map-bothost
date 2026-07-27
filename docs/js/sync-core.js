/* Shared compact-sync helpers (LWW). Safe to load before map UI. */
(function (global) {
  'use strict';

  // Primary codes: 0 none/tombstone, 1 working, 2 done.
  // Extra flags (4th compact field): BS=1, scheme=2, suv=4.
  // Legacy exclusive codes 3/4/5 migrate to primary 0 + corresponding flag.
  var FLAG_BS = 1;
  var FLAG_SCHEME = 2;
  var FLAG_SUV = 4;
  var FLAG_BY_STATUS = {
    base_station: FLAG_BS,
    scheme_clarify: FLAG_SCHEME,
    suv_needed: FLAG_SUV
  };
  var STATUS_BY_FLAG = {};
  STATUS_BY_FLAG[FLAG_BS] = 'base_station';
  STATUS_BY_FLAG[FLAG_SCHEME] = 'scheme_clarify';
  STATUS_BY_FLAG[FLAG_SUV] = 'suv_needed';

  function migrateLegacyCode(code) {
    var c = Number(code);
    if (c === 3) return { c: 0, f: FLAG_BS };
    if (c === 4) return { c: 0, f: FLAG_SCHEME };
    if (c === 5) return { c: 0, f: FLAG_SUV };
    if (c === 1 || c === 2) return { c: c, f: 0 };
    return { c: 0, f: 0 };
  }

  function normalizeFlags(raw) {
    var f = Number(raw) || 0;
    return f & (FLAG_BS | FLAG_SCHEME | FLAG_SUV);
  }

  function packRow(code, by, at, flags) {
    var c = Number(code) || 0;
    if (c !== 0 && c !== 1 && c !== 2) {
      var mig = migrateLegacyCode(c);
      c = mig.c;
      flags = (Number(flags) || 0) | mig.f;
    }
    var f = normalizeFlags(flags);
    var row = [
      c,
      by != null ? String(by).slice(0, 24) : '',
      Number(at) || 0
    ];
    if (f) row.push(f);
    return row;
  }

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
      var flags = row.length > 3 ? row[3] : 0;
      out.m[String(idx)] = packRow(code, row[1], row[2], flags);
    });
    return out;
  }

  function rowEqual(a, b) {
    if (!a || !b) return false;
    if (a[0] !== b[0] || a[1] !== b[1] || a[2] !== b[2]) return false;
    var af = a.length > 3 ? (Number(a[3]) || 0) : 0;
    var bf = b.length > 3 ? (Number(b[3]) || 0) : 0;
    return af === bf;
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
        if (!rem || !rowEqual(rem, loc)) changed = true;
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
    var mig = migrateLegacyCode(code);
    if (mig.c === 1) return 'working';
    if (mig.c === 2) return 'done';
    return 'none';
  }

  function codeFromStatus(status) {
    if (status === 'working') return 1;
    if (status === 'done') return 2;
    // Legacy exclusive extras → primary none (flags handled separately).
    return 0;
  }

  function flagsFromCode(code) {
    return migrateLegacyCode(code).f;
  }

  function flagBit(name) {
    return FLAG_BY_STATUS[name] || 0;
  }

  function hasFlag(mask, name) {
    return !!(normalizeFlags(mask) & flagBit(name));
  }

  function decodeRow(row) {
    if (!row || !row.length) return { status: 'none', f: 0, by: '', at: 0 };
    var mig = migrateLegacyCode(row[0]);
    var f = normalizeFlags((row.length > 3 ? row[3] : 0) | mig.f);
    var status = 'none';
    if (mig.c === 1) status = 'working';
    else if (mig.c === 2) status = 'done';
    return {
      status: status,
      f: f,
      by: row[1] != null ? String(row[1]) : '',
      at: Number(row[2]) || 0
    };
  }

  global.TzSyncCore = {
    FLAG_BS: FLAG_BS,
    FLAG_SCHEME: FLAG_SCHEME,
    FLAG_SUV: FLAG_SUV,
    FLAG_BY_STATUS: FLAG_BY_STATUS,
    STATUS_BY_FLAG: STATUS_BY_FLAG,
    normalizeCompact: normalizeCompact,
    mergeCompactDocs: mergeCompactDocs,
    statusFromCode: statusFromCode,
    codeFromStatus: codeFromStatus,
    flagsFromCode: flagsFromCode,
    flagBit: flagBit,
    hasFlag: hasFlag,
    normalizeFlags: normalizeFlags,
    packRow: packRow,
    decodeRow: decodeRow,
    migrateLegacyCode: migrateLegacyCode
  };
})(typeof window !== 'undefined' ? window : globalThis);
