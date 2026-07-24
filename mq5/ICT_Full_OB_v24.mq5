//+------------------------------------------------------------------+
//|                                       ICT_SwingMSS_Verify.mq5   |
//|   VERIFICATION BUILD: draws ONLY swing highs, swing lows, and   |
//|   MSS flips. No OB, no FVG, no RB, no regime shading.           |
//|   Same proven engine logic from ICT_Structure_POI_v13diag.mq5.  |
//|                                                                  |
//|   Purpose: visually verify the three foundational elements on    |
//|   EURUSD Daily before building anything on top of them.          |
//+------------------------------------------------------------------+
#property indicator_chart_window
#property indicator_plots 0
#property strict

input int   InpMonthsBack  = 6;             // months to display (from last closed candle)
input datetime InpReplayUpTo = 0;            // replay up to this date (0 = show all)
input color InpColorHigh   = clrCrimson;    // swing high color
input color InpColorLow    = clrRoyalBlue;  // swing low color
input color InpColorMSS    = clrMagenta;    // MSS flip color

const string PFX = "SWMSS_";

//--- confirmed swing events: kind 0=high, 1=low
struct SwEv { int confirmIdx; int kind; int swingIdx; double price; };
SwEv  g_ev[];
int   g_evCount = 0;

void AddEv(int confirmIdx, int kind, int swingIdx, double price)
  {
   ArrayResize(g_ev, g_evCount + 1);
   g_ev[g_evCount].confirmIdx = confirmIdx;
   g_ev[g_evCount].kind       = kind;
   g_ev[g_evCount].swingIdx   = swingIdx;
   g_ev[g_evCount].price      = price;
   g_evCount++;
  }

//--- MSS flips
struct MssEv { int atIdx; int brokenIdx; double price; bool toUp; };
MssEv g_mss[];
int   g_mssCount = 0;

void AddMss(int atIdx, int brokenIdx, double price, bool toUp)
  {
   ArrayResize(g_mss, g_mssCount + 1);
   g_mss[g_mssCount].atIdx     = atIdx;
   g_mss[g_mssCount].brokenIdx = brokenIdx;
   g_mss[g_mssCount].price     = price;
   g_mss[g_mssCount].toUp      = toUp;
   g_mssCount++;
  }

//--- Order Blocks: 0=IFOB, 1=AOB, 2=OOB, 3=SPENT
struct ObZone {
   int    candle;       // OB candle (zone body)
   double zb, zt;       // zone bottom/top (open-to-close)
   bool   bullish;      // true=buy, false=sell
   int    triggerK;     // candle that triggered creation
   int    eligibleK;    // impact eligible from this candle (-1=not yet)
   int    stopK;        // box stops here (-1=extending)
   int    state;        // 0=IFOB, 1=AOB, 2=OOB, 3=SPENT
   int    origState;    // original state at creation (for drawing color)
};
ObZone g_ob[];
int    g_obCount = 0;

void AddOB(int candle, double zb, double zt, bool bull, int triggerK, int state)
  {
   ArrayResize(g_ob, g_obCount + 1);
   g_ob[g_obCount].candle    = candle;
   g_ob[g_obCount].zb        = zb;
   g_ob[g_obCount].zt        = zt;
   g_ob[g_obCount].bullish   = bull;
   g_ob[g_obCount].triggerK  = triggerK;
   g_ob[g_obCount].eligibleK = (state == 1) ? triggerK : -1;
   g_ob[g_obCount].stopK     = -1;
   g_ob[g_obCount].state     = state;
   g_ob[g_obCount].origState = state;
   g_obCount++;
  }
int g_shIdx[];
int g_shCount = 0;

void AddSH(int idx)
  {
   if(g_shCount > 0 && g_shIdx[g_shCount - 1] == idx) return;
   ArrayResize(g_shIdx, g_shCount + 1);
   g_shIdx[g_shCount] = idx;
   g_shCount++;
  }

//--- recorded confirmed swing lows
int g_slIdx[];
int g_slCount = 0;

void AddSL(int idx)
  {
   if(g_slCount > 0 && g_slIdx[g_slCount - 1] == idx) return;
   ArrayResize(g_slIdx, g_slCount + 1);
   g_slIdx[g_slCount] = idx;
   g_slCount++;
  }

