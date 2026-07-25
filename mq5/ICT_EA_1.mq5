//+------------------------------------------------------------------+
//|                                                    ICT_EA_1.mq5  |
//|  Multi-timeframe ICT Order Block EA.                             |
//|                                                                    |
//|  Architecture: three independent instances of the SAME swing/MSS/ |
//|  OB engine built and proven in ICT_Full_OB_v24.mq5 (dual-candle   |
//|  swing detection, alternation rule, MSS, IFOB/AOB/AIFOB/OOB/SPENT,|
//|  body-superiority ranking, AOB/AIFOB range widening, mirrored     |
//|  stranding direction) -- one on Daily (bias + highest-conviction  |
//|  setups), one on H4 (continuation hunting once daily is used up), |
//|  one on H1 (entry timing: MSS/AOB formation, respect-check,       |
//|  execution).                                                      |
//|                                                                    |
//|  This is a first complete build of a very large, intricate spec -- |
//|  expect a test-and-refine cycle, same as the indicator before it. |
//+------------------------------------------------------------------+
#property strict
#include <Trade\Trade.mqh>

//================================ INPUTS ================================
input double InpRiskPercent      = 1.0;   // risk % of equity per trade
input double InpRR_Target        = 3.0;   // reward:risk target (take profit)
input double InpRR_BE            = 2.0;   // move SL to breakeven at this RR
input int    InpLondonStartHour  = 8;     // London session start (broker/server time)
input int    InpNewYorkStartHour = 13;    // New York session start (broker/server time)
input int    InpSessionWindowHrs = 2;     // trading window length from each session start
input int    InpDailyBars        = 800;   // daily bars to keep in the engine
input int    InpH4Bars           = 2000;  // H4 bars to keep in the engine
input int    InpH1Bars           = 4000;  // H1 bars to keep in the engine
input int    InpMaxWaitH1Bars    = 120;   // give up a stalled 1H watch/setup after this many hours
input ulong  InpMagic            = 202601;

CTrade trade;

//================================ ENGINE TYPES ================================
struct SwEv { int confirmIdx; int kind; int swingIdx; double price; }; // kind 0=high,1=low

// state: 0=IFOB, 1=AOB, 2=OOB, 3=SPENT, 4=AIFOB
struct ObZone
  {
   int      candle;     // index at creation time (internal engine use only)
   datetime t;           // candle time (external/cross-timeframe use)
   double   zb, zt;
   bool     bullish;
   int      triggerK;
   int      eligibleK;   // -1 = not yet eligible
   int      touchK;       // -1 = not yet touched; else the candle index of first Impact
   int      state;
   int      origState;   // classification for stranding direction (0/4 = IFOB-style, 1 = AOB-style)
  };

