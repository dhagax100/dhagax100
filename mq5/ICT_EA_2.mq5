//+------------------------------------------------------------------+
//|                                                    ICT_EA_2.mq5  |
//|  Weekly/Daily bias -> 4H confirm -> 5M entry cascade.             |
//|                                                                    |
//|  Reuses the SAME proven swing/MSS/OB engine as ICT_EA_1.mq5        |
//|  (dual-candle swing detection, alternation rule, MSS, IFOB/AOB/    |
//|  AIFOB/OOB/SPENT, body-superiority ranking) unchanged -- only the  |
//|  cascade logic on top is new, per the bias/confirm/entry spec:     |
//|                                                                    |
//|  TIER 1 (bias, Weekly or Daily, InpBiasTF): a POI becomes live the |
//|  instant price wicks into it, and stays live -- rolling forward    |
//|  across period closes -- until EITHER a candle BODY closes inside  |
//|  its range, OR the matching-direction swing confirms after entry   |
//|  (swing high kills a bearish POI, swing low kills a bullish one).  |
//|  Wick-only touches never kill it.                                  |
//|                                                                    |
//|  TIER 2 (confirm, fixed H4): once the bias POI is live, hunt H4    |
//|  POIs (aggressive=counter-trend AOB, or in-favor=with-trend IFOB/  |
//|  AIFOB) matching the bias direction, formed since bias entry.      |
//|  Same two kill conditions apply here too (confirmed: this scales   |
//|  to every tier). Overlapping H4 zones already being watched are    |
//|  merged, not restarted.                                            |
//|                                                                    |
//|  TIER 3 (entry, fixed M5): once price (5M) wicks into the live H4  |
//|  zone, place a stop order (sell-stop for a bearish cascade, buy-   |
//|  stop for bullish) at the latest matching 5M swing formed since    |
//|  entry. Re-trail to each newer matching swing until it fills, the  |
//|  H4/bias POI invalidates, or the trading session window closes for |
//|  the day (order is cancelled at the close of the window and the    |
//|  hunt resumes fresh next session day, provided the zone is still   |
//|  live).                                                             |
//|                                                                    |
//|  ASSUMPTIONS not yet nailed down in spec -- flagged for review:    |
//|   - Position SL defaults to the H4 confirm zone's far boundary     |
//|     (zt for sells, zb for buys); TP at InpRR_Target x that risk.   |
//|   - One trade at a time (any open position blocks new entries),    |
//|     mirroring ICT_EA_1.                                             |
//|   - Only one bias POI tracked live at a time (the multi-POI-at-    |
//|     once case is the explicitly-deferred next topic).              |
//|   - H4-zone overlap merge only extends bounds; it does not re-fold |
//|     a zone that already invalidated back in.                       |
//|                                                                    |
//|  First complete build -- expect a test-and-refine cycle.           |
//+------------------------------------------------------------------+
#property strict
#include <Trade\Trade.mqh>