//+------------------------------------------------------------------+
//| AOB hunts — must run regardless of the confirming candle's own   |
//| body direction, so both are called from all four MID-ARM sites.  |
//+------------------------------------------------------------------+
void TryBullishAOB(int prevRegime, int aobSWHidx, int newSwlIdx, double newSwlPrice,
                    const double &O[], const double &H[], const double &L[], const double &C[],
                    const datetime &Time[], int k, int n)
  {
   bool diagOB = (k >= n - 40);
   if(prevRegime != 1 || aobSWHidx < 0)
     {
      if(diagOB)
         PrintFormat("AOB-HUNT(bull) swl=%s SKIPPED prevRegime=%d aobSWHidx=%s",
                     TimeToString(Time[k], TIME_DATE), prevRegime,
                     (aobSWHidx>=0?TimeToString(Time[aobSWHidx], TIME_DATE):"-1"));
      return;
     }
   int lo2 = MathMin(aobSWHidx, newSwlIdx);
   int hi2 = MathMax(aobSWHidx, newSwlIdx);
   int best2 = -1;
   // rank by body extremity (close), not wick -- the zone itself is drawn
   // open-to-close, so selection should match.
   for(int x = lo2; x <= hi2; x++)
      if(C[x] > O[x] && (best2 == -1 || C[x] > C[best2])) best2 = x;
   // if the picked candle's low reaches the swing low that triggered this
   // hunt, it IS (or straddles) the pivot itself, not a candle inside the
   // completed retracement.
   bool passGuard = (best2 != -1 && L[best2] > newSwlPrice);
   if(diagOB)
      PrintFormat("AOB-HUNT(bull) swl=%s prevRegime=%d range=[%s..%s] best2=%s passGuard=%d",
                  TimeToString(Time[k], TIME_DATE), prevRegime,
                  TimeToString(Time[lo2], TIME_DATE), TimeToString(Time[hi2], TIME_DATE),
                  (best2!=-1?TimeToString(Time[best2], TIME_DATE):"-"), passGuard);
   if(passGuard)
      AddOB(best2, MathMin(O[best2],C[best2]), MathMax(O[best2],C[best2]), true, k, 1);
  }

void TryBearishAOB(int prevRegime, int aobSWLidx, int newSwhIdx, double newSwhPrice,
                    const double &O[], const double &H[], const double &L[], const double &C[],
                    const datetime &Time[], int k, int n)
  {
   bool diagOB2 = (k >= n - 40);
   if(prevRegime != 2 || aobSWLidx < 0)
     {
      if(diagOB2)
         PrintFormat("AOB-HUNT(bear) swh=%s SKIPPED prevRegime=%d aobSWLidx=%s",
                     TimeToString(Time[k], TIME_DATE), prevRegime,
                     (aobSWLidx>=0?TimeToString(Time[aobSWLidx], TIME_DATE):"-1"));
      return;
     }
   int lo2 = MathMin(aobSWLidx, newSwhIdx);
   int hi2 = MathMax(aobSWLidx, newSwhIdx);
   int best2 = -1;
   // rank by body extremity (close), not wick -- the zone itself is drawn
   // open-to-close, so selection should match.
   for(int x = lo2; x <= hi2; x++)
      if(C[x] < O[x] && (best2 == -1 || C[x] < C[best2])) best2 = x;
   // mirror guard: if the picked candle's high reaches the swing high that
   // triggered this hunt, it IS (or straddles) the pivot itself, not a
   // retracement candle.
   bool passGuard2 = (best2 != -1 && H[best2] < newSwhPrice);
   if(diagOB2)
      PrintFormat("AOB-HUNT(bear) swh=%s prevRegime=%d range=[%s..%s] best2=%s passGuard=%d",
                  TimeToString(Time[k], TIME_DATE), prevRegime,
                  TimeToString(Time[lo2], TIME_DATE), TimeToString(Time[hi2], TIME_DATE),
                  (best2!=-1?TimeToString(Time[best2], TIME_DATE):"-"), passGuard2);
   if(passGuard2)
      AddOB(best2, MathMin(O[best2],C[best2]), MathMax(O[best2],C[best2]), false, k, 1);
  }