//+------------------------------------------------------------------+
//| COBEngine -- one instance per timeframe. Refresh() reprocesses    |
//| the full window from scratch each call (mirrors the indicator's   |
//| OnCalculate), which is the same proven logic, just parameterized. |
//+------------------------------------------------------------------+
class COBEngine
  {
public:
   string          m_sym;
   ENUM_TIMEFRAMES m_tf;
   int             m_bars;
   datetime        m_anchorTime; // fixed start of the processed window -- see Refresh()

   SwEv   ev[];
   int    evCount;
   ObZone ob[];
   int    obCount;

   bool   haveSWH; double swhPrice; int swhIdx;
   bool   haveSWL; double swlPrice; int swlIdx;
   int    regime;        // 0 warmup, 1 up, 2 down
   int    lastSWHidx, lastSWLidx;
   int    pendingBullAifobIdx, pendingBearAifobIdx;

   int    n;             // bars actually loaded on the last Refresh()
   double O[], H[], L[], C[];
   datetime Time[];

   void Init(string sym, ENUM_TIMEFRAMES tf, int bars)
     {
      m_sym = sym; m_tf = tf; m_bars = bars;
      evCount = 0; obCount = 0; n = 0;
      m_anchorTime = 0; // set lazily on first successful Refresh() -- see below
     }

   void AddEv(int confirmIdx, int kind, int swingIdx, double price)
     {
      ArrayResize(ev, evCount + 1);
      ev[evCount].confirmIdx = confirmIdx;
      ev[evCount].kind       = kind;
      ev[evCount].swingIdx   = swingIdx;
      ev[evCount].price      = price;
      evCount++;
     }

   int AddOB(int candle, double zb, double zt, bool bull, int triggerK, int state)
     {
      ArrayResize(ob, obCount + 1);
      ob[obCount].candle    = candle;
      ob[obCount].t         = Time[candle];
      ob[obCount].zb        = zb;
      ob[obCount].zt        = zt;
      ob[obCount].bullish   = bull;
      ob[obCount].triggerK  = triggerK;
      ob[obCount].eligibleK = (state == 1 || state == 4) ? triggerK : -1;
      ob[obCount].touchK    = -1;
      ob[obCount].state     = state;
      ob[obCount].origState = state;
      obCount++;
      return obCount - 1;
     }

   // rank by body extremity (close), not wick -- zones are drawn/measured open-to-close
   int PickLowestBearish(int lo, int hi)
     {
      int best = -1;
      for(int x = lo; x <= hi; x++)
         if(C[x] < O[x] && (best == -1 || C[x] < C[best])) best = x;
      return best;
     }
   int PickHighestBullish(int lo, int hi)
     {
      int best = -1;
      for(int x = lo; x <= hi; x++)
         if(C[x] > O[x] && (best == -1 || C[x] > C[best])) best = x;
      return best;
     }

   int TryBullishAOB(int prevRegime, int aobSWHidx, int newSwlIdx, double newSwlPrice, int k)
     {
      if(prevRegime != 1 || aobSWHidx < 0) return -1;
      int lo = MathMax(0, MathMin(aobSWHidx - 1, newSwlIdx));
      int hi = MathMax(aobSWHidx - 1, newSwlIdx);
      int best = PickHighestBullish(lo, hi);
      if(best == -1 || L[best] <= newSwlPrice) return -1; // straddle guard
      return AddOB(best, MathMin(O[best], C[best]), MathMax(O[best], C[best]), true, k, 1);
     }

   int TryBearishAOB(int prevRegime, int aobSWLidx, int newSwhIdx, double newSwhPrice, int k)
     {
      if(prevRegime != 2 || aobSWLidx < 0) return -1;
      int lo = MathMax(0, MathMin(aobSWLidx - 1, newSwhIdx));
      int hi = MathMax(aobSWLidx - 1, newSwhIdx);
      int best = PickLowestBearish(lo, hi);
      if(best == -1 || H[best] >= newSwhPrice) return -1; // straddle guard
      return AddOB(best, MathMin(O[best], C[best]), MathMax(O[best], C[best]), false, k, 1);
     }

   int TryBullishAIFOB(int prevRegime, bool haveSWH_, int swhIdx_, int lastSWLidx_, int newSwlIdx, int k)
     {
      if(prevRegime != 1 || !haveSWH_ || swhIdx_ < 0 || lastSWLidx_ < 0) return -1;
      int lo = MathMax(0, MathMin(MathMin(lastSWLidx_, newSwlIdx), swhIdx_ - 1));
      int hi = MathMax(MathMax(lastSWLidx_, newSwlIdx), swhIdx_ - 1);
      int best = PickLowestBearish(lo, hi);
      if(best == -1) return -1;
      return AddOB(best, MathMin(O[best], C[best]), MathMax(O[best], C[best]), true, k, 4);
     }

   int TryBearishAIFOB(int prevRegime, bool haveSWL_, int swlIdx_, int lastSWHidx_, int newSwhIdx, int k)
     {
      if(prevRegime != 2 || !haveSWL_ || swlIdx_ < 0 || lastSWHidx_ < 0) return -1;
      int lo = MathMax(0, MathMin(MathMin(lastSWHidx_, newSwhIdx), swlIdx_ - 1));
      int hi = MathMax(MathMax(lastSWHidx_, newSwhIdx), swlIdx_ - 1);
      int best = PickHighestBullish(lo, hi);
      if(best == -1) return -1;
      return AddOB(best, MathMin(O[best], C[best]), MathMax(O[best], C[best]), false, k, 4);
     }

   bool Refresh()
     {
      // The processed window MUST start at a fixed point in time and only ever
      // grow forward, never slide. Every EA-level global stores plain integer
      // indices into ev[]/ob[] across calls (g_activeDailyIdx, g_1hOBIdx,
      // g_active4hIdx, ...). If Refresh() re-fetched "the last m_bars ending
      // now" (a sliding window), the earliest bar would drop off every call,
      // and since swing detection is a sequential, state-dependent scan, that
      // single dropped bar can reshuffle the entire ev[]/ob[] count and
      // ordering on the very next call -- silently invalidating every index
      // held elsewhere, up to and including reading past the end of the
      // (now shorter) array. Anchoring the start once and only appending
      // forward guarantees an OB assigned index Q now keeps index Q forever.
      if(m_anchorTime == 0)
        {
         datetime a = iTime(m_sym, m_tf, m_bars - 1);
         if(a <= 0) return false; // history not ready yet -- retry on a later call
         m_anchorTime = a;
        }

      ArraySetAsSeries(O, false); ArraySetAsSeries(H, false);
      ArraySetAsSeries(L, false); ArraySetAsSeries(C, false);
      ArraySetAsSeries(Time, false);

      datetime stop = TimeCurrent() + PeriodSeconds(m_tf); // include the still-forming bar
      int got = CopyOpen(m_sym, m_tf, m_anchorTime, stop, O);
      if(got <= 1) return false;
      CopyHigh(m_sym, m_tf, m_anchorTime, stop, H);
      CopyLow(m_sym, m_tf, m_anchorTime, stop, L);
      CopyClose(m_sym, m_tf, m_anchorTime, stop, C);
      CopyTime(m_sym, m_tf, m_anchorTime, stop, Time);
      n = ArraySize(O);
      if(n < 2) return false;

      evCount = 0; ArrayResize(ev, 0);
      obCount = 0; ArrayResize(ob, 0);
      haveSWH = false; swhPrice = 0; swhIdx = 0;
      haveSWL = false; swlPrice = 0; swlIdx = 0;
      regime = 0; lastSWHidx = -1; lastSWLidx = -1;
      pendingBullAifobIdx = -1; pendingBearAifobIdx = -1;

      //--- swing detection (dual-candle aware, alternation-blocked) ---
      int peakIdx = 0, troughIdx = 0;
      for(int i = 1; i < n; i++)
        {
         bool bullish       = (C[i] >= O[i]);
         bool breaksPrevHigh = (H[i] > H[i - 1]);
         bool breaksPrevLow  = (L[i] < L[i - 1]);
         bool dualAction     = (breaksPrevHigh && breaksPrevLow);

         bool prevDual = false;
         if(evCount >= 2)
           {
            bool diffKinds     = (ev[evCount - 1].kind != ev[evCount - 2].kind);
            bool sameConfirm   = (ev[evCount - 1].confirmIdx == ev[evCount - 2].confirmIdx);
            bool wasLastCandle = (ev[evCount - 1].confirmIdx == i - 1);
            prevDual = diffKinds && sameConfirm && wasLastCandle;
           }
         bool blockPostDual = (prevDual && !dualAction);

         if(!bullish)
           {
            if(H[i] > H[peakIdx]) peakIdx = i;
            if(breaksPrevHigh)
              {
               bool lastWasLow = (evCount > 0 && ev[evCount - 1].kind == 1);
               if(!lastWasLow && !blockPostDual)
                 { AddEv(i, 1, troughIdx, L[troughIdx]); peakIdx = i; }
              }
            if(L[i] < L[troughIdx]) troughIdx = i;
            if(breaksPrevLow)
              {
               bool lastWasHigh = (evCount > 0 && ev[evCount - 1].kind == 0);
               if(!lastWasHigh && !blockPostDual)
                 { AddEv(i, 0, peakIdx, H[peakIdx]); troughIdx = i; }
              }
           }
         else
           {
            if(L[i] < L[troughIdx]) troughIdx = i;
            if(breaksPrevLow)
              {
               bool lastWasHigh = (evCount > 0 && ev[evCount - 1].kind == 0);
               if(!lastWasHigh && !blockPostDual)
                 { AddEv(i, 0, peakIdx, H[peakIdx]); troughIdx = i; }
              }
            if(H[i] > H[peakIdx]) peakIdx = i;
            if(breaksPrevHigh)
              {
               bool lastWasLow = (evCount > 0 && ev[evCount - 1].kind == 1);
               if(!lastWasLow && !blockPostDual)
                 { AddEv(i, 1, troughIdx, L[troughIdx]); peakIdx = i; }
              }
           }
        }

      for(int a = 0; a < evCount; a++)
         for(int b = a + 1; b < evCount; b++)
            if(ev[b].confirmIdx < ev[a].confirmIdx)
              { SwEv tmp = ev[a]; ev[a] = ev[b]; ev[b] = tmp; }

      //--- regime / MSS / OB engine ---
      int ei = 0;
      for(int k = 0; k < n; k++)
        {
         {
            int peek = ei;
            while(peek < evCount && ev[peek].confirmIdx == k)
              {
               if(ev[peek].kind == 0) lastSWHidx = ev[peek].swingIdx;
               else                   lastSWLidx = ev[peek].swingIdx;
               peek++;
              }
         }
         int prevRegime = regime;
         bool swhConsumed = false, swlConsumed = false;
         int aobSWHidx = swhIdx, aobSWLidx = swlIdx;

         bool kBullish = (C[k] >= O[k]);
         if(!kBullish)
           {
            if(haveSWH && H[k] > swhPrice)
              {
               if(regime == 0) regime = 1; else if(regime == 2) regime = 1;
               if(pendingBullAifobIdx != -1)
                 { ob[pendingBullAifobIdx].state = 0; ob[pendingBullAifobIdx].origState = 0; pendingBullAifobIdx = -1; }
               else if(lastSWLidx >= 0)
                 {
                  int lo = MathMin(MathMin(lastSWLidx, k), swhIdx);
                  int hi = MathMax(MathMax(lastSWLidx, k), swhIdx);
                  int best = PickLowestBearish(lo, hi);
                  if(best != -1) AddOB(best, MathMin(O[best],C[best]), MathMax(O[best],C[best]), true, k, 0);
                 }
               haveSWH = false; swhConsumed = true;
              }
            {
             int peek2 = ei;
             while(peek2 < evCount && ev[peek2].confirmIdx == k)
               {
                if(ev[peek2].kind == 0)
                  {
                   haveSWH = true; swhPrice = ev[peek2].price; swhIdx = ev[peek2].swingIdx;
                   pendingBullAifobIdx = -1;
                   TryBearishAOB(prevRegime, aobSWLidx, ev[peek2].swingIdx, ev[peek2].price, k);
                   if(pendingBearAifobIdx == -1)
                     {
                      int idx2 = TryBearishAIFOB(prevRegime, haveSWL, aobSWLidx, lastSWHidx, ev[peek2].swingIdx, k);
                      if(idx2 != -1) pendingBearAifobIdx = idx2;
                     }
                  }
                else
                  {
                   haveSWL = true; swlPrice = ev[peek2].price; swlIdx = ev[peek2].swingIdx;
                   pendingBearAifobIdx = -1;
                   TryBullishAOB(prevRegime, aobSWHidx, ev[peek2].swingIdx, ev[peek2].price, k);
                   if(pendingBullAifobIdx == -1)
                     {
                      int idx2 = TryBullishAIFOB(prevRegime, haveSWH, aobSWHidx, lastSWLidx, ev[peek2].swingIdx, k);
                      if(idx2 != -1) pendingBullAifobIdx = idx2;
                     }
                  }
                peek2++;
               }
            }
            if(haveSWL && L[k] < swlPrice)
              {
               if(regime == 0) regime = 2; else if(regime == 1) regime = 2;
               if(pendingBearAifobIdx != -1)
                 { ob[pendingBearAifobIdx].state = 0; ob[pendingBearAifobIdx].origState = 0; pendingBearAifobIdx = -1; }
               else if(lastSWHidx >= 0)
                 {
                  int lo = MathMin(MathMin(lastSWHidx, k), swlIdx);
                  int hi = MathMax(MathMax(lastSWHidx, k), swlIdx);
                  int best = PickHighestBullish(lo, hi);
                  if(best != -1) AddOB(best, MathMin(O[best],C[best]), MathMax(O[best],C[best]), false, k, 0);
                 }
               haveSWL = false; swlConsumed = true;
              }
           }
         else
           {
            if(haveSWL && L[k] < swlPrice)
              {
               if(regime == 0) regime = 2; else if(regime == 1) regime = 2;
               if(pendingBearAifobIdx != -1)
                 { ob[pendingBearAifobIdx].state = 0; ob[pendingBearAifobIdx].origState = 0; pendingBearAifobIdx = -1; }
               else if(lastSWHidx >= 0)
                 {
                  int lo = MathMin(MathMin(lastSWHidx, k), swlIdx);
                  int hi = MathMax(MathMax(lastSWHidx, k), swlIdx);
                  int best = PickHighestBullish(lo, hi);
                  if(best != -1) AddOB(best, MathMin(O[best],C[best]), MathMax(O[best],C[best]), false, k, 0);
                 }
               haveSWL = false; swlConsumed = true;
              }
            {
             int peek2 = ei;
             while(peek2 < evCount && ev[peek2].confirmIdx == k)
               {
                if(ev[peek2].kind == 0)
                  {
                   haveSWH = true; swhPrice = ev[peek2].price; swhIdx = ev[peek2].swingIdx;
                   pendingBullAifobIdx = -1;
                   TryBearishAOB(prevRegime, aobSWLidx, ev[peek2].swingIdx, ev[peek2].price, k);
                   if(pendingBearAifobIdx == -1)
                     {
                      int idx2 = TryBearishAIFOB(prevRegime, haveSWL, aobSWLidx, lastSWHidx, ev[peek2].swingIdx, k);
                      if(idx2 != -1) pendingBearAifobIdx = idx2;
                     }
                  }
                else
                  {
                   haveSWL = true; swlPrice = ev[peek2].price; swlIdx = ev[peek2].swingIdx;
                   pendingBearAifobIdx = -1;
                   TryBullishAOB(prevRegime, aobSWHidx, ev[peek2].swingIdx, ev[peek2].price, k);
                   if(pendingBullAifobIdx == -1)
                     {
                      int idx2 = TryBullishAIFOB(prevRegime, haveSWH, aobSWHidx, lastSWLidx, ev[peek2].swingIdx, k);
                      if(idx2 != -1) pendingBullAifobIdx = idx2;
                     }
                  }
                peek2++;
               }
            }
            if(haveSWH && H[k] > swhPrice)
              {
               if(regime == 0) regime = 1; else if(regime == 2) regime = 1;
               if(pendingBullAifobIdx != -1)
                 { ob[pendingBullAifobIdx].state = 0; ob[pendingBullAifobIdx].origState = 0; pendingBullAifobIdx = -1; }
               else if(lastSWLidx >= 0)
                 {
                  int lo = MathMin(MathMin(lastSWLidx, k), swhIdx);
                  int hi = MathMax(MathMax(lastSWLidx, k), swhIdx);
                  int best = PickLowestBearish(lo, hi);
                  if(best != -1) AddOB(best, MathMin(O[best],C[best]), MathMax(O[best],C[best]), true, k, 0);
                 }
               haveSWH = false; swhConsumed = true;
              }
           }

         //--- STEP2: arm + eligibility ---
         while(ei < evCount && ev[ei].confirmIdx == k)
           {
            if(ev[ei].kind == 0)
              {
               if(!swhConsumed) { haveSWH = true; swhPrice = ev[ei].price; swhIdx = ev[ei].swingIdx; }
               lastSWHidx = ev[ei].swingIdx;
               for(int z = 0; z < obCount; z++)
                  if(ob[z].bullish && ob[z].state == 0 && ob[z].eligibleK == -1 && k > ob[z].triggerK)
                     ob[z].eligibleK = k;
              }
            else
              {
               if(!swlConsumed) { haveSWL = true; swlPrice = ev[ei].price; swlIdx = ev[ei].swingIdx; }
               lastSWLidx = ev[ei].swingIdx;
               for(int z = 0; z < obCount; z++)
                  if(!ob[z].bullish && ob[z].state == 0 && ob[z].eligibleK == -1 && k > ob[z].triggerK)
                     ob[z].eligibleK = k;
              }
            ei++;
           }

         //--- STEP3: lifecycle ---
         for(int z = 0; z < obCount; z++)
           {
            if(ob[z].state == 3) continue;
            double zb = ob[z].zb, zt = ob[z].zt; bool bull = ob[z].bullish;
            bool impacted = false;
            if(ob[z].eligibleK != -1 && k >= ob[z].eligibleK)
              {
               if(H[k] >= zb && L[k] <= zt) { ob[z].state = 3; ob[z].touchK = k; impacted = true; }
              }
            if(!impacted && (ob[z].state == 0 || ob[z].state == 1 || ob[z].state == 4) && ob[z].eligibleK != -1)
              {
               bool isIFOB = (ob[z].origState != 1);
               for(int e2 = 0; e2 < evCount; e2++)
                 {
                  if(ev[e2].confirmIdx != k) continue;
                  if(isIFOB)
                    {
                     if(bull && ev[e2].kind == 1 && ev[e2].price > zt) ob[z].state = 2;
                     if(!bull && ev[e2].kind == 0 && ev[e2].price < zb) ob[z].state = 2;
                    }
                  else
                    {
                     if(bull && ev[e2].kind == 0 && ev[e2].price < zb) ob[z].state = 2;
                     if(!bull && ev[e2].kind == 1 && ev[e2].price > zt) ob[z].state = 2;
                    }
                 }
              }
           }
        }
      return true;
     }

   // helpers for the EA layer
   int LastClosedIdx() { return n - 2; } // n-1 is the still-forming bar
  };

