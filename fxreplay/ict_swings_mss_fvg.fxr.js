//@version=1
// ICT_Swings_MSS_FVG -- FXR Script port of mq5/ICT_Swings_MSS_FVG.mq5
//
// Visualization-only: swing highs/lows, MSS flips (genuine reversals only,
// not the initial warmup establishment), and FVGs with full type
// classification (IFVG/AFVG/AIFVG/OFVG/invalidated). No OB, no trading.
//
// Two things here are best-effort guesses, not confirmed API behavior --
// check these first if something looks wrong:
//   1. updateDrawingById()'s exact patch shape was never shown with a worked
//      example in the docs. This assumes it accepts the same field names as
//      rectangle()'s own creation args (time1/price1/time2/price2/styles),
//      applied as a partial patch. See finalizeZoneDrawing() below.
//   2. Whether onTick fires once per CLOSED candle only, or also mid-candle
//      on live ticks. This code defends against both: it only ever commits
//      new swing/FVG state for bar (index-1) via a catch-up loop, so
//      repeated intra-candle ticks are naturally idempotent no-ops.
//
// Also assumed (matches every docs example that uses it): `index` is a
// live global giving the current bar's absolute position, so an absolute
// index `i` we stored earlier converts to a lookback offset as `index - i`
// for high(n)/low(n)/closeC(n)/openC(n)/time(n).

// ---- palette (FXR's BaseColors has no orange/gold/dimgray -- built via rgba) ----
const COL_SWING_HIGH = color.red;
const COL_SWING_LOW  = color.blue;
const COL_MSS        = color.yellow;
const COL_IFVG        = color.rgba(255, 215, 0, 1);     // gold
const COL_AFVG        = color.rgba(255, 165, 0, 1);     // orange
const COL_AIFVG       = color.rgba(255, 140, 0, 1);     // dark orange
const COL_OFVG        = color.rgba(105, 105, 105, 1);   // dim gray
const COL_SPENT       = color.purple;

init = () => {
  indicator({ onMainPanel: true, format: 'inherit' });
  input.bool('Show swing points', true, 'showSwings', 'Display');
  input.bool('Show MSS', true, 'showMss', 'Display');
  input.bool('Show FVGs', true, 'showFvgs', 'Display');
  input.bool('Extend live FVGs to current bar', true, 'extendFvgs', 'Display');
};

// ------------------------------------------------------------------
// Persistent state -- module scope, survives across onTick calls.
// ------------------------------------------------------------------
let g_processedUpTo = -1;   // last absolute bar index fully committed

// swing-detection running state (mirrors the dual-candle/alternation algo)
let g_peakIdx = 0, g_troughIdx = 0;
let g_ev = []; // { confirmIdx, kind (0=high,1=low), swingIdx, price, drawId }

// regime / MSS
let g_mss = []; // { atIdx, brokenIdx, price, toUp }
let g_haveSWH = false, g_swhPrice = 0, g_swhIdx = 0;
let g_haveSWL = false, g_swlPrice = 0, g_swlIdx = 0;
let g_regime = 0; // 0 warmup, 1 up, 2 down
let g_lastSWHidx = -1, g_lastSWLidx = -1;

// FVG zones. state: 0=IFVG, 1=AFVG, 2=OFVG(stranded), 3=spent(invalidated), 4=AIFVG
let g_fvg = []; // { candle, zb, zt, bullish, triggerK, eligibleK, resolvedK, state, origState, drawId }

// pending AIFVG lists -- "mark all" means a leg can spawn several AIFVGs at
// once, so (unlike a single tracked index) these need to be lists, and every
// entry converts together when the armed swing is exceeded.
let g_pendingBullAifvg = [];
let g_pendingBearAifvg = [];

// ------------------------------------------------------------------
// Absolute-index price/time accessors -- converts a stored absolute bar
// index to the offset-from-now the platform's own high()/low()/etc expect.
// ------------------------------------------------------------------
function hA(i) { return high(index - i); }
function lA(i) { return low(index - i); }
function cA(i) { return closeC(index - i); }
function oA(i) { return openC(index - i); }
function tA(i) { return time(index - i); }

function addEv(confirmIdx, kind, swingIdx, price) {
  g_ev.push({ confirmIdx, kind, swingIdx, price, drawId: null });
  return g_ev.length - 1;
}

function addMss(atIdx, brokenIdx, price, toUp) {
  g_mss.push({ atIdx, brokenIdx, price, toUp, drawId: null });
}

function addFvg(candle, zb, zt, bull, triggerK, state) {
  g_fvg.push({
    candle, zb, zt, bullish: bull, triggerK, state, origState: state,
    eligibleK: (state === 1 || state === 4) ? triggerK : -1,
    resolvedK: -1, drawId: null,
  });
  return g_fvg.length - 1;
}