//================================ INPUTS ================================
input ENUM_TIMEFRAMES InpBiasTF        = PERIOD_W1;  // bias tier: PERIOD_W1 or PERIOD_D1
input double InpRiskPercent      = 1.0;   // risk % of equity per trade
input double InpRR_Target        = 3.0;   // reward:risk target (take profit)
input double InpRR_BE            = 2.0;   // move SL to breakeven at this RR
input int    InpLondonStartHour  = 8;     // London session start (broker/server time)
input int    InpNewYorkStartHour = 13;    // New York session start (broker/server time)
input int    InpSessionWindowHrs = 4;     // trading window length from each session start
input int    InpBiasBars         = 520;   // bias-tf bars to keep in the engine
input int    InpH4Bars           = 3000;  // 4H bars to keep in the engine
input int    InpM5Bars           = 6000;  // 5M bars to keep in the engine
input ulong  InpMagic            = 202602;

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
//| Unchanged from ICT_EA_1.mq5 -- see that file for the reasoning     |
//| behind the anchored-window / dual-candle-swing / AOB / AIFOB      |
//| mechanics; only the EA-layer cascade below it is new.              |
//+------------------------------------------------------------------+
class COBEngine
  {
public:
   string          m_sym;
   ENUM_TIMEFRAMES m_tf;
   int             m_bars;
   datetime        m_anchorTime;

   SwEv   ev[];
   int    evCount;
   ObZone ob[];
   int    obCount;

   bool   haveSWH; double swhPrice; int swhIdx;
   bool   haveSWL; double swlPrice; int swlIdx;
   int    regime;
   int    lastSWHidx, lastSWLidx;
   int    pendingBullAifobIdx, pendingBearAifobIdx;

   int    n;
   double O[], H[], L[], C[];
   datetime Time[];

   void Init(string sym, ENUM_TIMEFRAMES tf, int bars)
     {
      m_sym = sym; m_tf = tf; m_bars = bars;
      evCount = 0; obCount = 0; n = 0;
      m_anchorTime = 0;
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
      if(best == -1 || L[best] <= newSwlPrice) return -1;
      return AddOB(best, MathMin(O[best], C[best]), MathMax(O[best], C[best]), true, k, 1);
     }

   int TryBearishAOB(int prevRegime, int aobSWLidx, int newSwhIdx, double newSwhPrice, int k)
     {
      if(prevRegime != 2 || aobSWLidx < 0) return -1;
      int lo = MathMax(0, MathMin(aobSWLidx - 1, newSwhIdx));
      int hi = MathMax(aobSWLidx - 1, newSwhIdx);
      int best = PickLowestBearish(lo, hi);
      if(best == -1 || H[best] >= newSwhPrice) return -1;
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
      if(m_anchorTime == 0)
        {
         datetime a = iTime(m_sym, m_tf, m_bars - 1);
         if(a <= 0) return false;
         m_anchorTime = a;
        }

      ArraySetAsSeries(O, false); ArraySetAsSeries(H, false);
      ArraySetAsSeries(L, false); ArraySetAsSeries(C, false);
      ArraySetAsSeries(Time, false);

      datetime stop = TimeCurrent() + PeriodSeconds(m_tf);
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

   int LastClosedIdx() { return n - 2; } // n-1 is the still-forming bar
  };

//================================ THE THREE ENGINE INSTANCES ================================
COBEngine g_bias, g_confirm, g_entry;

//================================ TIER TRACKING ================================
// Generic "is this POI still halal" tracker, shared by the bias and confirm
// tiers (confirmed: the two kill conditions scale to every tier).
struct PoiTrack
  {
   int idx;       // index into <engine>.ob[], -1 = none currently live
   int entryK;    // candle index of first touch (kill-by-swing only counts AFTER this)
   int swingPtr;  // how far into <engine>.ev[] already scanned for a killing swing
  };

PoiTrack g_biasTr    = { -1, -1, 0 };
PoiTrack g_confirmTr = { -1, -1, 0 };

datetime g_huntStartTime = 0; // 4H POIs must be formed at/after this (bias entry time) to count
bool     g_confirmBull   = false;
double   g_confirmZb = 0, g_confirmZt = 0; // live bounds used for the 5m watch (may be a merge)

int      g_entryStage      = 0;   // 0 idle, 1 active (watching/trailing on M5)
datetime g_entryWatchStart = 0;   // H4 touch time -- M5 structure must be fresh from here
int      g_entryEnteredIdx = -1;  // M5 candle idx when price first got inside the confirm zone
double   g_entrySwingPrice = 0;
ulong    g_pendingTicket   = 0;

datetime g_lastBiasBarTime = 0;
datetime g_lastH4BarTime   = 0;
datetime g_lastM5BarTime   = 0;

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

   double margin = 0;
   ENUM_ORDER_TYPE ot = isBuy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   if(OrderCalcMargin(ot, _Symbol, lots, entryPrice, margin) && margin > 0)
     {
      double freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
      if(margin > freeMargin)
        {
         double scaled = lots * (freeMargin / margin) * 0.95;
         scaled = MathFloor(scaled / lotStep) * lotStep;
         lots = (scaled < lotMin) ? 0 : scaled;
        }
     }
   return lots;
  }