//================================ THE THREE ENGINE INSTANCES ================================
COBEngine g_daily, g_h4, g_h1;

//================================ EA CASCADE STATE ================================
// bias: 0 none, 1 bullish, 2 bearish -- mirrors g_daily.regime once established
int g_bias = 0;

// the daily OB we are currently tracking through touch -> violate/respect -> used-up
int  g_activeDailyIdx   = -1;   // index into g_daily.ob[]
bool g_activeDailyIsOpp = false; // true if this is an OPPOSING (counter-bias) daily OB
int  g_dailyEvPtr       = 0;     // how far into g_daily.ev[] we've already scanned for the "used-up" swing

// 4H hunting mode: 0 inactive, 1 buy-only, 2 sell-only, 3 both (ambiguous)
int      g_huntMode = 0;
datetime g_huntStartTime = 0; // only 4H OBs formed after this count as fresh hunting POIs

// which 4H OB (if any) is currently escalated to the 1H entry-watch
int  g_active4hIdx = -1;

// ambiguity-resolution reference (set when an OPPOSING daily OB gets used up)
double   g_usedUpSwingPrice  = 0;
bool     g_usedUpSwingIsHigh = false; // true = watch for price reclaiming ABOVE it (bullish resolution)

// ---- 1H entry sub-state machine (reusable for daily- or 4h-driven setups) ----
// 0 idle, 1 watching for the first matching 1H OB, 2 watching for the respect reaction, 3 pending entry
int      g_1hStage  = 0;
bool     g_1hBuy    = false;
datetime g_1hWatchStart = 0;   // only 1H OBs created after this time count
int      g_1hOBIdx  = -1;      // index into g_h1.ob[] once found
int      g_1hReactionCandle = -1;
double   g_1hSLPrice = 0;      // SL level fixed at the reaction candle, checked while we wait for session window
datetime g_1hStageStart = 0;   // when we entered the CURRENT stage -- for the stall timeout

