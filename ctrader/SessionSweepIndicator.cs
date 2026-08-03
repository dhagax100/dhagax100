// SessionSweepIndicator.cs -- cTrader (cAlgo) indicator: swing highs/lows + MSS on
// whatever timeframe you apply it to, plus the session-level markings for the
// Asian-sweep / London-reversal strategy this whole project is built around.
//
// HOW TO GET 1m + 5m + 15m ON SCREEN AT ONCE (per your answer):
// this is ONE indicator file, applied as THREE SEPARATE INSTANCES -- drop it on
// your 1-minute chart, again on your 5-minute chart, and again on your
// 15-minute chart. Each instance only ever looks at the bars of the chart it's
// attached to; there is no cross-timeframe fetching here (that's the simpler
// option you picked over a single do-everything overlay).
//
// TIMEZONE (per your answer -- "automatically adapt when time changes"):
// the [Indicator(TimeZone = TimeZones.UTC)] attribute below pins this
// indicator's own Bars.OpenTimes/Server.Time to TRUE UTC, regardless of your
// broker's own server clock (IC Markets' cTrader server time floats on its own
// FX-week schedule, which is NOT the same as US daylight saving). From that
// fixed UTC anchor, ToEastern()/ToUtc() below convert to/from US Eastern time
// using .NET's own "Eastern Standard Time" zone table, which already knows the
// US DST transition dates (2nd Sunday of March, 1st Sunday of November) --
// so EST/EDT flips automatically, forever, with zero manual adjustment, and
// completely independent of whatever timezone quirks IC Markets' own servers
// have. All session-hour PARAMETERS below (Asian start, London start, etc.)
// are always "hour of the day in US Eastern time", exactly matching the
// ASIAN_START_H / LONDON_KZ_START_H / EXTENDED_END_H convention used
// throughout data_pipeline/ in this same project.
//
// WHAT THIS INDICATOR DRAWS:
//   1. Swing highs/lows + MSS (Market Structure Shift) -- same dual-candle
//      swing-detection engine (confirm-on-break, alternation guard) as
//      pine/ICT_Full_OB_v24.pine and ctrader/ICT_EA_1.cs, just the swing/MSS
//      part on its own (no order blocks/FVGs -- you didn't ask for those here).
//      Swings/MSS are confirmed ONLY on bar CLOSE (via Bars.BarOpened), not
//      updated tick-by-tick on the still-forming bar. That's a deliberate,
//      transparent choice: it trades a few seconds/minutes of "instant"
//      reactivity for zero repainting -- once a swing or MSS mark is drawn, it
//      never moves or disappears again.
//   2. Asian session range box (red, lightly shaded) -- the high/low of the
//      Asian session (default 20:00-00:00 EST), boxed in price and time.
//   3. AH/AL lines (red) -- horizontal rays from the Asian high/low. Each
//      ray keeps extending forward in time while its own cycle is still
//      "live", and FREEZES (stops extending) at whichever of these happens
//      first:
//        - its own level gets swept AND the OPPOSITE Asian level is then
//          reached ("target impact") -- freezes exactly at the target-impact
//          bar (this is the "full cycle" case: sweep, then reversal all the
//          way to the other side).
//        - the session resolution deadline (default 12:00 EST -- the exact
//          EXTENDED_END_H cutoff your 737-day backtest uses) arrives without
//          that full cycle completing -- freezes there instead. This covers
//          BOTH of your "if one side is not swept or impacted" cases (never
//          swept at all, OR swept but target never reached) with one rule.
//   4. Frankfurt + London killzone box (blue, lightly shaded) -- Frankfurt
//      (1 hour before London killzone start) through the London killzone's
//      own end. Default 01:00-05:00 EST (Frankfurt start=1, killzone
//      start=2, killzone end=5 -- the same LONDON_KZ_START_H/LONDON_KZ_END_H
//      convention used throughout data_pipeline/ in this project). VERIFIED
//      against your own research: IC Markets server 08:00-12:00 -> (server
//      is UTC+3 in summer, 7h ahead of EDT) -> EST/EDT 01:00-05:00. Same
//      match.
//   5. Asian range pips label -- printed right at the bottom of each day's
//      Asian box, in bold, the instant the Asian session closes.
//
// PDH/PDL: REMOVED per your request (for now) -- was drawing yesterday's
// daily high/low; deleted cleanly rather than left commented out. Easy to
// re-add later if you want it back (git history has the removed version).
//
// "Poorly shaded" is read here as "lightly/semi-transparently shaded" -- the
// Asian Box Alpha / Frankfurt-London Box Alpha parameters (0-255, low
// default) control exactly how faint the fill is.
//
// SESSION HOURS -- VERIFIED against your IC Markets web research:
//   - Asian: you found IC Markets server 03:00-07:00 = New York 20:00-00:00.
//     Checking the math: IC Markets' cTrader server runs UTC+3 in summer
//     (northern-hemisphere DST period); EDT (NY summer) is UTC-4; the gap
//     between them is 7 hours. NY 20:00 EDT = 00:00 UTC (next day) = 03:00
//     server (UTC+3). NY 00:00 EDT (next day) = 04:00 UTC = 07:00 server.
//     That's an exact match to what you found -- confirms InpAsianStartHourEst
//     (default 20, i.e. 20:00-00:00 EST) was already correct. No change made.
//   - Frankfurt+London: you found IC Markets server 09:00-12:00 for London,
//     08:00-12:00 once you add the Frankfurt hour before it. Same UTC+3-vs-
//     EDT math: server 08:00 = EST/EDT 01:00, server 12:00 = EST/EDT 05:00.
//     That's Frankfurt start 01:00 EST through killzone end 05:00 EST --
//     which is exactly LONDON_KZ_START_H=2/LONDON_KZ_END_H=5 (killzone) plus
//     one Frankfurt hour before it. This DIRECTLY CONTRADICTS my previous fix
//     in this file, which invented a narrower "London's own first hour"
//     concept (2 hours: 01:00-03:00 EST) instead of the full killzone (4
//     hours: 01:00-05:00 EST) -- that previous fix is reverted below; the box
//     is back to being anchored on London killzone start/end, which turns out
//     to have been the right concept all along, it was just missing an
//     explicit "killzone end" parameter (added now).
//   - Daylight saving: handled automatically already (see ToEastern/ToUtc
//     above) -- nothing broker-specific needed. Since the indicator is pinned
//     to true UTC and converts straight to real US Eastern time via .NET's
//     own DST-aware zone table, it does not matter at all what IC Markets'
//     own server offset is on any given day (UTC+2 in winter, UTC+3 in
//     summer, or anything else) -- the EST-anchored hours above stay correct
//     through every DST transition, on this broker or any other.
//
// COMPATIBILITY: standard cAlgo.API C#, targets the same cAlgo Automate API
// surface already used (and, per your prior sessions, working) in
// ctrader/ICT_EA_1.cs in this same folder -- Chart.DrawRectangle/DrawTrendLine/
// DrawText, Bars.BarOpened. Paste into cTrader's Automate editor as a new
// Indicator (not a Robot/cBot).
//
// THREE CALLS I COULD NOT FULLY VERIFY against the official reference
// (help.ctrader.com and the cTrader forum both blocked automated fetches while
// writing this) -- check these first if it doesn't compile:
//   - Color.FromArgb(int alpha, Color baseColor): standard in .NET's own
//     System.Drawing.Color, which cAlgo's Color struct is modeled on, but I could
//     not confirm cAlgo exposes this exact overload. If it doesn't compile, use
//     Color.FromArgb(alpha, baseColor.R, baseColor.G, baseColor.B) instead.
//   - ChartText.IsBold / .FontSize: ICT_EA_1.cs's own DrawText calls never set
//     these, so I have no first-hand confirmation they exist on this API version.
//     If they don't compile, just delete those two lines -- the label still
//     draws, only slightly smaller/non-bold.
//   - Chart.DrawTrendLine(name, t1, y1, t2, y2, color): DrawRectangle/DrawText
//     are both copied from confirmed, already-working calls in ICT_EA_1.cs;
//     DrawTrendLine is NOT used anywhere in that file, so its exact argument
//     order/overload here is inferred by analogy with DrawRectangle, not
//     confirmed first-hand. If it doesn't compile, check whether it wants a
//     trailing thickness argument (like DrawRectangle does) or a different
//     argument order.
//
// SWING/MSS MARKER OFFSET FIX: you reported swing arrows and MSS crosses
// landing on the wrong (usually the next) candle after I switched them from
// Chart.DrawIcon to Chart.DrawText for size control. The (time, price) data
// fed to both calls never changed -- DrawIcon apparently centers an icon on
// its given point, while DrawText's default anchor does not (confirmed: the
// cAlgo forum shows ChartText exposes a settable .HorizontalAlignment, and an
// older overload takes VerticalAlignment/HorizontalAlignment as explicit
// arguments -- i.e. DrawText is NOT centered by default). Fixed by explicitly
// setting mark.HorizontalAlignment = HorizontalAlignment.Center and
// mark.VerticalAlignment = VerticalAlignment.Center on every swing/MSS text
// object below. VerticalAlignment/HorizontalAlignment themselves ARE
// confirmed to exist in this API (ICT_EA_1.cs's own Chart.DrawStaticText call
// already uses them), but the specific ".Center" member of each enum is not
// independently confirmed -- if it doesn't compile, try ".Middle" instead of
// ".Center" for VerticalAlignment.