// Scans (lo..hi) for every qualifying 3-candle gap and marks ALL of them --
// unlike an OB's single-best-candle pick. straddlePrice mirrors the OB
// straddle guard (only used where OB would apply it: AFVG, not IFVG/AIFVG).
function scanFvgs(lo, hi, bullish, triggerK, state, straddlePrice) {
  lo = Math.max(lo, 0);
  const limit = Math.min(hi, index - 3); // never reference an unclosed bar
  for (let i = lo; i <= limit; i++) {
    if (bullish) {
      if (lA(i + 2) > hA(i)) {
        if (straddlePrice !== undefined && hA(i) <= straddlePrice) continue;
        addFvg(i, hA(i), lA(i + 2), true, triggerK, state);
      }
    } else {
      if (hA(i + 2) < lA(i)) {
        if (straddlePrice !== undefined && lA(i) >= straddlePrice) continue;
        addFvg(i, hA(i + 2), lA(i), false, triggerK, state);
      }
    }
  }
}

function pendingConvertAll(arr) {
  for (const idx of arr) { g_fvg[idx].state = 0; g_fvg[idx].origState = 0; }
  arr.length = 0;
}

// ------------------------------------------------------------------
// Drawing helpers
// ------------------------------------------------------------------
function fvgColor(z) {
  if (z.state === 2) return COL_OFVG;
  if (z.state === 3) return COL_SPENT;
  if (z.origState === 1) return COL_AFVG;
  if (z.origState === 4) return COL_AIFVG;
  return COL_IFVG;
}
function fvgLabel(z) {
  const base = z.origState === 1 ? 'AFVG' : z.origState === 4 ? 'AIFVG' : 'IFVG';
  if (z.state === 2) return 'OFVG';
  if (z.state === 3) return base + ' (inv)';
  return base;
}

function drawZone(z, extend) {
  const c = fvgColor(z);
  const rightIdx = extend ? index : (z.resolvedK !== -1 ? z.resolvedK : z.candle);
  z.drawId = rectangle(
    tA(z.candle), z.zt, tA(rightIdx), z.zb,
    { backgroundColor: color.rgba(0, 0, 0, 0), color: c, extendRight: extend }
  );
  plot.shapes(
    'FVG label', z.bullish ? z.zb : z.zt, fvgLabel(z), c, c,
    z.bullish ? 'shape_label_up' : 'shape_label_down', 'Absolute', 'small',
    z.candle - index, 0, 'fvglbl_' + g_fvg.indexOf(z)
  );
}

// NOTE (guess #1, see header): re-applying rectangle's own arg names as a
// partial patch. Verify updateDrawingById's real signature and fix if wrong.
function finalizeZoneDrawing(z) {
  if (z.drawId == null) { drawZone(z, false); return; }
  updateDrawingById(z.drawId, {
    time2: tA(z.resolvedK), price1: z.zt, price2: z.zb,
    color: fvgColor(z), extendRight: false,
  });
}