datetime g_lastDailyBarTime = 0;
datetime g_lastH4BarTime    = 0;
datetime g_lastH1BarTime    = 0;

//+------------------------------------------------------------------+
//| Session filter: only enter in the first InpSessionWindowHrs of   |
//| the London or New York session (broker/server time).             |
//+------------------------------------------------------------------+
bool InSessionWindow(datetime t)
  {
   MqlDateTime dt; TimeToStruct(t, dt);
   int h = dt.hour;
   bool inLondon = (h >= InpLondonStartHour && h < InpLondonStartHour + InpSessionWindowHrs);
   bool inNY     = (h >= InpNewYorkStartHour && h < InpNewYorkStartHour + InpSessionWindowHrs);
   return inLondon || inNY;
  }

//+------------------------------------------------------------------+
//| Risk-based position sizing from SL distance (in price).           |
//+------------------------------------------------------------------+
double CalcLotSize(double riskDistPrice, bool isBuy, double entryPrice)
  {
   double equity   = AccountInfoDouble(ACCOUNT_EQUITY);
   double riskMoney = equity * (InpRiskPercent / 100.0);
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickSize <= 0 || tickValue <= 0 || riskDistPrice <= 0) return 0;
   double lots = riskMoney / (riskDistPrice / tickSize * tickValue);

   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double lotMin  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double lotMax  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   lots = MathFloor(lots / lotStep) * lotStep;
   if(lots < lotMin) lots = lotMin;
   if(lots > lotMax) lots = lotMax;

   // A tight SL relative to normal volatility can blow the risk-based size up
   // far past what the account can actually margin (e.g. a 1-2 pip H1 stop on
   // a $100k account demanding 70+ lots). Sending that straight to the broker
   // just gets rejected outright ("not enough money") instead of skipping or
   // right-sizing the trade. Cap it to what free margin can actually support.
   double margin = 0;
   ENUM_ORDER_TYPE ot = isBuy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   if(OrderCalcMargin(ot, _Symbol, lots, entryPrice, margin) && margin > 0)
     {
      double freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
      if(margin > freeMargin)
        {
         double scaled = lots * (freeMargin / margin) * 0.95; // safety buffer
         scaled = MathFloor(scaled / lotStep) * lotStep;
         lots = (scaled < lotMin) ? 0 : scaled; // doesn't even fit at minimum -- skip the trade
        }
     }
   return lots;
  }