using System;
using System.Collections.Generic;
using cAlgo.API;

namespace cAlgo.Indicators
{
    [Indicator(IsOverlay = true, TimeZone = TimeZones.UTC, AccessRights = AccessRights.None)]
    public class SessionSweepIndicator : Indicator
    {
        // ============================== PARAMETERS ==============================
        [Parameter("Asian session start (hour, 0-23, US Eastern time)", DefaultValue = 20, MinValue = 0, MaxValue = 23,
            Group = "Session hours (US Eastern time -- auto DST, see file header)")]
        public int InpAsianStartHourEst { get; set; }

        [Parameter("London killzone start (hour, 0-23, US Eastern time) -- feeds AH/AL AND is the Frankfurt/London box's own killzone start",
            DefaultValue = 2, MinValue = 0, MaxValue = 23, Group = "Session hours (US Eastern time -- auto DST, see file header)")]
        public int InpLondonStartHourEst { get; set; }

        [Parameter("London killzone end (hour, 0-23, US Eastern time) -- the Frankfurt/London box's own end (verified: matches IC Markets server 08:00-12:00)",
            DefaultValue = 5, MinValue = 0, MaxValue = 23, Group = "Session hours (US Eastern time -- auto DST, see file header)")]
        public int InpLondonKzEndHourEst { get; set; }