// ------------------------------------------------------------------
// Per-bar commit -- runs the swing/regime/FVG engine for exactly ONE newly
// closed bar `k`. Mirrors mq5/ICT_Swings_MSS_FVG.mq5's Process() loop body,
// just re-shaped to run incrementally instead of a full-history rebuild.
// ------------------------------------------------------------------
function commitBar(k, inputs) {
  // --- swing detection (dual-candle aware, alternation-blocked) ---
  if (k >= 1) {
    const bullish = cA(k) >= oA(k);
    const breaksPrevHigh = hA(k) > hA(k - 1);
    const breaksPrevLow = lA(k) < lA(k - 1);
    const dualAction = breaksPrevHigh && breaksPrevLow;

    let prevDual = false;
    if (g_ev.length >= 2) {
      const a = g_ev[g_ev.length - 1], b = g_ev[g_ev.length - 2];
      prevDual = (a.kind !== b.kind) && (a.confirmIdx === b.confirmIdx) && (a.confirmIdx === k - 1);
    }
    const blockPostDual = prevDual && !dualAction;

    if (!bullish) {
      if (hA(k) > hA(g_peakIdx)) g_peakIdx = k;
      if (breaksPrevHigh) {
        const lastWasLow = g_ev.length > 0 && g_ev[g_ev.length - 1].kind === 1;
        if (!lastWasLow && !blockPostDual) { addEv(k, 1, g_troughIdx, lA(g_troughIdx)); g_peakIdx = k; }
      }
      if (lA(k) < lA(g_troughIdx)) g_troughIdx = k;
      if (breaksPrevLow) {
        const lastWasHigh = g_ev.length > 0 && g_ev[g_ev.length - 1].kind === 0;
        if (!lastWasHigh && !blockPostDual) { addEv(k, 0, g_peakIdx, hA(g_peakIdx)); g_troughIdx = k; }
      }
    } else {
      if (lA(k) < lA(g_troughIdx)) g_troughIdx = k;
      if (breaksPrevLow) {
        const lastWasHigh = g_ev.length > 0 && g_ev[g_ev.length - 1].kind === 0;
        if (!lastWasHigh && !blockPostDual) { addEv(k, 0, g_peakIdx, hA(g_peakIdx)); g_troughIdx = k; }
      }
      if (hA(k) > hA(g_peakIdx)) g_peakIdx = k;
      if (breaksPrevHigh) {
        const lastWasLow = g_ev.length > 0 && g_ev[g_ev.length - 1].kind === 1;
        if (!lastWasLow && !blockPostDual) { addEv(k, 1, g_troughIdx, lA(g_troughIdx)); g_peakIdx = k; }
      }
    }
  }

  // --- regime / MSS / FVG ---
  const evAtK = g_ev.filter((e) => e.confirmIdx === k);
  for (const e of evAtK) {
    if (e.kind === 0) g_lastSWHidx = e.swingIdx; else g_lastSWLidx = e.swingIdx;
  }

  const prevRegime = g_regime;
  const aobSWHidx = g_swhIdx, aobSWLidx = g_swlIdx;
  const kBullish = k >= 1 ? cA(k) >= oA(k) : true;

  function continuationBull() {
    if (g_pendingBullAifvg.length > 0) { pendingConvertAll(g_pendingBullAifvg); }
    else if (g_lastSWLidx >= 0) {
      const lo = Math.min(Math.min(g_lastSWLidx, k), g_swhIdx);
      const hi = Math.max(Math.max(g_lastSWLidx, k), g_swhIdx);
      scanFvgs(lo, hi, true, k, 0);
    }
  }
  function continuationBear() {
    if (g_pendingBearAifvg.length > 0) { pendingConvertAll(g_pendingBearAifvg); }
    else if (g_lastSWHidx >= 0) {
      const lo = Math.min(Math.min(g_lastSWHidx, k), g_swlIdx);
      const hi = Math.max(Math.max(g_lastSWHidx, k), g_swlIdx);
      scanFvgs(lo, hi, false, k, 0);
    }
  }

  function armBranch() {
    for (const e of evAtK) {
      if (e.kind === 0) {
        g_haveSWH = true; g_swhPrice = e.price; g_swhIdx = e.swingIdx;
        g_pendingBullAifvg.length = 0;
        if (prevRegime === 2 && aobSWLidx >= 0) {
          const lo = Math.max(0, Math.min(aobSWLidx - 1, e.swingIdx));
          const hi = Math.max(aobSWLidx - 1, e.swingIdx);
          scanFvgs(lo, hi, false, k, 1, e.price);
        }
        if (prevRegime === 2 && g_haveSWL && aobSWLidx >= 0 && g_lastSWHidx >= 0) {
          const lo2 = Math.max(0, Math.min(Math.min(g_lastSWHidx, e.swingIdx), aobSWLidx - 1));
          const hi2 = Math.max(Math.max(g_lastSWHidx, e.swingIdx), aobSWLidx - 1);
          const before = g_fvg.length;
          scanFvgs(lo2, hi2, false, k, 4);
          for (let z = before; z < g_fvg.length; z++) g_pendingBearAifvg.push(z);
        }
      } else {
        g_haveSWL = true; g_swlPrice = e.price; g_swlIdx = e.swingIdx;
        g_pendingBearAifvg.length = 0;
        if (prevRegime === 1 && aobSWHidx >= 0) {
          const lo = Math.max(0, Math.min(aobSWHidx - 1, e.swingIdx));
          const hi = Math.max(aobSWHidx - 1, e.swingIdx);
          scanFvgs(lo, hi, true, k, 1, e.price);
        }
        if (prevRegime === 1 && g_haveSWH && aobSWHidx >= 0 && g_lastSWLidx >= 0) {
          const lo2 = Math.max(0, Math.min(Math.min(g_lastSWLidx, e.swingIdx), aobSWHidx - 1));
          const hi2 = Math.max(Math.max(g_lastSWLidx, e.swingIdx), aobSWHidx - 1);
          const before = g_fvg.length;
          scanFvgs(lo2, hi2, true, k, 4);
          for (let z = before; z < g_fvg.length; z++) g_pendingBullAifvg.push(z);
        }
      }
    }
  }

  if (!kBullish) {
    if (g_haveSWH && hA(k) > g_swhPrice) {
      if (g_regime === 0) g_regime = 1;
      else if (g_regime === 2) { g_regime = 1; addMss(k, g_swhIdx, g_swhPrice, true); }
      continuationBull();
      g_haveSWH = false;
    }
    armBranch();
    if (g_haveSWL && lA(k) < g_swlPrice) {
      if (g_regime === 0) g_regime = 2;
      else if (g_regime === 1) { g_regime = 2; addMss(k, g_swlIdx, g_swlPrice, false); }
      continuationBear();
      g_haveSWL = false;
    }
  } else {
    if (g_haveSWL && lA(k) < g_swlPrice) {
      if (g_regime === 0) g_regime = 2;
      else if (g_regime === 1) { g_regime = 2; addMss(k, g_swlIdx, g_swlPrice, false); }
      continuationBear();
      g_haveSWL = false;
    }
    armBranch();
    if (g_haveSWH && hA(k) > g_swhPrice) {
      if (g_regime === 0) g_regime = 1;
      else if (g_regime === 2) { g_regime = 1; addMss(k, g_swhIdx, g_swhPrice, true); }
      continuationBull();
      g_haveSWH = false;
    }
  }
  // --- eligibility arm (IFVG only -- AFVG/AIFVG are eligible immediately) ---
  for (const e of evAtK) {
    if (e.kind === 0) {
      for (const z of g_fvg) if (z.bullish && z.state === 0 && z.eligibleK === -1 && k > z.triggerK) z.eligibleK = k;
    } else {
      for (const z of g_fvg) if (!z.bullish && z.state === 0 && z.eligibleK === -1 && k > z.triggerK) z.eligibleK = k;
    }
  }

  // --- lifecycle: invalidation (body closes fully through the far edge)
  // takes priority, then structural stranding (OFVG), same swing-based rule.
  for (const z of g_fvg) {
    if (z.state === 3 || z.state === 2) continue;
    if (z.eligibleK === -1 || k < z.eligibleK) continue;

    const invalidated = z.bullish ? cA(k) < z.zb : cA(k) > z.zt;
    if (invalidated) { z.state = 3; z.resolvedK = k; finalizeZoneDrawing(z); continue; }

    const isIFVG = z.origState !== 1;
    for (const e of evAtK) {
      if (isIFVG) {
        if (z.bullish && e.kind === 1 && e.price > z.zt) { z.state = 2; z.resolvedK = k; }
        if (!z.bullish && e.kind === 0 && e.price < z.zb) { z.state = 2; z.resolvedK = k; }
      } else {
        if (z.bullish && e.kind === 0 && e.price < z.zb) { z.state = 2; z.resolvedK = k; }
        if (!z.bullish && e.kind === 1 && e.price > z.zt) { z.state = 2; z.resolvedK = k; }
      }
      if (z.state === 2) { finalizeZoneDrawing(z); break; }
    }
  }
}