//+------------------------------------------------------------------+
//| Was a given daily OB just touched, and did it respect or violate  |
//| on that same candle (body close through = violate)?                |
//+------------------------------------------------------------------+
bool DailyRespected(int obIdx, int candleIdx)
  {
   bool   bull = g_daily.ob[obIdx].bullish;
   double zb = g_daily.ob[obIdx].zb, zt = g_daily.ob[obIdx].zt;
   if(bull) return g_daily.C[candleIdx] >= zb; // did NOT close below the demand zone
   else     return g_daily.C[candleIdx] <= zt; // did NOT close above the supply zone
  }

//+------------------------------------------------------------------+
//| Start the 1H entry-watch for a setup spawned by a daily or 4H OB. |
//+------------------------------------------------------------------+
void StartWatching1H(bool buyDirection, datetime fromTime)
  {
   g_1hStage      = 1;
   g_1hBuy        = buyDirection;
   g_1hWatchStart = fromTime;
   g_1hOBIdx      = -1;
   g_1hReactionCandle = -1;
   g_1hStageStart = TimeCurrent();
  }

//+------------------------------------------------------------------+
//| Advance the 1H sub-state machine one step (call after each H1     |
//| bar close). Places the entry order itself when respect confirms   |
//| and the next hour's bar has opened.                                |
//+------------------------------------------------------------------+
void Advance1H()
  {
   if(g_1hStage == 0) return;

   // Stall guard: none of the three sub-stages has a bound on how long they may
   // wait (stage 1 for a matching 1H structure, stage 2 for the wick reaction,
   // stage 3 for a session window to open). Left unbounded, a direction that
   // simply doesn't produce the next piece of structure for a long stretch would
   // occupy g_1hStage forever and block UpdateHuntLevel()'s "one setup at a
   // time" gate from ever starting a fresh, more current setup. Give up and
   // free the slot after InpMaxWaitH1Bars hours with no resolution.
   if(TimeCurrent() - g_1hStageStart >= (long)InpMaxWaitH1Bars * 3600)
     {
      PrintFormat("[1H] %s stalled in stage %d for >%d hours -- giving up this watch",
                  TimeToString(TimeCurrent()), g_1hStage, InpMaxWaitH1Bars);
      g_1hStage = 0;
      return;
     }

   if(g_1hStage == 1)
     {
      int found = -1; datetime foundTime = 0;
      for(int z = 0; z < g_h1.obCount; z++)
        {
         if(g_h1.ob[z].bullish != g_1hBuy) continue;
         if(g_h1.ob[z].t <= g_1hWatchStart) continue;
         if(found == -1 || g_h1.ob[z].t < foundTime) { found = z; foundTime = g_h1.ob[z].t; }
        }
      if(found != -1)
        {
         g_1hOBIdx = found; g_1hStage = 2; g_1hStageStart = TimeCurrent();
         PrintFormat("[1H] found matching %s H1 OB #%d (formed %s) -- watching for reaction",
                     g_1hBuy?"bullish":"bearish", found, TimeToString(foundTime));
        }
      return;
     }

   if(g_1hStage == 2)
     {
      int lc = g_h1.LastClosedIdx();
      if(lc < 0) return;
      if(g_h1.ob[g_1hOBIdx].state == 2)
        {
         PrintFormat("[1H] %s watched OB #%d stranded before reacting -- resume watching", TimeToString(g_h1.Time[lc]), g_1hOBIdx);
         g_1hStage = 1; g_1hOBIdx = -1; g_1hStageStart = TimeCurrent(); return; // stranded before reacting
        }
      double zb = g_h1.ob[g_1hOBIdx].zb, zt = g_h1.ob[g_1hOBIdx].zt;
      bool wicked = (g_h1.H[lc] >= zb && g_h1.L[lc] <= zt);
      if(!wicked) return;

      bool respected = g_1hBuy ? (g_h1.C[lc] >= zt) : (g_h1.C[lc] <= zb);
      if(respected)
        {
         g_1hReactionCandle = lc;
         g_1hSLPrice = g_1hBuy ? g_h1.L[lc] : g_h1.H[lc];
         g_1hStage = 3;
         g_1hStageStart = TimeCurrent();
         PrintFormat("[1H] %s reaction RESPECTED on OB #%d -- pending entry (SL=%f)", TimeToString(g_h1.Time[lc]), g_1hOBIdx, g_1hSLPrice);
        }
      else
        {
         PrintFormat("[1H] %s reaction VIOLATED on OB #%d -- resume watching", TimeToString(g_h1.Time[lc]), g_1hOBIdx);
         g_1hStage = 1; g_1hOBIdx = -1; g_1hStageStart = TimeCurrent(); // violated -- keep watching for the next 1H setup
        }
      return;
     }

   if(g_1hStage == 3)
     {
      // The session-time rule is a TIMING gate on when to fire the entry, not a
      // filter on which setups are eligible. A confirmed reaction that happens
      // to land outside the window must WAIT for the next in-window hour, not
      // be thrown away -- discarding it here was silently killing the large
      // majority of otherwise-valid setups (only ~4 of 24 hours qualify).
      int cur = g_h1.n - 1; // the bar that just opened this tick (still forming)
      if(cur <= g_1hReactionCandle) return; // the bar right after the reaction hasn't opened yet

      // While we wait, make sure price hasn't already breached the reaction
      // candle's SL level -- entering late on a setup that already failed
      // would put the stop on the wrong side of price.
      for(int x = g_1hReactionCandle + 1; x <= cur; x++)
        {
         bool breached = g_1hBuy ? (g_h1.L[x] <= g_1hSLPrice) : (g_h1.H[x] >= g_1hSLPrice);
         if(breached)
           {
            PrintFormat("[1H] %s SL level breached while waiting for session window -- resume watching", TimeToString(g_h1.Time[x]));
            g_1hStage = 1; g_1hOBIdx = -1; g_1hStageStart = TimeCurrent(); return;
           }
        }

      datetime entryTime = g_h1.Time[cur];
      if(!InSessionWindow(entryTime)) return; // keep waiting for the next in-window hour

      if(PositionsTotal() > 0)
        {
         PrintFormat("[1H] %s setup ready but a position is already open -- setup skipped", TimeToString(entryTime));
         g_1hStage = 0; return; // one trade at a time
        }

      double entryPrice = g_h1.O[cur];
      double slPrice = g_1hSLPrice;
      double riskDist = g_1hBuy ? (entryPrice - slPrice) : (slPrice - entryPrice);
      if(riskDist <= 0) { g_1hStage = 1; g_1hOBIdx = -1; g_1hStageStart = TimeCurrent(); return; }

      double tpPrice = g_1hBuy ? entryPrice + riskDist * InpRR_Target : entryPrice - riskDist * InpRR_Target;
      double lots = CalcLotSize(riskDist, g_1hBuy, entryPrice);
      PrintFormat("[1H] %s ENTRY %s @ %f SL=%f TP=%f lots=%f", TimeToString(entryTime), g_1hBuy?"BUY":"SELL", entryPrice, slPrice, tpPrice, lots);
      if(lots > 0)
        {
         trade.SetExpertMagicNumber(InpMagic);
         if(g_1hBuy) trade.Buy(lots, _Symbol, 0, slPrice, tpPrice, "ICT_EA_1");
         else        trade.Sell(lots, _Symbol, 0, slPrice, tpPrice, "ICT_EA_1");
        }
      g_1hStage = 0;
     }
  }