        [Parameter("Session resolution deadline (hour, 0-23, US Eastern time) -- if a side hasn't fully swept + hit target by this hour, its line freezes here. Defaults to the same EXTENDED_END_H cutoff the backtest uses.",
            DefaultValue = 12, MinValue = 0, MaxValue = 23, Group = "Session hours (US Eastern time -- auto DST, see file header)")]
        public int InpSessionDeadlineHourEst { get; set; }

        [Parameter("Only draw sessions from this many calendar days back (0 = all loaded history)", DefaultValue = 60, MinValue = 0,
            Group = "Session hours (US Eastern time -- auto DST, see file header)")]
        public int InpHistoryDaysBack { get; set; }

        [Parameter("Show swing highs/lows", DefaultValue = true, Group = "Display toggles")]
        public bool InpShowSwings { get; set; }

        [Parameter("Show MSS marks", DefaultValue = true, Group = "Display toggles")]
        public bool InpShowMss { get; set; }

        [Parameter("Show Asian range box", DefaultValue = true, Group = "Display toggles")]
        public bool InpShowAsianBox { get; set; }

        [Parameter("Show AH/AL sweep lines", DefaultValue = true, Group = "Display toggles")]
        public bool InpShowAhAl { get; set; }

        [Parameter("Show Frankfurt + London killzone box", DefaultValue = true, Group = "Display toggles")]
        public bool InpShowFrankfurtLondonBox { get; set; }

        [Parameter("Show Asian range pips label", DefaultValue = true, Group = "Display toggles")]
        public bool InpShowAsianPips { get; set; }

        [Parameter("Swing high color", DefaultValue = "Blue", Group = "Colors")]
        public Color InpSwingHighColor { get; set; }

        [Parameter("Swing low color", DefaultValue = "Black", Group = "Colors")]
        public Color InpSwingLowColor { get; set; }

        [Parameter("MSS up color (blue cross, price flips down-to-up)", DefaultValue = "Blue", Group = "Colors")]
        public Color InpMssUpColor { get; set; }

        [Parameter("MSS down color (black cross, price flips up-to-down)", DefaultValue = "Black", Group = "Colors")]
        public Color InpMssDownColor { get; set; }

        [Parameter("Swing marker font size (tiny = 6-8)", DefaultValue = 7, MinValue = 4, MaxValue = 24, Group = "Colors")]
        public int InpSwingMarkerFontSize { get; set; }

        [Parameter("MSS marker font size", DefaultValue = 8, MinValue = 4, MaxValue = 24, Group = "Colors")]
        public int InpMssMarkerFontSize { get; set; }

        [Parameter("Asian box / AH-AL line color", DefaultValue = "Red", Group = "Colors")]
        public Color InpAsianColor { get; set; }

        [Parameter("Asian box fill alpha (0-255, low = poorly/lightly shaded)", DefaultValue = 35, MinValue = 0, MaxValue = 255, Group = "Colors")]
        public int InpAsianBoxAlpha { get; set; }

        [Parameter("Frankfurt + London box color", DefaultValue = "DodgerBlue", Group = "Colors")]
        public Color InpFrankLondonColor { get; set; }

        [Parameter("Frankfurt + London box fill alpha (0-255, low = poorly/lightly shaded)", DefaultValue = 35, MinValue = 0, MaxValue = 255, Group = "Colors")]
        public int InpFrankLondonBoxAlpha { get; set; }

        [Parameter("Asian pips label color", DefaultValue = "White", Group = "Colors")]
        public Color InpPipsLabelColor { get; set; }