//+------------------------------------------------------------------+
//| Is the tracked POI (bias or confirm tier -- same rule, either      |
//| engine) still halal on the tier's own just-closed candle lc?       |
//| Kills on: (1) a candle BODY closing inside the zone, or (2) the    |
//| matching-direction swing (swing high for bearish, swing low for    |
//| bullish) confirming at any point after entry. Wick-only touches    |
//| never kill it -- that's the whole point of this tracker.           |
//+------------------------------------------------------------------+
bool PoiStillHalal(COBEngine &eng, PoiTrack &tr, int lc)
  {
   if(tr.idx == -1) return false;
   double zb = eng.ob[tr.idx].zb, zt = eng.ob[tr.idx].zt;

   double bodyLo = MathMin(eng.O[lc], eng.C[lc]);
   double bodyHi = MathMax(eng.O[lc], eng.C[lc]);
   if(bodyHi >= zb && bodyLo <= zt) return false; // kill condition 1: body closed inside the range

   bool wantHigh = !eng.ob[tr.idx].bullish; // bearish POI dies on a swing HIGH, bullish on a swing LOW
   for(int e = tr.swingPtr; e < eng.evCount; e++)
     {
      if(eng.ev[e].confirmIdx <= tr.entryK) continue; // must confirm strictly after entry
      if((wantHigh && eng.ev[e].kind == 0) || (!wantHigh && eng.ev[e].kind == 1))
         return false; // kill condition 2: matching swing confirmed
     }
   tr.swingPtr = eng.evCount;
   return true;
  }

//+------------------------------------------------------------------+
//| First eligible wick-touch on the tier's just-closed candle lc,     |
//| among POIs formed at/after notBefore and (if requireDirection)     |
//| matching wantBull. -1 if none.                                     |
//+------------------------------------------------------------------+
int FindFreshTouch(COBEngine &eng, int lc, datetime notBefore, bool wantBull, bool requireDirection)
  {
   for(int z = eng.obCount - 1; z >= 0; z--)
     {
      if(requireDirection && eng.ob[z].bullish != wantBull) continue;
      if(eng.ob[z].t < notBefore) continue;
      if(eng.ob[z].eligibleK == -1 || lc < eng.ob[z].eligibleK) continue;
      bool wick = (eng.H[lc] >= eng.ob[z].zb && eng.L[lc] <= eng.ob[z].zt);
      if(wick) return z;
     }
   return -1;
  }

//+------------------------------------------------------------------+
void CancelPendingOrder()
  {
   if(g_pendingTicket != 0)
     {
      if(OrderSelect(g_pendingTicket)) trade.OrderDelete(g_pendingTicket);
      g_pendingTicket = 0;
     }
  }

void RetireConfirm()
  {
   g_confirmTr.idx = -1;
   g_entryStage = 0;
   g_entryEnteredIdx = -1;
   CancelPendingOrder();
  }

void RetireBias()
  {
   g_biasTr.idx = -1;
   RetireConfirm();
  }

void StartEntryWatch(datetime fromTime)
  {
   g_entryStage = 1;
   g_entryWatchStart = fromTime;
   g_entryEnteredIdx = -1;
   CancelPendingOrder();
  }

