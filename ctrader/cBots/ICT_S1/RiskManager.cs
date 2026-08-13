// ICT_S1 — RiskManager. Spec: docs/s1_ea_specification.md section 9.
// Fixed % of account BALANCE per trade (confirmed rule -- ignores floating
// P&L on other open positions), normalized to the symbol's real volume
// constraints (master prompt section 42 -- no hard-coded forex-5-digit
// assumptions).

using cAlgo.API;

namespace cAlgo.Robots.ICT_S1
{
    public class RiskManager
    {
        private readonly Symbol _symbol;
        private readonly IAccount _account;
        private readonly double _riskPercent;

        public RiskManager(Symbol symbol, IAccount account, double riskPercent)
        {
            _symbol = symbol;
            _account = account;
            _riskPercent = riskPercent;
        }

        // slDistancePrice: entry-to-stop distance, absolute price units.
        public double ComputeVolume(double slDistancePrice)
        {
            if (slDistancePrice <= 0) return _symbol.VolumeInUnitsMin;

            double riskAmount = _account.Balance * (_riskPercent / 100.0);
            double slPips = slDistancePrice / _symbol.PipSize;
            if (slPips <= 0) return _symbol.VolumeInUnitsMin;

            // Symbol.PipValue = account-currency value of 1 pip for 1 unit
            // of volume -- standard cAlgo risk-sizing formula.
            double rawVolume = riskAmount / (slPips * _symbol.PipValue);
            double normalized = _symbol.NormalizeVolumeInUnits(rawVolume, RoundingMode.Down);

            if (normalized < _symbol.VolumeInUnitsMin) normalized = _symbol.VolumeInUnitsMin;
            if (normalized > _symbol.VolumeInUnitsMax) normalized = _symbol.VolumeInUnitsMax;
            return normalized;
        }
    }
}
