//+------------------------------------------------------------------+
//|                                        ICT_Swings_MSS_FVG.mq5    |
//|  Visualization-only indicator: swing highs/lows, MSS, and FVGs   |
//|  (IFVG/AFVG/AIFVG/OFVG/spent), single timeframe -- whatever chart |
//|  it's attached to. No OB, no trading -- pure visual verification. |
//|                                                                    |
//|  Same proven swing/regime engine as the rest of this project.     |
//|  FVG creation mirrors OB's exactly (same trigger moments, same     |
//|  range-widening, same straddle guard on AFVG only) EXCEPT: every   |
//|  qualifying 3-candle gap in a leg is marked, not just one best     |
//|  candle -- so a single leg can produce several FVGs where it       |
//|  would only ever produce one OB.                                   |
//+------------------------------------------------------------------+
#property indicator_chart_window
#property indicator_plots 0
#property strict

input datetime InpDisplayFrom  = 0;           // 0 = show everything loaded
input color    InpSwingHighColor = clrOrangeRed;
input color    InpSwingLowColor  = clrDodgerBlue;
input color    InpMSSColor       = clrYellow;
input color    InpIFVGColor      = clrGold;
input color    InpAFVGColor      = clrOrange;
input color    InpAIFVGColor     = clrDarkOrange;
input color    InpOFVGColor      = clrDimGray;
input color    InpSpentColor     = clrPurple;

const string PFX = "ICTFVG_";

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

//--- MSS flips -- only genuine reversals (1<->2), NOT the initial warmup
//--- establishment (0->1 or 0->2), matching the proven convention.
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

//--- FVG zones. state: 0=IFVG, 1=AFVG, 2=OFVG(stranded), 3=spent(invalidated), 4=AIFVG
struct FvgZone
  {
   int      candle;      // left-edge candle -- first of the 3-candle gap
   double   zb, zt;
   bool     bullish;
   int      triggerK;
   int      eligibleK;   // -1 = not yet eligible (only matters for IFVG, state 0)
   int      resolvedK;   // -1 = still live; else the candle where it invalidated/stranded
   int      state;
   int      origState;   // classification for stranding direction (0/4 = IFVG-style, 1 = AFVG-style)
  };
FvgZone g_fvg[];
int     g_fvgCount = 0;

int AddFvg(int candle, double zb, double zt, bool bull, int triggerK, int state)
  {
   ArrayResize(g_fvg, g_fvgCount + 1);
   g_fvg[g_fvgCount].candle    = candle;
   g_fvg[g_fvgCount].zb        = zb;
   g_fvg[g_fvgCount].zt        = zt;
   g_fvg[g_fvgCount].bullish   = bull;
   g_fvg[g_fvgCount].triggerK  = triggerK;
   g_fvg[g_fvgCount].eligibleK = (state == 1 || state == 4) ? triggerK : -1;
   g_fvg[g_fvgCount].resolvedK = -1;
   g_fvg[g_fvgCount].state     = state;
   g_fvg[g_fvgCount].origState = state;
   g_fvgCount++;
   return g_fvgCount - 1;
  }

// Scans (lo..hi) for every qualifying 3-candle gap in the given direction and
// marks ALL of them -- unlike OB's single-best-candle pick. straddlePrice
// mirrors the OB straddle guard (only used where OB applies it: AFVG).
void ScanFvgs(const double &H[], const double &L[], int n, int lo, int hi, bool bullish,
              int triggerK, int state, bool hasStraddle, double straddlePrice)
  {
   lo = MathMax(lo, 0);
   int limit = MathMin(hi, n - 3);
   for(int i = lo; i <= limit; i++)
     {
      if(bullish)
        {
         if(L[i + 2] > H[i])
           {
            if(hasStraddle && H[i] <= straddlePrice) continue; // straddle guard
            AddFvg(i, H[i], L[i + 2], true, triggerK, state);
           }
        }
      else
        {
         if(H[i + 2] < L[i])
           {
            if(hasStraddle && L[i] >= straddlePrice) continue; // straddle guard
            AddFvg(i, H[i + 2], L[i], false, triggerK, state);
           }
        }
     }
  }