//+------------------------------------------------------------------+
//| CORE ENGINE — v2: handles same-candle dual swings correctly.     |
//+------------------------------------------------------------------+
void Process(const double &O[], const double &H[],
             const double &L[], const double &C[], const datetime &Time[], int n)
  {
   g_shCount  = 0; ArrayResize(g_shIdx, 0);
   g_slCount  = 0; ArrayResize(g_slIdx, 0);
   g_evCount  = 0; ArrayResize(g_ev, 0);
   g_mssCount = 0; ArrayResize(g_mss, 0);
   g_obCount  = 0; ArrayResize(g_ob, 0);
   if(n < 2) return;

   //--- SWING HIGHS + SWING LOWS — ONE merged pass, both trackers live.
   //    FIX v3: a candle's bullish/bearish body tells us the REAL order
   //    events happened inside that bar (no tick data, so this is our best
   //    proxy): bullish = Low reached first, then High. bearish = High
   //    reached first, then Low. On a candle that triggers BOTH break
   //    conditions at once, this ordering decides which check uses the OLD
   //    reference (from before this candle) and which uses the NEW one
   //    (already updated earlier in the SAME bar). Getting this backwards is
   //    NOISE FILTER v9 (user numbering): two universal rules.
   //    RULE 1 — ALTERNATION: check the last recorded event. Same type as
   //    what we're about to confirm → skip. Different type → allow. Checked
   //    against the actual g_ev[] array, no boolean that can drift.
   //    RULE 2 — POST-DUAL BLOCK: if the previous candle was "dual-action"
   //    (produced BOTH a SWH and a SWL, detectable by the last two events
   //    having the same confirmIdx and different kinds), AND the current
   //    candle is "single-action" (breaks only one side of the previous
   //    candle), AND it's the very next candle → block. This is continuation
   //    noise after a volatile bar, not a new swing point.
   //    Dual-action candles themselves are NEVER blocked. ---
   int    peakIdx   = 0;
   int    troughIdx  = 0;

   for(int i = 1; i < n; i++)
     {
      bool bullish = (C[i] >= O[i]);
      bool breaksPrevHigh = (H[i] > H[i - 1]);
      bool breaksPrevLow  = (L[i] < L[i - 1]);
      bool dualAction = (breaksPrevHigh && breaksPrevLow);

      // detect if previous candle was dual-action
      bool prevDual = false;
      if(g_evCount >= 2)
        {
         bool diffKinds    = (g_ev[g_evCount - 1].kind != g_ev[g_evCount - 2].kind);
         bool sameConfirm  = (g_ev[g_evCount - 1].confirmIdx == g_ev[g_evCount - 2].confirmIdx);
         bool wasLastCandle = (g_ev[g_evCount - 1].confirmIdx == i - 1);
         prevDual = diffKinds && sameConfirm && wasLastCandle;
        }

      // block: previous was dual-action, current is single-action, immediately after
      bool blockPostDual = (prevDual && !dualAction);

      // DIAGNOSTIC: print for last 15 candles of dataset
      bool diag = (i >= n - 15);
      if(diag)
         PrintFormat("DIAG i=%d %s O=%.5f H=%.5f L=%.5f C=%.5f brkH=%d brkL=%d dual=%d prevDual=%d blockPD=%d lastEvKind=%d evCnt=%d peakIdx=%d troughIdx=%d",
                     i, bullish?"BUY":"SELL", O[i],H[i],L[i],C[i],
                     breaksPrevHigh,breaksPrevLow,dualAction,prevDual,blockPostDual,
                     (g_evCount>0?g_ev[g_evCount-1].kind:-1), g_evCount, peakIdx, troughIdx);

      if(!bullish)
        {
         //--- BEARISH: High reached first, then Low ---
         if(H[i] > H[peakIdx]) peakIdx = i;

         if(breaksPrevHigh)
           {
            bool lastWasLow = (g_evCount > 0 && g_ev[g_evCount - 1].kind == 1);
            if(!lastWasLow && !blockPostDual)
              {
               AddSL(troughIdx);
               AddEv(i, 1, troughIdx, L[troughIdx]);
               peakIdx = i;   // opposite tracker resets: new up-leg starts
               if(diag) PrintFormat("  -> CONFIRMED SWL at troughIdx=%d price=%.5f", troughIdx, L[troughIdx]);
              }
            else if(diag) PrintFormat("  -> BLOCKED SWL (lastWasLow=%d blockPD=%d)", lastWasLow, blockPostDual);
           }

         if(L[i] < L[troughIdx]) troughIdx = i;

         if(breaksPrevLow)
           {
            bool lastWasHigh = (g_evCount > 0 && g_ev[g_evCount - 1].kind == 0);
            if(!lastWasHigh && !blockPostDual)
              {
               AddSH(peakIdx);
               AddEv(i, 0, peakIdx, H[peakIdx]);
               troughIdx = i;  // opposite tracker resets: new down-leg starts
               if(diag) PrintFormat("  -> CONFIRMED SWH at peakIdx=%d price=%.5f", peakIdx, H[peakIdx]);
              }
            else if(diag) PrintFormat("  -> BLOCKED SWH (lastWasHigh=%d blockPD=%d)", lastWasHigh, blockPostDual);
           }
        }
      else
        {
         //--- BULLISH: Low reached first, then High ---
         if(L[i] < L[troughIdx]) troughIdx = i;

         if(breaksPrevLow)
           {
            bool lastWasHigh = (g_evCount > 0 && g_ev[g_evCount - 1].kind == 0);
            if(!lastWasHigh && !blockPostDual)
              {
               AddSH(peakIdx);
               AddEv(i, 0, peakIdx, H[peakIdx]);
               troughIdx = i;  // opposite tracker resets: new down-leg starts
               if(diag) PrintFormat("  -> CONFIRMED SWH at peakIdx=%d price=%.5f", peakIdx, H[peakIdx]);
              }
            else if(diag) PrintFormat("  -> BLOCKED SWH (lastWasHigh=%d blockPD=%d)", lastWasHigh, blockPostDual);
           }

         if(H[i] > H[peakIdx]) peakIdx = i;

         if(breaksPrevHigh)
           {
            bool lastWasLow = (g_evCount > 0 && g_ev[g_evCount - 1].kind == 1);
            if(!lastWasLow && !blockPostDual)
              {
               AddSL(troughIdx);
               AddEv(i, 1, troughIdx, L[troughIdx]);
               peakIdx = i;   // opposite tracker resets: new up-leg starts
               if(diag) PrintFormat("  -> CONFIRMED SWL at troughIdx=%d price=%.5f", troughIdx, L[troughIdx]);
              }
            else if(diag) PrintFormat("  -> BLOCKED SWL (lastWasLow=%d blockPD=%d)", lastWasLow, blockPostDual);
           }
        }
     }

   //--- sort events by confirmation index ---
   for(int a = 0; a < g_evCount; a++)
      for(int b = a + 1; b < g_evCount; b++)
         if(g_ev[b].confirmIdx < g_ev[a].confirmIdx)
           { SwEv tmp = g_ev[a]; g_ev[a] = g_ev[b]; g_ev[b] = tmp; }

   //--- REGIME / MSS + OB ENGINE ---
   bool   haveSWH = false; double swhPrice = 0; int swhIdx = 0;
   bool   haveSWL = false; double swlPrice = 0; int swlIdx = 0;
   int    regime  = 0;   // 0=warmup, 1=up, 2=down
   int    ei      = 0;
   int    lastSWHidx = -1, lastSWLidx = -1;  // OB scan boundaries
   int    prevRegime = 0;  // track regime before this candle for AOB conversion

   for(int k = 0; k < n; k++)
     {
      //--- STEP 0: peek-ahead — update lastSWHidx/lastSWLidx from events
      //    confirmed at THIS candle, BEFORE breaks run. This ensures the
      //    OB scan sees the correct, up-to-date swing boundaries even when
      //    the breaking candle itself confirms a new swing (e.g. candle 19). ---
      {
         int peek = ei;
         while(peek < g_evCount && g_ev[peek].confirmIdx == k)
           {
            if(g_ev[peek].kind == 0) lastSWHidx = g_ev[peek].swingIdx;
            else                     lastSWLidx = g_ev[peek].swingIdx;
            peek++;
           }
      }

      prevRegime = regime;
      bool swhConsumed = false, swlConsumed = false;
      // save ARMED swing indices before STEP 0/MID-ARM change them
      int aobSWHidx = swhIdx;   // the armed SWH candle
      int aobSWLidx = swlIdx;   // the armed SWL candle

      //--- STEP 1: break checks + MSS + IFOB creation ---
      bool kBullish = (C[k] >= O[k]);
      if(!kBullish)
        {
         // bearish: high happened first -> check the armed SWH break first
         if(haveSWH && H[k] > swhPrice)
           {
            if(regime == 0)      regime = 1;
            else if(regime == 2) { regime = 1; AddMss(k, swhIdx, swhPrice, true); }
            // IFOB: bullish OB — scan from lastSWLidx through swhIdx to k
            if(lastSWLidx >= 0)
              {
               int lo = MathMin(MathMin(lastSWLidx, k), swhIdx);
               int hi = MathMax(MathMax(lastSWLidx, k), swhIdx);
               int best = -1;
               for(int x = lo; x <= hi; x++)
                  // rank by body extremity (close), not wick -- the zone
                  // itself is drawn open-to-close, so selection should match.
                  if(C[x] < O[x] && (best == -1 || C[x] < C[best])) best = x;
               if(best != -1)
                  AddOB(best, MathMin(O[best],C[best]), MathMax(O[best],C[best]), true, k, 0);
              }
            haveSWH = false; swhConsumed = true;
           }
         // MID-ARM: arm events + create AOBs (before the second break creates IFOBs)
         {
            int peek2 = ei;
            while(peek2 < g_evCount && g_ev[peek2].confirmIdx == k)
              {
               if(g_ev[peek2].kind == 0)
                 {
                  haveSWH = true; swhPrice = g_ev[peek2].price; swhIdx = g_ev[peek2].swingIdx;
                  // Bearish AOB: SWH just confirmed while a downtrend was in
                  // effect -- runs regardless of this candle's own body
                  // direction, so it isn't missed like OB near 2026.06.24.
                  TryBearishAOB(prevRegime, aobSWLidx, g_ev[peek2].swingIdx, g_ev[peek2].price,
                                O, H, L, C, Time, k, n);
                 }
               else
                 {
                  haveSWL = true; swlPrice = g_ev[peek2].price; swlIdx = g_ev[peek2].swingIdx;
                  // Bullish AOB: SWL just confirmed while an uptrend was in effect.
                  TryBullishAOB(prevRegime, aobSWHidx, g_ev[peek2].swingIdx, g_ev[peek2].price,
                                O, H, L, C, Time, k, n);
                 }
               peek2++;
              }
         }
         if(haveSWL && L[k] < swlPrice)
           {
            if(regime == 0)      regime = 2;
            else if(regime == 1) { regime = 2; AddMss(k, swlIdx, swlPrice, false); }
            // IFOB: bearish OB — scan from lastSWHidx through swlIdx to k
            if(lastSWHidx >= 0)
              {
               int lo = MathMin(MathMin(lastSWHidx, k), swlIdx);
               int hi = MathMax(MathMax(lastSWHidx, k), swlIdx);
               int best = -1;
               for(int x = lo; x <= hi; x++)
                  // rank by body extremity (close), not wick -- the zone
                  // itself is drawn open-to-close, so selection should match.
                  if(C[x] > O[x] && (best == -1 || C[x] > C[best])) best = x;
               if(best != -1)
                  AddOB(best, MathMin(O[best],C[best]), MathMax(O[best],C[best]), false, k, 0);
              }
            haveSWL = false; swlConsumed = true;
           }
        }
      else
        {
         // bullish: low happened first -> check the armed SWL break first
         if(haveSWL && L[k] < swlPrice)
           {
            if(regime == 0)      regime = 2;
            else if(regime == 1) { regime = 2; AddMss(k, swlIdx, swlPrice, false); }
            if(lastSWHidx >= 0)
              {
               int lo = MathMin(MathMin(lastSWHidx, k), swlIdx);
               int hi = MathMax(MathMax(lastSWHidx, k), swlIdx);
               int best = -1;
               for(int x = lo; x <= hi; x++)
                  // rank by body extremity (close), not wick -- the zone
                  // itself is drawn open-to-close, so selection should match.
                  if(C[x] > O[x] && (best == -1 || C[x] > C[best])) best = x;
               if(best != -1)
                  AddOB(best, MathMin(O[best],C[best]), MathMax(O[best],C[best]), false, k, 0);
              }
            haveSWL = false; swlConsumed = true;
           }
         // MID-ARM: arm events + create AOBs (before the second break creates IFOBs)
         {
            int peek2 = ei;
            while(peek2 < g_evCount && g_ev[peek2].confirmIdx == k)
              {
               if(g_ev[peek2].kind == 0)
                 {
                  haveSWH = true; swhPrice = g_ev[peek2].price; swhIdx = g_ev[peek2].swingIdx;
                  // Bearish AOB: SWH just confirmed while a downtrend was in effect.
                  TryBearishAOB(prevRegime, aobSWLidx, g_ev[peek2].swingIdx, g_ev[peek2].price,
                                O, H, L, C, Time, k, n);
                 }
               else
                 {
                  haveSWL = true; swlPrice = g_ev[peek2].price; swlIdx = g_ev[peek2].swingIdx;
                  // Bullish AOB: SWL just confirmed while an uptrend was in
                  // effect -- runs regardless of this candle's own body
                  // direction, so it isn't missed like OB near 2026.06.24.
                  TryBullishAOB(prevRegime, aobSWHidx, g_ev[peek2].swingIdx, g_ev[peek2].price,
                                O, H, L, C, Time, k, n);
                 }
               peek2++;
              }
         }
         if(haveSWH && H[k] > swhPrice)
           {
            if(regime == 0)      regime = 1;
            else if(regime == 2) { regime = 1; AddMss(k, swhIdx, swhPrice, true); }
            if(lastSWLidx >= 0)
              {
               int lo = MathMin(MathMin(lastSWLidx, k), swhIdx);
               int hi = MathMax(MathMax(lastSWLidx, k), swhIdx);
               int best = -1;
               for(int x = lo; x <= hi; x++)
                  // rank by body extremity (close), not wick -- the zone
                  // itself is drawn open-to-close, so selection should match.
                  if(C[x] < O[x] && (best == -1 || C[x] < C[best])) best = x;
               if(best != -1)
                  AddOB(best, MathMin(O[best],C[best]), MathMax(O[best],C[best]), true, k, 0);
              }
            haveSWH = false; swhConsumed = true;
           }
        }

      //--- STEP 2: arm swings + AOB creation + IFOB eligibility ---
      while(ei < g_evCount && g_ev[ei].confirmIdx == k)
        {
         if(g_ev[ei].kind == 0)
           {
            if(!swhConsumed)
              { haveSWH = true; swhPrice = g_ev[ei].price; swhIdx = g_ev[ei].swingIdx; }
            lastSWHidx = g_ev[ei].swingIdx;

            // IFOB eligibility: new SWH makes pending bullish IFOBs eligible
            for(int z = 0; z < g_obCount; z++)
               if(g_ob[z].bullish && g_ob[z].state == 0 && g_ob[z].eligibleK == -1 && k > g_ob[z].triggerK)
                  g_ob[z].eligibleK = k;
           }
         else
           {
            if(!swlConsumed)
              { haveSWL = true; swlPrice = g_ev[ei].price; swlIdx = g_ev[ei].swingIdx; }
            lastSWLidx = g_ev[ei].swingIdx;

            // IFOB eligibility: new SWL makes pending bearish IFOBs eligible
            for(int z = 0; z < g_obCount; z++)
               if(!g_ob[z].bullish && g_ob[z].state == 0 && g_ob[z].eligibleK == -1 && k > g_ob[z].triggerK)
                  g_ob[z].eligibleK = k;
           }
         ei++;
        }

      //--- STEP 3: OB lifecycle at this candle ---
      for(int z = 0; z < g_obCount; z++)
        {
         if(g_ob[z].state >= 3) continue; // SPENT

         double zb = g_ob[z].zb, zt = g_ob[z].zt;
         bool bull = g_ob[z].bullish;

         // IMPACT: first touch after eligible → SPENT
         if(g_ob[z].eligibleK != -1 && k >= g_ob[z].eligibleK)
           {
            if(H[k] >= zb && L[k] <= zt)
              { g_ob[z].state = 3; g_ob[z].stopK = k; continue; }
           }

         // STRANDING → OLD: IFOB or AOB can become OLD
         if((g_ob[z].state == 0 || g_ob[z].state == 1) && g_ob[z].eligibleK != -1)
           {
            for(int e2 = 0; e2 < g_evCount; e2++)
              {
               if(g_ev[e2].confirmIdx != k) continue;
               if(bull && g_ev[e2].kind == 1 && g_ev[e2].price > zt)
                 { g_ob[z].state = 2; break; }
               if(!bull && g_ev[e2].kind == 0 && g_ev[e2].price < zb)
                 { g_ob[z].state = 2; break; }
              }
           }
        }
     }

   //--- one-time summary ---
   static bool logged = false;
   if(!logged)
     {
      int nIFOB=0, nAOB=0, nOOB=0, nSpent=0;
      for(int z=0;z<g_obCount;z++)
        { if(g_ob[z].state==0) nIFOB++; else if(g_ob[z].state==1) nAOB++;
          else if(g_ob[z].state==2) nOOB++; else nSpent++; }
      PrintFormat("SwingMSS+OB: bars=%d SWH=%d SWL=%d MSS=%d OB=%d (ifob=%d aob=%d oob=%d spent=%d)",
                  n, g_shCount, g_slCount, g_mssCount, g_obCount, nIFOB, nAOB, nOOB, nSpent);
      logged = true;
     }
  }