//+------------------------------------------------------------------+
//| TIER 1: bias POI (Weekly or Daily) lifecycle.                      |
//+------------------------------------------------------------------+
void UpdateBiasLevel()
  {
   int lc = g_bias.LastClosedIdx();
   if(lc < 0) return;

   if(g_biasTr.idx != -1 && !PoiStillHalal(g_bias, g_biasTr, lc))
     {
      PrintFormat("[BIAS] %s POI #%d KILLED", TimeToString(g_bias.Time[lc]), g_biasTr.idx);
      RetireBias();
     }

   if(g_biasTr.idx == -1)
     {
      int z = FindFreshTouch(g_bias, lc, 0, false, false);
      if(z != -1)
        {
         g_biasTr.idx = z; g_biasTr.entryK = lc; g_biasTr.swingPtr = g_bias.evCount;
         g_huntStartTime = g_bias.Time[lc];
         RetireConfirm(); // fresh bias entry -- drop any stale confirm/entry watch
         PrintFormat("[BIAS] %s entered %s POI #%d [%.5f-%.5f]", TimeToString(g_bias.Time[lc]),
                     g_bias.ob[z].bullish ? "bullish" : "bearish", z, g_bias.ob[z].zb, g_bias.ob[z].zt);
        }
     }
  }

//+------------------------------------------------------------------+
//| TIER 2: 4H confirm zone (aggressive or in-favor), same lifecycle.  |
//+------------------------------------------------------------------+
void UpdateConfirmLevel()
  {
   if(g_biasTr.idx == -1) { if(g_confirmTr.idx != -1) RetireConfirm(); return; }

   int lc = g_confirm.LastClosedIdx();
   if(lc < 0) return;

   if(g_confirmTr.idx != -1 && !PoiStillHalal(g_confirm, g_confirmTr, lc))
     {
      PrintFormat("[CONFIRM] %s 4H POI #%d KILLED", TimeToString(g_confirm.Time[lc]), g_confirmTr.idx);
      RetireConfirm();
     }

   bool wantBull = g_bias.ob[g_biasTr.idx].bullish;

   if(g_confirmTr.idx == -1)
     {
      int z = FindFreshTouch(g_confirm, lc, g_huntStartTime, wantBull, true);
      if(z == -1) return;

      double zb = g_confirm.ob[z].zb, zt = g_confirm.ob[z].zt;
      bool overlapsLive = (g_entryStage == 1 && zb <= g_confirmZt && zt >= g_confirmZb);

      g_confirmTr.idx = z; g_confirmTr.entryK = lc; g_confirmTr.swingPtr = g_confirm.evCount;
      g_confirmBull = wantBull;

      if(overlapsLive)
        {
         // overlaps the zone we were already trailing on -- merge bounds only,
         // keep the existing M5 watch/pending order progress intact.
         g_confirmZb = MathMin(g_confirmZb, zb);
         g_confirmZt = MathMax(g_confirmZt, zt);
         PrintFormat("[CONFIRM] %s merged overlapping %s 4H POI #%d into live watch [%.5f-%.5f]",
                     TimeToString(g_confirm.Time[lc]), wantBull ? "bullish" : "bearish", z, g_confirmZb, g_confirmZt);
        }
      else
        {
         g_confirmZb = zb; g_confirmZt = zt;
         StartEntryWatch(g_confirm.Time[lc]);
         PrintFormat("[CONFIRM] %s escalating %s 4H %s POI #%d [%.5f-%.5f] to 5m watch",
                     TimeToString(g_confirm.Time[lc]), wantBull ? "bullish" : "bearish",
                     g_confirm.ob[z].origState == 1 ? "aggressive" : "in-favor", z, zb, zt);
        }
     }
  }