// rank by body extremity (close), not wick -- used only to locate the swing's
// eligibility arm point via the same range math OB uses, FVG needs no pick itself
int PickLowestBearish(const double &O[], const double &C[], int lo, int hi)
  {
   int best = -1;
   for(int x = lo; x <= hi; x++)
      if(C[x] < O[x] && (best == -1 || C[x] < C[best])) best = x;
   return best;
  }
int PickHighestBullish(const double &O[], const double &C[], int lo, int hi)
  {
   int best = -1;
   for(int x = lo; x <= hi; x++)
      if(C[x] > O[x] && (best == -1 || C[x] > C[best])) best = x;
   return best;
  }

bool   g_haveSWH; double g_swhPrice; int g_swhIdx;
bool   g_haveSWL; double g_swlPrice; int g_swlIdx;
int    g_regime;        // 0 warmup, 1 up, 2 down
int    g_lastSWHidx, g_lastSWLidx;

// pending AIFVG lists -- "mark all" means a single leg can produce several
// AIFVGs at once, so (unlike OB's single pendingIdx) we need a LIST, and
// convert every entry in it together when the armed swing is exceeded.
int    g_pendingBullAifvg[]; int g_pendingBullAifvgCount;
int    g_pendingBearAifvg[]; int g_pendingBearAifvgCount;

void PendingClear(int &arr[], int &cnt) { cnt = 0; ArrayResize(arr, 0); }
void PendingAdd(int &arr[], int &cnt, int idx) { ArrayResize(arr, cnt + 1); arr[cnt] = idx; cnt++; }
void PendingConvertAll(int &arr[], int &cnt)
  {
   for(int i = 0; i < cnt; i++)
     {
      int idx = arr[i];
      g_fvg[idx].state     = 0;
      g_fvg[idx].origState = 0;
     }
   PendingClear(arr, cnt);
  }