// ------------------------------------------------------------------
// onTick -- catches up bar-by-bar (guards against both once-per-close and
// once-per-tick platforms) then draws anything newly created this pass.
// ------------------------------------------------------------------
onTick = (length, _moment, _, ta, inputs) => {
  const fvgBefore = g_fvg.length;
  const evBefore = g_ev.length;
  const mssBefore = g_mss.length;

  while (g_processedUpTo < index - 1) {
    commitBar(g_processedUpTo + 1, inputs);
    g_processedUpTo++;
  }

  if (inputs.showSwings) {
    for (let e = evBefore; e < g_ev.length; e++) {
      const ev = g_ev[e];
      const isHigh = ev.kind === 0;
      plot.shapes(
        'Swing', isHigh ? hA(ev.swingIdx) : lA(ev.swingIdx), '',
        isHigh ? COL_SWING_HIGH : COL_SWING_LOW, isHigh ? COL_SWING_HIGH : COL_SWING_LOW,
        isHigh ? 'shape_triangle_down' : 'shape_triangle_up',
        isHigh ? 'AboveBar' : 'BelowBar', 'small',
        ev.swingIdx - index, 0, 'sw_' + e
      );
    }
  }

  if (inputs.showMss) {
    for (let m = mssBefore; m < g_mss.length; m++) {
      const mss = g_mss[m];
      plot.shapes(
        'MSS', mss.toUp ? hA(mss.brokenIdx) : lA(mss.brokenIdx), 'MSS', COL_MSS, COL_MSS,
        mss.toUp ? 'shape_label_up' : 'shape_label_down',
        mss.toUp ? 'AboveBar' : 'BelowBar', 'normal',
        mss.brokenIdx - index, 0, 'mss_' + m
      );
    }
  }

  if (inputs.showFvgs) {
    for (let z = fvgBefore; z < g_fvg.length; z++) drawZone(g_fvg[z], inputs.extendFvgs);
  }
};