//+------------------------------------------------------------------+
//| Move SL to breakeven once a position reaches InpRR_BE reward:risk. |
//+------------------------------------------------------------------+
void ManageBreakeven()
  {
   for(int i = 0; i < PositionsTotal(); i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != (long)InpMagic) continue;

      double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl        = PositionGetDouble(POSITION_SL);
      double curPrice  = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ?
                          SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      bool isBuy = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
      double riskDist = isBuy ? (openPrice - sl) : (sl - openPrice);
      if(riskDist <= 0) continue;
      double rr = isBuy ? (curPrice - openPrice) / riskDist : (openPrice - curPrice) / riskDist;
      if(rr >= InpRR_BE)
        {
         bool alreadyBE = isBuy ? (sl >= openPrice) : (sl <= openPrice);
         if(!alreadyBE)
            trade.PositionModify(ticket, openPrice, PositionGetDouble(POSITION_TP));
        }
     }
  }

//+------------------------------------------------------------------+
//| Daily-level cascade: find/track the active daily OB through       |
//| touch -> violate (done) / respect -> used-up (advance hunt mode). |
//+------------------------------------------------------------------+
void UpdateDailyLevel()
  {
   int prevBias = g_bias;
   g_bias = (g_daily.regime == 1 || g_daily.regime == 2) ? g_daily.regime : g_bias;
   if(g_bias != prevBias)
      PrintFormat("[DAILY] %s bias -> %s", TimeToString(g_daily.Time[g_daily.LastClosedIdx()]), g_bias==1?"BULLISH":"BEARISH");

   // Always check for a fresh touch on the last closed candle, even while
   // another OB is still being tracked -- a "used up" confirmation can take
   // a long time (or never come) in a quiet market, and a new touch is
   // objectively more current. Without this, one early OB that never
   // resolves would permanently block all future daily engagement.
   int lc = g_daily.LastClosedIdx();
   for(int z = 0; z < g_daily.obCount; z++)
     {
      if(g_daily.ob[z].touchK != lc) continue; // only react to a touch that JUST happened
      if(z == g_activeDailyIdx) break;         // this IS the one we're already tracking
      bool isOpposing = (g_bias != 0) && (g_daily.ob[z].bullish == (g_bias == 2));
      if(DailyRespected(z, lc))
        {
         g_activeDailyIdx = z;
         g_activeDailyIsOpp = isOpposing;
         g_dailyEvPtr = g_daily.evCount; // only swings AFTER this count matter for "used up"
         StartWatching1H(g_daily.ob[z].bullish, g_daily.Time[lc]);
         PrintFormat("[DAILY] %s touch RESPECTED on %s OB #%d (opposing=%s) -- now tracking for used-up",
                     TimeToString(g_daily.Time[lc]), g_daily.ob[z].bullish?"bullish":"bearish", z, isOpposing?"true":"false");
        }
      else
        {
         PrintFormat("[DAILY] %s touch VIOLATED on %s OB #%d -- done, no action",
                     TimeToString(g_daily.Time[lc]), g_daily.ob[z].bullish?"bullish":"bearish", z);
        }
      break;
     }
   if(g_activeDailyIdx == -1) return;

   // we ARE tracking one -- watch for the confirming swing that makes it "used up"
   bool wantHighConfirm = g_daily.ob[g_activeDailyIdx].bullish ? false : true; // bearish OB -> wait for a SWH
   for(int e = g_dailyEvPtr; e < g_daily.evCount; e++)
     {
      int kind = g_daily.ev[e].kind;
      if((wantHighConfirm && kind == 0) || (!wantHighConfirm && kind == 1))
        {
         // USED UP
         if(!g_activeDailyIsOpp)
           {
            g_huntMode = g_daily.ob[g_activeDailyIdx].bullish ? 1 : 2; // resume/continue single-direction hunt
           }
         else
           {
            g_huntMode = 3; // ambiguous -- opposing OB proved itself, watch both ways
            g_usedUpSwingPrice  = g_daily.ev[e].price;
            g_usedUpSwingIsHigh = (kind == 0);
           }
         g_huntStartTime = g_daily.Time[g_daily.LastClosedIdx()];
         PrintFormat("[DAILY] %s USED UP OB #%d -- huntMode=%d, huntStartTime=%s",
                     TimeToString(g_daily.Time[g_daily.LastClosedIdx()]), g_activeDailyIdx, g_huntMode, TimeToString(g_huntStartTime));
         g_activeDailyIdx = -1;
         break;
        }
     }
  }