        // ============================== TIMEZONE HELPERS ==============================
        // Resolved once. Tries the Windows zone ID first (what cAlgo's own hosting
        // normally runs on); falls back to the IANA ID for any non-Windows host --
        // either way this is the real US-Eastern zone with its own correct, automatic
        // EST/EDT DST rules, never a fixed manual offset.
        private static readonly TimeZoneInfo EasternTz = ResolveEasternTimeZone();

        private static TimeZoneInfo ResolveEasternTimeZone()
        {
            try { return TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time"); }
            catch (TimeZoneNotFoundException) { return TimeZoneInfo.FindSystemTimeZoneById("America/New_York"); }
        }

        // Bars.OpenTimes here are true UTC (forced by [Indicator(TimeZone = TimeZones.UTC)]).
        private DateTime ToEastern(DateTime utc) => TimeZoneInfo.ConvertTimeFromUtc(DateTime.SpecifyKind(utc, DateTimeKind.Utc), EasternTz);
        private DateTime ToUtc(DateTime est) => TimeZoneInfo.ConvertTimeToUtc(DateTime.SpecifyKind(est, DateTimeKind.Unspecified), EasternTz);

        // ============================== TRADING-DAY BOUNDARIES ==============================
        // "Trading day D" spans Asian start (D-1 at InpAsianStartHourEst:00 EST) through
        // D's own session deadline -- same anchor as ASIAN_START_H=20 (prior day) in the
        // Python backtest pipeline. A bar in the evening (hour >= Asian start hour)
        // already belongs to TOMORROW's trading day by this convention.
        private DateTime GetTradingDay(DateTime est) => est.Hour >= InpAsianStartHourEst ? est.Date.AddDays(1) : est.Date;
        private DateTime AsianStart(DateTime tradingDay) => tradingDay.AddDays(-1).AddHours(InpAsianStartHourEst);
        private DateTime AsianEnd(DateTime tradingDay) => tradingDay; // midnight EST
        private DateTime LondonStart(DateTime tradingDay) => tradingDay.AddHours(InpLondonStartHourEst); // killzone start
        private DateTime LondonKzEnd(DateTime tradingDay) => tradingDay.AddHours(InpLondonKzEndHourEst); // killzone end
        private DateTime SessionDeadline(DateTime tradingDay) => tradingDay.AddHours(InpSessionDeadlineHourEst);

        // Frankfurt = 1 hour before the SAME London killzone used for AH/AL above
        // (reverted from a previous, mistaken "separate real-calendar session"
        // redesign -- see the file header's SESSION HOURS note for the verified
        // math showing this coupling was actually correct all along).
        private DateTime FrankfurtStart(DateTime tradingDay) => LondonStart(tradingDay).AddHours(-1);

        // ============================== SWING/MSS ENGINE STATE ==============================
        private struct SwEv { public int ConfirmIdx; public int Kind; public int SwingIdx; public double Price; } // Kind: 0=high,1=low
        // MSS is drawn at the BROKEN SWING's own (SwingIdx, Price) -- exactly where
        // pine/ICT_Full_OB_v24.pine's label.new(x=swhIdx, y=swhPrice, ...) puts it --
        // never at the breaking candle itself. See StepBar() for why.
        private struct MssEv { public int SwingIdx; public double Price; public bool Bullish; }

        private readonly List<SwEv> _ev = new List<SwEv>();
        private readonly List<MssEv> _mss = new List<MssEv>();
        private int _peakIdx, _troughIdx;
        private bool _haveSwh, _haveSwl;
        private double _swhPrice, _swlPrice;
        private int _swhIdx, _swlIdx;
        private int _regime; // 0 warmup, 1 up, 2 down
        private int _ei;     // how many _ev entries have been OFFICIALLY armed (STEP2) so far
        private int _evDrawn, _mssDrawn;
        private DateTime _historyCutoffUtc; // DateTime.MinValue = draw everything loaded

        private double O(int i) => Bars.OpenPrices[i];
        private double H(int i) => Bars.HighPrices[i];
        private double L(int i) => Bars.LowPrices[i];
        private double C(int i) => Bars.ClosePrices[i];
        private DateTime T(int i) => Bars.OpenTimes[i];

        private void AddEv(int confirmIdx, int kind, int swingIdx, double price)
        {
            _ev.Add(new SwEv { ConfirmIdx = confirmIdx, Kind = kind, SwingIdx = swingIdx, Price = price });
        }

        // One bar's worth of the swing-detection + regime/MSS step. Identical rules to
        // OBEngine.Refresh() in ICT_EA_1.cs (dual-candle swing confirm, alternation
        // guard, MSS = the swing break that actually flips/establishes the regime),
        // minus the order-block/FVG machinery this indicator doesn't need.
        private void StepBar(int i)
        {
            bool bullish = C(i) >= O(i);
            bool breaksPrevHigh = H(i) > H(i - 1);
            bool breaksPrevLow = L(i) < L(i - 1);
            bool dualAction = breaksPrevHigh && breaksPrevLow;

            bool prevDual = false;
            if (_ev.Count >= 2)
            {
                bool diffKinds = _ev[_ev.Count - 1].Kind != _ev[_ev.Count - 2].Kind;
                bool sameConfirm = _ev[_ev.Count - 1].ConfirmIdx == _ev[_ev.Count - 2].ConfirmIdx;
                bool wasLastCandle = _ev[_ev.Count - 1].ConfirmIdx == i - 1;
                prevDual = diffKinds && sameConfirm && wasLastCandle;
            }
            bool blockPostDual = prevDual && !dualAction;

            if (!bullish)
            {
                if (H(i) > H(_peakIdx)) _peakIdx = i;
                if (breaksPrevHigh)
                {
                    bool lastWasLow = _ev.Count > 0 && _ev[_ev.Count - 1].Kind == 1;
                    if (!lastWasLow && !blockPostDual) { AddEv(i, 1, _troughIdx, L(_troughIdx)); _peakIdx = i; }
                }
                if (L(i) < L(_troughIdx)) _troughIdx = i;
                if (breaksPrevLow)
                {
                    bool lastWasHigh = _ev.Count > 0 && _ev[_ev.Count - 1].Kind == 0;
                    if (!lastWasHigh && !blockPostDual) { AddEv(i, 0, _peakIdx, H(_peakIdx)); _troughIdx = i; }
                }
            }
            else
            {
                if (L(i) < L(_troughIdx)) _troughIdx = i;
                if (breaksPrevLow)
                {
                    bool lastWasHigh = _ev.Count > 0 && _ev[_ev.Count - 1].Kind == 0;
                    if (!lastWasHigh && !blockPostDual) { AddEv(i, 0, _peakIdx, H(_peakIdx)); _troughIdx = i; }
                }
                if (H(i) > H(_peakIdx)) _peakIdx = i;
                if (breaksPrevHigh)
                {
                    bool lastWasLow = _ev.Count > 0 && _ev[_ev.Count - 1].Kind == 1;
                    if (!lastWasLow && !blockPostDual) { AddEv(i, 1, _troughIdx, L(_troughIdx)); _peakIdx = i; }
                }
            }

            // Regime/MSS step -- a faithful trim of OBEngine.Refresh()'s per-bar loop
            // in ICT_EA_1.cs (same file, lines ~345-512), keeping its exact branch
            // ORDER (this matters: a bearish candle break-checks the armed swing HIGH
            // using last bar's price, THEN arms whatever this bar just confirmed, THEN
            // break-checks the armed swing LOW using whatever price is current AT THAT
            // POINT -- which may be a value this same bar just armed, on purpose, so a
            // same-bar cascade can fire without waiting a full extra bar. A bullish
            // candle runs the mirror order (low break, arm, high break). Collapsing
            // this into a single order-independent pass -- what an earlier draft of
            // this file did -- silently changes which price a same-bar break-check
            // compares against, so it is NOT done here; every line below matches the
            // original 1:1, just without the order-block/FVG bookkeeping this
            // indicator has no use for) -- only regime/MSS and the swing arm state.
            //
            // MSS recording (the bug you spotted): pine/ICT_Full_OB_v24.pine only ever
            // draws a label on the "else if" branch -- regime 2->1 (a genuine down-to-
            // up flip) or 1->2 (up-to-down) -- and NEVER on the plain "if regime==0"
            // branch, which is just the engine's FIRST-EVER regime establishing itself
            // out of warmup, not a real reversal. My first draft fired an MSS event on
            // ANY regime change, including that initial 0->1/0->2 warmup case, which is
            // why you saw far more MSS marks than the reference indicator. Fixed by
            // recording MSS only inside the matching "else if" branch below.
            //
            // Placement (the other half of the bug): pine draws the label at
            // (swhIdx, swhPrice) / (swlIdx, swlPrice) -- the ORIGINAL broken swing's own
            // bar and price -- not at the breaking candle. So the MSS event is recorded
            // using _swhIdx/_swhPrice (or _swlIdx/_swlPrice) captured INSIDE the break
            // check itself, before the mid-arm loop right below it has a chance to
            // overwrite those same fields with a brand-new swing confirmed on this same
            // bar.
            bool swhConsumed = false, swlConsumed = false;

            if (!bullish)
            {
                if (_haveSwh && H(i) > _swhPrice)
                {
                    if (_regime == 0) _regime = 1;
                    else if (_regime == 2)
                    {
                        _mss.Add(new MssEv { SwingIdx = _swhIdx, Price = _swhPrice, Bullish = true });
                        _regime = 1;
                    }
                    _haveSwh = false; swhConsumed = true;
                }
                for (int peek = _ei; peek < _ev.Count && _ev[peek].ConfirmIdx == i; peek++)
                {
                    if (_ev[peek].Kind == 0) { _haveSwh = true; _swhPrice = _ev[peek].Price; _swhIdx = _ev[peek].SwingIdx; }
                    else { _haveSwl = true; _swlPrice = _ev[peek].Price; _swlIdx = _ev[peek].SwingIdx; }
                }
                if (_haveSwl && L(i) < _swlPrice)
                {
                    if (_regime == 0) _regime = 2;
                    else if (_regime == 1)
                    {
                        _mss.Add(new MssEv { SwingIdx = _swlIdx, Price = _swlPrice, Bullish = false });
                        _regime = 2;
                    }
                    _haveSwl = false; swlConsumed = true;
                }
            }
            else
            {
                if (_haveSwl && L(i) < _swlPrice)
                {
                    if (_regime == 0) _regime = 2;
                    else if (_regime == 1)
                    {
                        _mss.Add(new MssEv { SwingIdx = _swlIdx, Price = _swlPrice, Bullish = false });
                        _regime = 2;
                    }
                    _haveSwl = false; swlConsumed = true;
                }
                for (int peek = _ei; peek < _ev.Count && _ev[peek].ConfirmIdx == i; peek++)
                {
                    if (_ev[peek].Kind == 0) { _haveSwh = true; _swhPrice = _ev[peek].Price; _swhIdx = _ev[peek].SwingIdx; }
                    else { _haveSwl = true; _swlPrice = _ev[peek].Price; _swlIdx = _ev[peek].SwingIdx; }
                }
                if (_haveSwh && H(i) > _swhPrice)
                {
                    if (_regime == 0) _regime = 1;
                    else if (_regime == 2)
                    {
                        _mss.Add(new MssEv { SwingIdx = _swhIdx, Price = _swhPrice, Bullish = true });
                        _regime = 1;
                    }
                    _haveSwh = false; swhConsumed = true;
                }
            }

            // Officially arm this bar's events (guarded by *Consumed so a swing that
            // was JUST used to fire a break above this same bar doesn't get
            // immediately re-armed from its own confirming event) and advance _ei for
            // real -- the peeks above only looked ahead without consuming.
            while (_ei < _ev.Count && _ev[_ei].ConfirmIdx == i)
            {
                if (_ev[_ei].Kind == 0)
                {
                    if (!swhConsumed) { _haveSwh = true; _swhPrice = _ev[_ei].Price; _swhIdx = _ev[_ei].SwingIdx; }
                }
                else
                {
                    if (!swlConsumed) { _haveSwl = true; _swlPrice = _ev[_ei].Price; _swlIdx = _ev[_ei].SwingIdx; }
                }
                _ei++;
            }
        }

        private void DrawSwingsAndMss()
        {
            // The history-back bound only limits what's actually DRAWN here, never
            // what StepBar() processes (see ProcessClosedBar) -- the engine's running
            // peak/trough/armed-swing/regime state has to see every bar from the very
            // start of loaded history to stay correct; skipping ahead would leave it
            // initialized from the wrong point and produce wrong swings/MSS henceforth.
            if (InpShowSwings)
            {
                // Chart.DrawIcon has no size argument -- ChartIconType renders at a
                // fixed size the API doesn't expose a way to shrink (confirmed: neither
                // ICT_EA_1.cs's own icon calls nor the official reference show a size
                // parameter). Chart.DrawText's FontSize is the only sizing knob cAlgo
                // actually gives an indicator, so "tiny arrows" means switching to a
                // small text glyph instead of a fixed-size icon.
                for (int i = _evDrawn; i < _ev.Count; i++)
                {
                    var e = _ev[i];
                    DateTime t = T(e.SwingIdx);
                    if (t >= _historyCutoffUtc)
                    {
                        bool isHigh = e.Kind == 0;
                        var mark = Chart.DrawText($"sw_{i}", isHigh ? "▲" : "▼", t, e.Price, isHigh ? InpSwingHighColor : InpSwingLowColor);
                        mark.FontSize = InpSwingMarkerFontSize;
                        // Centers the glyph exactly ON (t, e.Price) -- DrawText is NOT
                        // centered by default (that's the "next candle" offset bug you
                        // reported); see the file header for what's confirmed vs not.
                        mark.HorizontalAlignment = HorizontalAlignment.Center;
                        mark.VerticalAlignment = VerticalAlignment.Center;
                    }
                }
                _evDrawn = _ev.Count;
            }
            if (InpShowMss)
            {
                // Cross mark ("x"), same as pine's label.style_xcross -- drawn at the
                // BROKEN SWING's own (SwingIdx, Price), matching the reference exactly
                // (see the long comment in StepBar() for why this needed fixing).
                for (int i = _mssDrawn; i < _mss.Count; i++)
                {
                    var m = _mss[i];
                    DateTime t = T(m.SwingIdx);
                    if (t >= _historyCutoffUtc)
                    {
                        var mark = Chart.DrawText($"mss_{i}", "x", t, m.Price, m.Bullish ? InpMssUpColor : InpMssDownColor);
                        mark.FontSize = InpMssMarkerFontSize;
                        mark.IsBold = true;
                        mark.HorizontalAlignment = HorizontalAlignment.Center;
                        mark.VerticalAlignment = VerticalAlignment.Center;
                    }
                }
                _mssDrawn = _mss.Count;
            }
        }

        // ============================== SESSION/DAY STATE ==============================
        private class DayState
        {
            public double AsianHigh = double.NegativeInfinity, AsianLow = double.PositiveInfinity;
            public bool AsianAnyBar;
            public bool AsianClosed;   // Asian window has fully closed -- AH/AL are now fixed
            public bool PipsLabelDrawn;

            public bool AhSwept, AhTargetHit, AhFrozen;
            public bool AlSwept, AlTargetHit, AlFrozen;

            public double FlHigh = double.NegativeInfinity, FlLow = double.PositiveInfinity;
            public bool FlAnyBar, FlClosed;
        }
        private readonly Dictionary<DateTime, DayState> _days = new Dictionary<DateTime, DayState>();

        private DayState GetOrCreateDay(DateTime tradingDay)
        {
            if (!_days.TryGetValue(tradingDay, out var d)) { d = new DayState(); _days[tradingDay] = d; }
            return d;
        }

        private void UpdateAsianSession(DayState day, DateTime tradingDay, int i, DateTime est)
        {
            DateTime start = AsianStart(tradingDay), end = AsianEnd(tradingDay);
            if (est >= start && est < end)
            {
                day.AsianAnyBar = true;
                if (H(i) > day.AsianHigh) day.AsianHigh = H(i);
                if (L(i) < day.AsianLow) day.AsianLow = L(i);
                if (InpShowAsianBox)
                {
                    var rect = Chart.DrawRectangle($"asianbox_{tradingDay:yyyyMMdd}", ToUtc(start), day.AsianHigh, T(i), day.AsianLow,
                        Color.FromArgb(InpAsianBoxAlpha, InpAsianColor), 1);
                    rect.IsFilled = true;
                }
            }
            else if (est >= end && !day.AsianClosed && day.AsianAnyBar)
            {
                day.AsianClosed = true;
                if (InpShowAsianBox)
                {
                    var rect = Chart.DrawRectangle($"asianbox_{tradingDay:yyyyMMdd}", ToUtc(start), day.AsianHigh, ToUtc(end), day.AsianLow,
                        Color.FromArgb(InpAsianBoxAlpha, InpAsianColor), 1);
                    rect.IsFilled = true;
                }
                if (InpShowAsianPips && !day.PipsLabelDrawn)
                {
                    double pips = (day.AsianHigh - day.AsianLow) / Symbol.PipSize;
                    var text = Chart.DrawText($"asianpips_{tradingDay:yyyyMMdd}", $"Asian Range: {pips:F1} pips", ToUtc(end), day.AsianLow, InpPipsLabelColor);
                    text.IsBold = true;
                    text.FontSize = 12;
                    day.PipsLabelDrawn = true;
                }
            }
        }

        // AH's job is to get swept (High > AsianHigh), then the day's target is AL
        // (Low <= AsianLow) -- and mirrored for AL. Each line keeps extending to "now"
        // while its own cycle is still unresolved, and freezes the moment either (a)
        // it's swept AND the opposite level is then reached ("target impact"), or
        // (b) the session deadline passes without that -- covering both of your
        // "not swept" / "swept but not impacted" cases with the same freeze rule.
        private void UpdateAhAlLines(DayState day, DateTime tradingDay, int i, DateTime est)
        {
            if (!InpShowAhAl || !day.AsianClosed) return;
            DateTime end = AsianEnd(tradingDay), deadline = SessionDeadline(tradingDay);
            if (est < end) return;
            // FIX: the previous version early-returned on "est > deadline" BEFORE the
            // freeze-at-deadline draw below could ever run, so a line that never got
            // swept/impacted just silently stopped growing at whatever the last
            // pre-deadline bar happened to be (never marked frozen, never redrawn with
            // its right edge pinned exactly at the deadline) -- part of what you saw
            // as "random" lines not stopping cleanly. Fixed: we still enter below for
            // bars past the deadline too, so the frozen-at-deadline draw actually fires.
            bool pastDeadline = est >= deadline;

            if (!day.AhFrozen)
            {
                if (!pastDeadline)
                {
                    if (!day.AhSwept && H(i) > day.AsianHigh) day.AhSwept = true;
                    if (day.AhSwept && !day.AhTargetHit && L(i) <= day.AsianLow) day.AhTargetHit = true;
                }
                bool freezeNow = day.AhTargetHit || pastDeadline;
                DateTime rightEdge = day.AhTargetHit ? T(i) : (pastDeadline ? ToUtc(deadline) : T(i));
                Chart.DrawTrendLine($"ah_{tradingDay:yyyyMMdd}", ToUtc(end), day.AsianHigh, rightEdge, day.AsianHigh, InpAsianColor);
                if (freezeNow) day.AhFrozen = true;
            }

            if (!day.AlFrozen)
            {
                if (!pastDeadline)
                {
                    if (!day.AlSwept && L(i) < day.AsianLow) day.AlSwept = true;
                    if (day.AlSwept && !day.AlTargetHit && H(i) >= day.AsianHigh) day.AlTargetHit = true;
                }
                bool freezeNow = day.AlTargetHit || pastDeadline;
                DateTime rightEdge = day.AlTargetHit ? T(i) : (pastDeadline ? ToUtc(deadline) : T(i));
                Chart.DrawTrendLine($"al_{tradingDay:yyyyMMdd}", ToUtc(end), day.AsianLow, rightEdge, day.AsianLow, InpAsianColor);
                if (freezeNow) day.AlFrozen = true;
            }
        }

        // Frankfurt through the London killzone's own end -- default 01:00-05:00 EST
        // (verified against IC Markets server 08:00-12:00, see file header).
        private void UpdateFrankfurtLondonBox(DayState day, DateTime tradingDay, int i, DateTime est)
        {
            if (!InpShowFrankfurtLondonBox) return;
            DateTime start = FrankfurtStart(tradingDay), end = LondonKzEnd(tradingDay);
            if (est >= start && est < end)
            {
                day.FlAnyBar = true;
                if (H(i) > day.FlHigh) day.FlHigh = H(i);
                if (L(i) < day.FlLow) day.FlLow = L(i);
                var rect = Chart.DrawRectangle($"flbox_{tradingDay:yyyyMMdd}", ToUtc(start), day.FlHigh, T(i), day.FlLow,
                    Color.FromArgb(InpFrankLondonBoxAlpha, InpFrankLondonColor), 1);
                rect.IsFilled = true;
            }
            else if (est >= end && !day.FlClosed && day.FlAnyBar)
            {
                day.FlClosed = true;
                var rect = Chart.DrawRectangle($"flbox_{tradingDay:yyyyMMdd}", ToUtc(start), day.FlHigh, ToUtc(end), day.FlLow,
                    Color.FromArgb(InpFrankLondonBoxAlpha, InpFrankLondonColor), 1);
                rect.IsFilled = true;
            }
        }

        private void ProcessClosedBar(int i)
        {
            // StepBar always runs, for every bar from the start of loaded history --
            // the swing engine's peak/trough/armed-swing/regime state has to see every
            // bar to stay correct. The history-back bound below only decides whether we
            // bother tracking/drawing SESSION boxes/lines this far back; it must never
            // gate StepBar itself (that would leave the engine mid-initialized).
            StepBar(i);
            DrawSwingsAndMss();

            if (T(i) < _historyCutoffUtc) return;

            DateTime est = ToEastern(T(i));
            DateTime tradingDay = GetTradingDay(est);
            var day = GetOrCreateDay(tradingDay);

            UpdateAsianSession(day, tradingDay, i, est);
            UpdateAhAlLines(day, tradingDay, i, est);
            UpdateFrankfurtLondonBox(day, tradingDay, i, est);
        }

        // ============================== LIFECYCLE ==============================
        protected override void Initialize()
        {
            Bars.BarOpened += OnBarOpened;

            // Server.Time is already true UTC here because of [Indicator(TimeZone =
            // TimeZones.UTC)] above -- no separate "TimeInUtc" property needed/assumed.
            _historyCutoffUtc = InpHistoryDaysBack > 0 ? Server.Time.AddDays(-InpHistoryDaysBack) : DateTime.MinValue;

            // Backfill: reprocess ALL loaded history once so past sessions are visible
            // immediately, same as ICT_EA_1.cs's baseline Refresh() call in OnStart().
            // The still-forming last bar is deliberately NOT processed here (see the
            // file header note on no-repaint-by-design).
            for (int i = 1; i <= Bars.Count - 2; i++)
                ProcessClosedBar(i);
        }

        private void OnBarOpened(BarOpenedEventArgs args)
        {
            int justClosed = Bars.Count - 2; // -1 is the new bar that just opened (forming)
            if (justClosed >= 1) ProcessClosedBar(justClosed);
        }

        public override void Calculate(int index)
        {
            // All real work happens in OnBarOpened (once per closed bar) -- see the
            // file header for why the still-forming bar is intentionally left alone.
        }
    }
}