//+------------------------------------------------------------------+
//| INDICATOR LIFECYCLE                                              |
//+------------------------------------------------------------------+
datetime g_displayFrom = 0;

int OnInit() { return INIT_SUCCEEDED; }

void OnDeinit(const int reason)
  { ObjectsDeleteAll(0, PFX); ChartRedraw(0); }

int OnCalculate(const int rates_total, const int prev_calculated,
                const datetime &time[], const double &open[],
                const double &high[], const double &low[],
                const double &close[], const long &tick_volume[],
                const long &volume[], const int &spread[])
  {
   int n = rates_total;
   if(n < 2) return rates_total;

   // REPLAY MODE: if date is set, truncate to only process bars up to that date
   if(InpReplayUpTo > 0)
     {
      int replayN = n;
      for(int r = 0; r < rates_total; r++)
         if(time[r] > InpReplayUpTo) { replayN = r; break; }
      n = replayN;
      if(n < 2) return rates_total;
     }

   // only rebuild when bar count changes (new bar opened)
   static int lastN = -1;
   if(prev_calculated > 0 && n == lastN) return rates_total;
   lastN = n;

   Process(open, high, low, close, time, n);

   int lastClosed = n - 2;
   g_displayFrom  = time[lastClosed]
                     - (datetime)(InpMonthsBack * PeriodSeconds(PERIOD_MN1));

   ObjectsDeleteAll(0, PFX);

   //--- draw swing HIGHS (blue up arrow, no text) ---
   for(int k = 0; k < g_shCount; k++)
     {
      int idx = g_shIdx[k];
      if(idx < 0 || idx >= n)        continue;
      if(time[idx] < g_displayFrom)  continue;

      string dn = PFX + "dot_" + IntegerToString(k);
      if(ObjectCreate(0, dn, OBJ_ARROW, 0, time[idx], high[idx]))
        {
         ObjectSetInteger(0, dn, OBJPROP_ARROWCODE, 241);   // up arrow
         ObjectSetInteger(0, dn, OBJPROP_COLOR, clrBlue);
         ObjectSetInteger(0, dn, OBJPROP_WIDTH, 2);
         ObjectSetInteger(0, dn, OBJPROP_ANCHOR, ANCHOR_BOTTOM);
        }
     }

   //--- draw swing LOWS (black down arrow, no text) ---
   for(int q = 0; q < g_slCount; q++)
     {
      int idx = g_slIdx[q];
      if(idx < 0 || idx >= n)        continue;
      if(time[idx] < g_displayFrom)  continue;

      string dn = PFX + "ldot_" + IntegerToString(q);
      if(ObjectCreate(0, dn, OBJ_ARROW, 0, time[idx], low[idx]))
        {
         ObjectSetInteger(0, dn, OBJPROP_ARROWCODE, 242);   // down arrow
         ObjectSetInteger(0, dn, OBJPROP_COLOR, clrBlack);
         ObjectSetInteger(0, dn, OBJPROP_WIDTH, 2);
         ObjectSetInteger(0, dn, OBJPROP_ANCHOR, ANCHOR_TOP);
        }
     }

   //--- draw MSS flips at the BROKEN swing point's location ---
   for(int m = 0; m < g_mssCount; m++)
     {
      int bi = g_mss[m].brokenIdx;
      if(bi < 0 || bi >= n)           continue;
      if(time[bi] < g_displayFrom)    continue;

      bool up = g_mss[m].toUp;
      double yPos = up ? high[bi] : low[bi];
      ENUM_ANCHOR_POINT anc = up ? ANCHOR_BOTTOM : ANCHOR_TOP;

      string mn = PFX + "mss_" + IntegerToString(m);
      if(ObjectCreate(0, mn, OBJ_ARROW, 0, time[bi], yPos))
        {
         ObjectSetInteger(0, mn, OBJPROP_ARROWCODE, 251);
         ObjectSetInteger(0, mn, OBJPROP_COLOR, up ? clrBlue : clrBlack);
         ObjectSetInteger(0, mn, OBJPROP_WIDTH, 2);
         ObjectSetInteger(0, mn, OBJPROP_ANCHOR, anc);
        }
     }

   //--- draw OB zones ---
   // IFOB bullish=blue, IFOB bearish=black, AOB=green, OOB=red, SPENT=stopped
   datetime extT = time[n-1] + (datetime)(6 * PeriodSeconds(PERIOD_MN1));
   static string stateName[4] = {"IFOB","AOB","OOB","SPENT"};
   for(int z = 0; z < g_obCount; z++)
     {
      // draw + diagnose the last 12 OBs (both share this same filter, so
      // widening it here extends diagnostics too -- no separate cutoff)
      if(z < g_obCount - 12) continue;
      int idx = g_ob[z].candle;
      if(idx < 0 || idx >= n) continue;

      datetime rightT = (g_ob[z].stopK != -1 && g_ob[z].stopK < n) ? time[g_ob[z].stopK] : extT;
      color col;
      int drawState = (g_ob[z].state == 3) ? g_ob[z].origState : g_ob[z].state;
      switch(drawState)
        {
         case 0: col = g_ob[z].bullish ? clrBlue : clrBlack; break;  // IFOB
         case 1: col = clrGreen; break;                                // AOB
         case 2: col = clrRed; break;                                  // OOB
         default: col = g_ob[z].bullish ? clrBlue : clrBlack; break;
        }

      // DIAG: identify each drawn OB by its position counted from the end
      // (#1 = most recent) so specific OBs can be cross-checked by date.
      PrintFormat("OB#%d (from end)  date=%s  bull=%d  state=%s  orig=%s  zb=%.5f zt=%.5f  eligibleK=%d(%s)  stopK=%d",
                  g_obCount - z, TimeToString(time[idx], TIME_DATE),
                  g_ob[z].bullish, stateName[g_ob[z].state], stateName[g_ob[z].origState],
                  g_ob[z].zb, g_ob[z].zt,
                  g_ob[z].eligibleK, (g_ob[z].eligibleK >= 0 && g_ob[z].eligibleK < n) ? TimeToString(time[g_ob[z].eligibleK], TIME_DATE) : "-",
                  g_ob[z].stopK);

      // AUDIT: independently re-scan raw price/swing data for this OB,
      // regardless of what state the engine currently holds, so a
      // discrepancy against the engine's own state is visible directly.
      if(g_ob[z].eligibleK != -1)
        {
         int auditImpactK = -1, auditStrandK = -1;
         for(int kk = g_ob[z].eligibleK; kk < n && auditImpactK == -1; kk++)
            if(high[kk] >= g_ob[z].zb && low[kk] <= g_ob[z].zt) auditImpactK = kk;
         for(int e2 = 0; e2 < g_evCount; e2++)
           {
            if(g_ev[e2].confirmIdx < g_ob[z].eligibleK) continue;
            if(g_ob[z].bullish && g_ev[e2].kind == 1 && g_ev[e2].price > g_ob[z].zt)
              { auditStrandK = g_ev[e2].confirmIdx; break; }
            if(!g_ob[z].bullish && g_ev[e2].kind == 0 && g_ev[e2].price < g_ob[z].zb)
              { auditStrandK = g_ev[e2].confirmIdx; break; }
           }
         PrintFormat("OB#%d AUDIT: firstImpact=%s  firstStrand=%s  (engine state=%s stopK=%d)",
                     g_obCount - z,
                     (auditImpactK!=-1?TimeToString(time[auditImpactK], TIME_DATE):"-"),
                     (auditStrandK!=-1?TimeToString(time[auditStrandK], TIME_DATE):"-"),
                     stateName[g_ob[z].state], g_ob[z].stopK);
        }

      string rn = PFX + "ob_" + IntegerToString(z);
      if(ObjectCreate(0, rn, OBJ_RECTANGLE, 0, time[idx], g_ob[z].zb, rightT, g_ob[z].zt))
        {
         ObjectSetInteger(0, rn, OBJPROP_COLOR, col);
         ObjectSetInteger(0, rn, OBJPROP_FILL, false);   // hollow
         ObjectSetInteger(0, rn, OBJPROP_BACK, true);
         ObjectSetInteger(0, rn, OBJPROP_WIDTH, 1);      // thin border
        }
     }

   ChartRedraw(0);
   return rates_total;
  }
//+------------------------------------------------------------------+