//+------------------------------------------------------------------+
//| 4H hunting: mark fresh 4H OBs matching the allowed direction(s)   |
//| and escalate the first one to the 1H entry-watch.                 |
//+------------------------------------------------------------------+
void UpdateHuntLevel()
  {
   if(g_huntMode == 0) return;

   // Whenever the daily regime flips to a direction huntMode doesn't already
   // reflect -- a genuine new daily MSS -- redirect hunting to follow it
   // immediately, in EVERY huntMode (not just the ambiguous one, 3). Previously
   // this reversal was only ever detected while huntMode==3, so a clean
   // single-direction hunt (1 or 2) set up once would keep hunting that same
   // stale direction forever even after the trend reversed days or months
   // later, since nothing else ever re-touches g_huntMode. Any stale 1H watch
   // for the old direction is abandoned along with it.
   if(g_daily.regime != 0 && g_daily.regime != g_huntMode)
     {
      PrintFormat("[HUNT] %s daily regime flip -- huntMode %d -> %d, abandoning any stale watch",
                  TimeToString(g_daily.Time[g_daily.LastClosedIdx()]), g_huntMode, g_daily.regime);
      g_huntMode      = g_daily.regime; // 1=up/buy, 2=down/sell -- same encoding as regime
      g_bias          = g_daily.regime;
      g_huntStartTime = g_daily.Time[g_daily.LastClosedIdx()];
      g_1hStage       = 0;
     }

   if(g_1hStage != 0) return; // already busy watching/entering one setup at a time

   int lc = g_h4.LastClosedIdx();
   if(lc < 0) return;

   bool allowBuy  = (g_huntMode == 1 || g_huntMode == 3);
   bool allowSell = (g_huntMode == 2 || g_huntMode == 3);

   for(int z = g_h4.obCount - 1; z >= 0; z--)
     {
      // any state (including OOB) is eligible, matching the daily-level rule --
      // what matters is whether price just touched it, not its current state.
      if(g_h4.ob[z].t < g_huntStartTime) continue; // only OBs formed since hunting began
      if(g_h4.ob[z].bullish && !allowBuy) continue;
      if(!g_h4.ob[z].bullish && !allowSell) continue;
      if(g_h4.ob[z].touchK == lc) // price just reached this 4H OB
        {
         StartWatching1H(g_h4.ob[z].bullish, g_h4.Time[lc]);
         g_active4hIdx = z;
         PrintFormat("[HUNT] %s escalating %s H4 OB #%d to 1H watch (huntMode=%d)",
                     TimeToString(g_h4.Time[lc]), g_h4.ob[z].bullish?"bullish":"bearish", z, g_huntMode);
         break;
        }
     }

   // ambiguity resolution (b), reaching a fresh in-trend daily IFOB/AIFOB, is
   // handled by UpdateDailyLevel()'s own touch/respect/used-up tracking; case
   // (b), a genuine regime flip, is now handled generically above for every
   // huntMode. Only (c) -- price reclaiming past the opposing-OB reaction's
   // swing without waiting for a full new daily cycle -- needs handling here.
   if(g_huntMode == 3)
     {
      double last = iClose(_Symbol, PERIOD_D1, 1);
      if(g_usedUpSwingIsHigh && last > g_usedUpSwingPrice)
        {
         // (c) price reclaimed back above the opposing-OB reaction's swing high
         g_huntMode = 1;
         g_huntStartTime = g_h4.Time[lc];
         PrintFormat("[HUNT] ambiguity resolved (c) reclaimed above %f -> huntMode=1", g_usedUpSwingPrice);
        }
      else if(!g_usedUpSwingIsHigh && last < g_usedUpSwingPrice)
        {
         g_huntMode = 2;
         g_huntStartTime = g_h4.Time[lc];
         PrintFormat("[HUNT] ambiguity resolved (c) reclaimed below %f -> huntMode=2", g_usedUpSwingPrice);
        }
     }
  }

int OnInit()
  {
   g_daily.Init(_Symbol, PERIOD_D1, InpDailyBars);
   g_h4.Init(_Symbol, PERIOD_H4, InpH4Bars);
   g_h1.Init(_Symbol, PERIOD_H1, InpH1Bars);
   return(INIT_SUCCEEDED);
  }

void OnTick()
  {
   ManageBreakeven();

   datetime dT = iTime(_Symbol, PERIOD_D1, 0);
   datetime h4T = iTime(_Symbol, PERIOD_H4, 0);
   datetime h1T = iTime(_Symbol, PERIOD_H1, 0);

   bool newDaily = (dT != g_lastDailyBarTime);
   bool newH4    = (h4T != g_lastH4BarTime);
   bool newH1    = (h1T != g_lastH1BarTime);

   if(newDaily) { g_lastDailyBarTime = dT; g_daily.Refresh(); UpdateDailyLevel(); }
   if(newH4)    { g_lastH4BarTime = h4T; g_h4.Refresh(); }
   if(newH1)    { g_lastH1BarTime = h1T; g_h1.Refresh(); UpdateHuntLevel(); Advance1H(); }
  }