//+------------------------------------------------------------------+
//| Full reprocess from scratch -- same proven pattern as the rest of |
//| this project (simpler and more reliable than incremental state).  |
//+------------------------------------------------------------------+
void Process(const double &O[], const double &H[], const double &L[], const double &C[], int n)
  {
   g_evCount = 0; ArrayResize(g_ev, 0);
   g_mssCount = 0; ArrayResize(g_mss, 0);
   g_fvgCount = 0; ArrayResize(g_fvg, 0);
   g_haveSWH = false; g_swhPrice = 0; g_swhIdx = 0;
   g_haveSWL = false; g_swlPrice = 0; g_swlIdx = 0;
   g_regime = 0; g_lastSWHidx = -1; g_lastSWLidx = -1;
   PendingClear(g_pendingBullAifvg, g_pendingBullAifvgCount);
   PendingClear(g_pendingBearAifvg, g_pendingBearAifvgCount);

   //--- swing detection (dual-candle aware, alternation-blocked) ---
   int peakIdx = 0, troughIdx = 0;
   for(int i = 1; i < n; i++)
     {
      bool bullish        = (C[i] >= O[i]);
      bool breaksPrevHigh = (H[i] > H[i - 1]);
      bool breaksPrevLow  = (L[i] < L[i - 1]);
      bool dualAction      = (breaksPrevHigh && breaksPrevLow);

      bool prevDual = false;
      if(g_evCount >= 2)
        {
         bool diffKinds     = (g_ev[g_evCount - 1].kind != g_ev[g_evCount - 2].kind);
         bool sameConfirm   = (g_ev[g_evCount - 1].confirmIdx == g_ev[g_evCount - 2].confirmIdx);
         bool wasLastCandle = (g_ev[g_evCount - 1].confirmIdx == i - 1);
         prevDual = diffKinds && sameConfirm && wasLastCandle;
        }
      bool blockPostDual = (prevDual && !dualAction);

      if(!bullish)
        {
         if(H[i] > H[peakIdx]) peakIdx = i;
         if(breaksPrevHigh)
           {
            bool lastWasLow = (g_evCount > 0 && g_ev[g_evCount - 1].kind == 1);
            if(!lastWasLow && !blockPostDual)
              { AddEv(i, 1, troughIdx, L[troughIdx]); peakIdx = i; }
           }
         if(L[i] < L[troughIdx]) troughIdx = i;
         if(breaksPrevLow)
           {
            bool lastWasHigh = (g_evCount > 0 && g_ev[g_evCount - 1].kind == 0);
            if(!lastWasHigh && !blockPostDual)
              { AddEv(i, 0, peakIdx, H[peakIdx]); troughIdx = i; }
           }
        }
      else
        {
         if(L[i] < L[troughIdx]) troughIdx = i;
         if(breaksPrevLow)
           {
            bool lastWasHigh = (g_evCount > 0 && g_ev[g_evCount - 1].kind == 0);
            if(!lastWasHigh && !blockPostDual)
              { AddEv(i, 0, peakIdx, H[peakIdx]); troughIdx = i; }
           }
         if(H[i] > H[peakIdx]) peakIdx = i;
         if(breaksPrevHigh)
           {
            bool lastWasLow = (g_evCount > 0 && g_ev[g_evCount - 1].kind == 1);
            if(!lastWasLow && !blockPostDual)
              { AddEv(i, 1, troughIdx, L[troughIdx]); peakIdx = i; }
           }
        }
     }

   //--- regime / MSS / FVG engine ---
   int ei = 0;
   for(int k = 0; k < n; k++)
     {
      {
       int peek = ei;
       while(peek < g_evCount && g_ev[peek].confirmIdx == k)
         {
          if(g_ev[peek].kind == 0) g_lastSWHidx = g_ev[peek].swingIdx;
          else                     g_lastSWLidx = g_ev[peek].swingIdx;
          peek++;
         }
      }
      int prevRegime = g_regime;
      bool swhConsumed = false, swlConsumed = false;
      int aobSWHidx = g_swhIdx, aobSWLidx = g_swlIdx;

      bool kBullish = (C[k] >= O[k]);
      if(!kBullish)
        {
         if(g_haveSWH && H[k] > g_swhPrice)
           {
            if(g_regime == 0)      g_regime = 1;
            else if(g_regime == 2) { g_regime = 1; AddMss(k, g_swhIdx, g_swhPrice, true); }
            if(g_pendingBullAifvgCount > 0)
               PendingConvertAll(g_pendingBullAifvg, g_pendingBullAifvgCount);
            else if(g_lastSWLidx >= 0)
              {
               int lo = MathMin(MathMin(g_lastSWLidx, k), g_swhIdx);
               int hi = MathMax(MathMax(g_lastSWLidx, k), g_swhIdx);
               ScanFvgs(H, L, n, lo, hi, true, k, 0, false, 0);
              }
            g_haveSWH = false; swhConsumed = true;
           }
         {
          int peek2 = ei;
          while(peek2 < g_evCount && g_ev[peek2].confirmIdx == k)
            {
             if(g_ev[peek2].kind == 0)
               {
                g_haveSWH = true; g_swhPrice = g_ev[peek2].price; g_swhIdx = g_ev[peek2].swingIdx;
                PendingClear(g_pendingBullAifvg, g_pendingBullAifvgCount);
                // AFVG (retracement leg confirming, no MSS)
                {
                 int lo = MathMax(0, MathMin(aobSWLidx - 1, g_ev[peek2].swingIdx));
                 int hi = MathMax(aobSWLidx - 1, g_ev[peek2].swingIdx);
                 if(prevRegime == 2 && aobSWLidx >= 0)
                    ScanFvgs(H, L, n, lo, hi, false, k, 1, true, g_ev[peek2].price);
                }
                // AIFVG (same trigger, IFVG-style range, pending until armed swing exceeded)
                if(prevRegime == 2 && g_haveSWL && aobSWLidx >= 0 && g_lastSWHidx >= 0)
                  {
                   int lo2 = MathMax(0, MathMin(MathMin(g_lastSWHidx, g_ev[peek2].swingIdx), aobSWLidx - 1));
                   int hi2 = MathMax(MathMax(g_lastSWHidx, g_ev[peek2].swingIdx), aobSWLidx - 1);
                   int before = g_fvgCount;
                   ScanFvgs(H, L, n, lo2, hi2, false, k, 4, false, 0);
                   for(int z = before; z < g_fvgCount; z++)
                      PendingAdd(g_pendingBearAifvg, g_pendingBearAifvgCount, z);
                  }
               }
             else
               {
                g_haveSWL = true; g_swlPrice = g_ev[peek2].price; g_swlIdx = g_ev[peek2].swingIdx;
                PendingClear(g_pendingBearAifvg, g_pendingBearAifvgCount);
                {
                 int lo = MathMax(0, MathMin(aobSWHidx - 1, g_ev[peek2].swingIdx));
                 int hi = MathMax(aobSWHidx - 1, g_ev[peek2].swingIdx);
                 if(prevRegime == 1 && aobSWHidx >= 0)
                    ScanFvgs(H, L, n, lo, hi, true, k, 1, true, g_ev[peek2].price);
                }
                if(prevRegime == 1 && g_haveSWH && aobSWHidx >= 0 && g_lastSWLidx >= 0)
                  {
                   int lo2 = MathMax(0, MathMin(MathMin(g_lastSWLidx, g_ev[peek2].swingIdx), aobSWHidx - 1));
                   int hi2 = MathMax(MathMax(g_lastSWLidx, g_ev[peek2].swingIdx), aobSWHidx - 1);
                   int before = g_fvgCount;
                   ScanFvgs(H, L, n, lo2, hi2, true, k, 4, false, 0);
                   for(int z = before; z < g_fvgCount; z++)
                      PendingAdd(g_pendingBullAifvg, g_pendingBullAifvgCount, z);
                  }
               }
             peek2++;
            }
         }
         if(g_haveSWL && L[k] < g_swlPrice)
           {
            if(g_regime == 0)      g_regime = 2;
            else if(g_regime == 1) { g_regime = 2; AddMss(k, g_swlIdx, g_swlPrice, false); }
            if(g_pendingBearAifvgCount > 0)
               PendingConvertAll(g_pendingBearAifvg, g_pendingBearAifvgCount);
            else if(g_lastSWHidx >= 0)
              {
               int lo = MathMin(MathMin(g_lastSWHidx, k), g_swlIdx);
               int hi = MathMax(MathMax(g_lastSWHidx, k), g_swlIdx);
               ScanFvgs(H, L, n, lo, hi, false, k, 0, false, 0);
              }
            g_haveSWL = false; swlConsumed = true;
           }
        }
      else
        {
         if(g_haveSWL && L[k] < g_swlPrice)
           {
            if(g_regime == 0)      g_regime = 2;
            else if(g_regime == 1) { g_regime = 2; AddMss(k, g_swlIdx, g_swlPrice, false); }
            if(g_pendingBearAifvgCount > 0)
               PendingConvertAll(g_pendingBearAifvg, g_pendingBearAifvgCount);
            else if(g_lastSWHidx >= 0)
              {
               int lo = MathMin(MathMin(g_lastSWHidx, k), g_swlIdx);
               int hi = MathMax(MathMax(g_lastSWHidx, k), g_swlIdx);
               ScanFvgs(H, L, n, lo, hi, false, k, 0, false, 0);
              }
            g_haveSWL = false; swlConsumed = true;
           }
         {
          int peek2 = ei;
          while(peek2 < g_evCount && g_ev[peek2].confirmIdx == k)
            {
             if(g_ev[peek2].kind == 0)
               {
                g_haveSWH = true; g_swhPrice = g_ev[peek2].price; g_swhIdx = g_ev[peek2].swingIdx;
                PendingClear(g_pendingBullAifvg, g_pendingBullAifvgCount);
                {
                 int lo = MathMax(0, MathMin(aobSWLidx - 1, g_ev[peek2].swingIdx));
                 int hi = MathMax(aobSWLidx - 1, g_ev[peek2].swingIdx);
                 if(prevRegime == 2 && aobSWLidx >= 0)
                    ScanFvgs(H, L, n, lo, hi, false, k, 1, true, g_ev[peek2].price);
                }
                if(prevRegime == 2 && g_haveSWL && aobSWLidx >= 0 && g_lastSWHidx >= 0)
                  {
                   int lo2 = MathMax(0, MathMin(MathMin(g_lastSWHidx, g_ev[peek2].swingIdx), aobSWLidx - 1));
                   int hi2 = MathMax(MathMax(g_lastSWHidx, g_ev[peek2].swingIdx), aobSWLidx - 1);
                   int before = g_fvgCount;
                   ScanFvgs(H, L, n, lo2, hi2, false, k, 4, false, 0);
                   for(int z = before; z < g_fvgCount; z++)
                      PendingAdd(g_pendingBearAifvg, g_pendingBearAifvgCount, z);
                  }
               }
             else
               {
                g_haveSWL = true; g_swlPrice = g_ev[peek2].price; g_swlIdx = g_ev[peek2].swingIdx;
                PendingClear(g_pendingBearAifvg, g_pendingBearAifvgCount);
                {
                 int lo = MathMax(0, MathMin(aobSWHidx - 1, g_ev[peek2].swingIdx));
                 int hi = MathMax(aobSWHidx - 1, g_ev[peek2].swingIdx);
                 if(prevRegime == 1 && aobSWHidx >= 0)
                    ScanFvgs(H, L, n, lo, hi, true, k, 1, true, g_ev[peek2].price);
                }
                if(prevRegime == 1 && g_haveSWH && aobSWHidx >= 0 && g_lastSWLidx >= 0)
                  {
                   int lo2 = MathMax(0, MathMin(MathMin(g_lastSWLidx, g_ev[peek2].swingIdx), aobSWHidx - 1));
                   int hi2 = MathMax(MathMax(g_lastSWLidx, g_ev[peek2].swingIdx), aobSWHidx - 1);
                   int before = g_fvgCount;
                   ScanFvgs(H, L, n, lo2, hi2, true, k, 4, false, 0);
                   for(int z = before; z < g_fvgCount; z++)
                      PendingAdd(g_pendingBullAifvg, g_pendingBullAifvgCount, z);
                  }
               }
             peek2++;
            }
         }
         if(g_haveSWH && H[k] > g_swhPrice)
           {
            if(g_regime == 0)      g_regime = 1;
            else if(g_regime == 2) { g_regime = 1; AddMss(k, g_swhIdx, g_swhPrice, true); }
            if(g_pendingBullAifvgCount > 0)
               PendingConvertAll(g_pendingBullAifvg, g_pendingBullAifvgCount);
            else if(g_lastSWLidx >= 0)
              {
               int lo = MathMin(MathMin(g_lastSWLidx, k), g_swhIdx);
               int hi = MathMax(MathMax(g_lastSWLidx, k), g_swhIdx);
               ScanFvgs(H, L, n, lo, hi, true, k, 0, false, 0);
              }
            g_haveSWH = false; swhConsumed = true;
           }
        }

      //--- arm + eligibility (IFVG only -- AFVG/AIFVG are eligible immediately) ---
      while(ei < g_evCount && g_ev[ei].confirmIdx == k)
        {
         if(g_ev[ei].kind == 0)
           {
            if(!swhConsumed) { g_haveSWH = true; g_swhPrice = g_ev[ei].price; g_swhIdx = g_ev[ei].swingIdx; }
            g_lastSWHidx = g_ev[ei].swingIdx;
            for(int z = 0; z < g_fvgCount; z++)
               if(g_fvg[z].bullish && g_fvg[z].state == 0 && g_fvg[z].eligibleK == -1 && k > g_fvg[z].triggerK)
                  g_fvg[z].eligibleK = k;
           }
         else
           {
            if(!swlConsumed) { g_haveSWL = true; g_swlPrice = g_ev[ei].price; g_swlIdx = g_ev[ei].swingIdx; }
            g_lastSWLidx = g_ev[ei].swingIdx;
            for(int z = 0; z < g_fvgCount; z++)
               if(!g_fvg[z].bullish && g_fvg[z].state == 0 && g_fvg[z].eligibleK == -1 && k > g_fvg[z].triggerK)
                  g_fvg[z].eligibleK = k;
           }
         ei++;
        }

      //--- lifecycle: invalidation (body closes fully through the far edge)  ---
      //--- takes priority, exactly mirroring how OB's "impacted" check runs   ---
      //--- before its stranding check; then structural stranding (OFVG),      ---
      //--- same swing-based rule as OOB.                                      ---
      for(int z = 0; z < g_fvgCount; z++)
        {
         if(g_fvg[z].state == 3 || g_fvg[z].state == 2) continue;
         if(g_fvg[z].eligibleK == -1 || k < g_fvg[z].eligibleK) continue;
         double zb = g_fvg[z].zb, zt = g_fvg[z].zt; bool bull = g_fvg[z].bullish;

         bool invalidated = bull ? (C[k] < zb) : (C[k] > zt);
         if(invalidated)
           {
            g_fvg[z].state = 3; g_fvg[z].resolvedK = k;
            continue;
           }

         bool isIFVG = (g_fvg[z].origState != 1);
         for(int e2 = 0; e2 < g_evCount; e2++)
           {
            if(g_ev[e2].confirmIdx != k) continue;
            if(isIFVG)
              {
               if(bull && g_ev[e2].kind == 1 && g_ev[e2].price > zt) { g_fvg[z].state = 2; g_fvg[z].resolvedK = k; }
               if(!bull && g_ev[e2].kind == 0 && g_ev[e2].price < zb) { g_fvg[z].state = 2; g_fvg[z].resolvedK = k; }
              }
            else
              {
               if(bull && g_ev[e2].kind == 0 && g_ev[e2].price < zb) { g_fvg[z].state = 2; g_fvg[z].resolvedK = k; }
               if(!bull && g_ev[e2].kind == 1 && g_ev[e2].price > zt) { g_fvg[z].state = 2; g_fvg[z].resolvedK = k; }
              }
           }
        }
     }
  }

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

   static int lastN = -1;
   if(prev_calculated > 0 && n == lastN) return rates_total;
   lastN = n;

   Process(open, high, low, close, n);

   datetime displayFrom = InpDisplayFrom;
   int lastClosed = n - 2;

   ObjectsDeleteAll(0, PFX);

   //--- swing highs ---
   for(int e = 0; e < g_evCount; e++)
     {
      if(g_ev[e].kind != 0) continue;
      int idx = g_ev[e].swingIdx;
      if(idx < 0 || idx >= n) continue;
      if(displayFrom > 0 && time[idx] < displayFrom) continue;
      string dn = PFX + "sh_" + IntegerToString(e);
      if(ObjectCreate(0, dn, OBJ_ARROW, 0, time[idx], high[idx]))
        {
         ObjectSetInteger(0, dn, OBJPROP_ARROWCODE, 241);
         ObjectSetInteger(0, dn, OBJPROP_COLOR, InpSwingHighColor);
         ObjectSetInteger(0, dn, OBJPROP_WIDTH, 2);
         ObjectSetInteger(0, dn, OBJPROP_ANCHOR, ANCHOR_BOTTOM);
        }
     }

   //--- swing lows ---
   for(int e = 0; e < g_evCount; e++)
     {
      if(g_ev[e].kind != 1) continue;
      int idx = g_ev[e].swingIdx;
      if(idx < 0 || idx >= n) continue;
      if(displayFrom > 0 && time[idx] < displayFrom) continue;
      string dn = PFX + "sl_" + IntegerToString(e);
      if(ObjectCreate(0, dn, OBJ_ARROW, 0, time[idx], low[idx]))
        {
         ObjectSetInteger(0, dn, OBJPROP_ARROWCODE, 242);
         ObjectSetInteger(0, dn, OBJPROP_COLOR, InpSwingLowColor);
         ObjectSetInteger(0, dn, OBJPROP_WIDTH, 2);
         ObjectSetInteger(0, dn, OBJPROP_ANCHOR, ANCHOR_TOP);
        }
     }

   //--- MSS flips, drawn at the broken swing point ---
   for(int m = 0; m < g_mssCount; m++)
     {
      int bi = g_mss[m].brokenIdx;
      if(bi < 0 || bi >= n) continue;
      if(displayFrom > 0 && time[bi] < displayFrom) continue;
      bool up = g_mss[m].toUp;
      double yPos = up ? high[bi] : low[bi];
      string mn = PFX + "mss_" + IntegerToString(m);
      if(ObjectCreate(0, mn, OBJ_TEXT, 0, time[bi], yPos))
        {
         ObjectSetString(0, mn, OBJPROP_TEXT, "MSS");
         ObjectSetInteger(0, mn, OBJPROP_COLOR, InpMSSColor);
         ObjectSetInteger(0, mn, OBJPROP_FONTSIZE, 8);
         ObjectSetInteger(0, mn, OBJPROP_ANCHOR, up ? ANCHOR_BOTTOM : ANCHOR_TOP);
        }
     }

   //--- FVG zones ---
   datetime extT = time[n - 1];
   for(int z = 0; z < g_fvgCount; z++)
     {
      int idx = g_fvg[z].candle;
      if(idx < 0 || idx >= n) continue;
      if(displayFrom > 0 && time[idx] < displayFrom) continue;

      bool stillLive = (g_fvg[z].state == 0 || g_fvg[z].state == 1 || g_fvg[z].state == 4);
      datetime rightT = stillLive ? extT : ((g_fvg[z].resolvedK != -1 && g_fvg[z].resolvedK < n) ? time[g_fvg[z].resolvedK] : time[idx]);

      color col;
      string label;
      if(g_fvg[z].state == 2) { col = InpOFVGColor; label = "OFVG"; }
      else if(g_fvg[z].state == 3)
        {
         col = InpSpentColor;
         label = (g_fvg[z].origState == 1 ? "AFVG" : g_fvg[z].origState == 4 ? "AIFVG" : "IFVG") + " (inv)";
        }
      else if(g_fvg[z].origState == 1) { col = InpAFVGColor;  label = "AFVG"; }
      else if(g_fvg[z].origState == 4) { col = InpAIFVGColor; label = "AIFVG"; }
      else                             { col = InpIFVGColor;  label = "IFVG"; }

      string rn = PFX + "fvg_" + IntegerToString(z);
      if(ObjectCreate(0, rn, OBJ_RECTANGLE, 0, time[idx], g_fvg[z].zb, rightT, g_fvg[z].zt))
        {
         ObjectSetInteger(0, rn, OBJPROP_COLOR, col);
         ObjectSetInteger(0, rn, OBJPROP_FILL, false);   // hollow
         ObjectSetInteger(0, rn, OBJPROP_BACK, true);
         ObjectSetInteger(0, rn, OBJPROP_STYLE, STYLE_DASH); // dashed -- distinct from any OB indicator
        }
      string tn = PFX + "fvgtxt_" + IntegerToString(z);
      if(ObjectCreate(0, tn, OBJ_TEXT, 0, time[idx], g_fvg[z].bullish ? g_fvg[z].zb : g_fvg[z].zt))
        {
         ObjectSetString(0, tn, OBJPROP_TEXT, label);
         ObjectSetInteger(0, tn, OBJPROP_COLOR, col);
         ObjectSetInteger(0, tn, OBJPROP_FONTSIZE, 7);
        }
     }

   ChartRedraw(0);
   return rates_total;
  }