//+------------------------------------------------------------------+
//| TIER 3: 5M trailing stop-entry inside the live confirm zone.       |
//+------------------------------------------------------------------+
void UpdateEntryLevel()
  {
   if(g_entryStage == 0) return;
   if(PositionsTotal() > 0) return; // one trade at a time

   int lc = g_entry.LastClosedIdx();
   if(lc < 0) return;

   datetime now = g_entry.Time[lc];
   if(!InSessionWindow(now))
     {
      if(g_pendingTicket != 0)
        {
         CancelPendingOrder();
         g_entryEnteredIdx = -1;
         PrintFormat("[ENTRY] %s outside session window -- pending order cancelled for today", TimeToString(now));
        }
      return;
     }

   if(g_entryEnteredIdx == -1)
     {
      if(g_entry.Time[lc] < g_entryWatchStart) return;
      bool inside = (g_entry.H[lc] >= g_confirmZb && g_entry.L[lc] <= g_confirmZt);
      if(!inside) return;
      g_entryEnteredIdx = lc;
      PrintFormat("[ENTRY] %s 5m entered the confirm zone -- trailing %s", TimeToString(now),
                  g_confirmBull ? "buy stop at swing highs" : "sell stop at swing lows");
     }

   int wantKind = g_confirmBull ? 0 : 1; // buy zone -> swing high anchors the stop; sell zone -> swing low
   int bestE = -1;
   for(int e = 0; e < g_entry.evCount; e++)
     {
      if(g_entry.ev[e].confirmIdx < g_entryEnteredIdx) continue;
      if(g_entry.ev[e].kind != wantKind) continue;
      if(bestE == -1 || g_entry.ev[e].confirmIdx > g_entry.ev[bestE].confirmIdx) bestE = e;
     }
   if(bestE == -1) return; // no matching swing yet to anchor the stop on

   double price = g_entry.ev[bestE].price;
   if(g_pendingTicket != 0 && MathAbs(price - g_entrySwingPrice) < _Point) return; // unchanged, nothing to do

   double sl = g_confirmBull ? g_confirmZb : g_confirmZt; // ASSUMPTION: SL at the confirm zone's far boundary
   double riskDist = g_confirmBull ? (price - sl) : (sl - price);
   if(riskDist <= 0) return; // degenerate geometry (zone widened past the swing) -- skip until it resolves
   double tp = g_confirmBull ? price + riskDist * InpRR_Target : price - riskDist * InpRR_Target;
   double lots = CalcLotSize(riskDist, g_confirmBull, price);
   if(lots <= 0) return;

   CancelPendingOrder();
   trade.SetExpertMagicNumber(InpMagic);
   bool ok = g_confirmBull ? trade.BuyStop(lots, price, _Symbol, sl, tp, ORDER_TIME_GTC, 0, "ICT_EA_2")
                            : trade.SellStop(lots, price, _Symbol, sl, tp, ORDER_TIME_GTC, 0, "ICT_EA_2");
   if(ok)
     {
      g_pendingTicket = trade.ResultOrder();
      g_entrySwingPrice = price;
      PrintFormat("[ENTRY] %s placed %s stop @ %f SL=%f TP=%f lots=%f", TimeToString(now),
                  g_confirmBull ? "BUY" : "SELL", price, sl, tp, lots);
     }
   else
     {
      PrintFormat("[ENTRY] %s order placement FAILED: %d %s", TimeToString(now), trade.ResultRetcode(), trade.ResultRetcodeDescription());
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

int OnInit()
  {
   if(InpBiasTF != PERIOD_W1 && InpBiasTF != PERIOD_D1)
      Print("[WARN] InpBiasTF is neither W1 nor D1 -- proceeding anyway, but the spec only covers those two.");
   g_bias.Init(_Symbol, InpBiasTF, InpBiasBars);
   g_confirm.Init(_Symbol, PERIOD_H4, InpH4Bars);
   g_entry.Init(_Symbol, PERIOD_M5, InpM5Bars);
   return(INIT_SUCCEEDED);
  }

void OnTick()
  {
   ManageBreakeven();

   datetime bT = iTime(_Symbol, InpBiasTF, 0);
   datetime h4T = iTime(_Symbol, PERIOD_H4, 0);
   datetime m5T = iTime(_Symbol, PERIOD_M5, 0);

   bool newBias = (bT != g_lastBiasBarTime);
   bool newH4   = (h4T != g_lastH4BarTime);
   bool newM5   = (m5T != g_lastM5BarTime);

   if(newBias) { g_lastBiasBarTime = bT; g_bias.Refresh(); UpdateBiasLevel(); }
   if(newH4)   { g_lastH4BarTime = h4T; g_confirm.Refresh(); UpdateConfirmLevel(); }
   if(newM5)   { g_lastM5BarTime = m5T; g_entry.Refresh(); UpdateEntryLevel(); }
  }
