// SnackbabyA — momentum-12 + trend bias EMA20/50 + timing Stoch K/D
// เข้า: mom เกิน MomMin + ทิศตาม EMA20 vs 50 + K>D อนุญาต buy / K<D อนุญาต sell
// ออก: ชุดแรกเหมือนดั้งเดิม SL + trailing | ถ้า TpUsd>0 ใช้ TP ตายตัวแทน trailing
using cAlgo.API;
using System;
using System.Linq;

[Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.None)]
public class SnackbabyA : Robot
{
    [Parameter("SlUsd", DefaultValue = 5.0)] public double SlUsd { get; set; }
    [Parameter("TrailStep", DefaultValue = 0.3)] public double TrailStep { get; set; }
    [Parameter("TrailOff", DefaultValue = 0.05)] public double TrailOff { get; set; }
    [Parameter("TpUsd", DefaultValue = 0.0)] public double TpUsd { get; set; }
    [Parameter("MomBars", DefaultValue = 12)] public int MomBars { get; set; }
    [Parameter("MomMin", DefaultValue = 2.0)] public double MomMin { get; set; }
    [Parameter("EmaFast", DefaultValue = 20)] public int EmaFast { get; set; }
    [Parameter("EmaSlow", DefaultValue = 50)] public int EmaSlow { get; set; }
    [Parameter("StochLen", DefaultValue = 14)] public int StochLen { get; set; }
    [Parameter("StochK", DefaultValue = 3)] public int StochK { get; set; }
    [Parameter("StochD", DefaultValue = 3)] public int StochD { get; set; }
    [Parameter("UseStochRsi", DefaultValue = false)] public bool UseStochRsi { get; set; }
    [Parameter("UseCross", DefaultValue = false)] public bool UseCross { get; set; }
    [Parameter("UseZScore", DefaultValue = false)] public bool UseZScore { get; set; }
    [Parameter("ZLen", DefaultValue = 50)] public int ZLen { get; set; }
    [Parameter("ZMax", DefaultValue = 2.0)] public double ZMax { get; set; }
    [Parameter("CooldownLosses", DefaultValue = 0)] public int CooldownLosses { get; set; }
    [Parameter("CooldownSignals", DefaultValue = 1)] public int CooldownSignals { get; set; }
    [Parameter("LotDiv", DefaultValue = 10000.0)] public double LotDiv { get; set; }
    [Parameter("MinLot", DefaultValue = 0.01)] public double MinLot { get; set; }
    [Parameter("MaxLot", DefaultValue = 200.0)] public double MaxLot { get; set; }
    [Parameter("UseM5EmaBias", DefaultValue = true)] public bool UseM5EmaBias { get; set; }
    [Parameter("UseDayEma", DefaultValue = false)] public bool UseDayEma { get; set; }
    [Parameter("DayEmaLen", DefaultValue = 50)] public int DayEmaLen { get; set; }
    [Parameter("UseDayStoch", DefaultValue = false)] public bool UseDayStoch { get; set; }
    [Parameter("DayStochLen", DefaultValue = 14)] public int DayStochLen { get; set; }
    [Parameter("DayStochK", DefaultValue = 3)] public int DayStochK { get; set; }
    [Parameter("DayStochD", DefaultValue = 3)] public int DayStochD { get; set; }
    [Parameter("UseBbwGate", DefaultValue = false)] public bool UseBbwGate { get; set; }
    [Parameter("BbwMin", DefaultValue = 0.06)] public double BbwMin { get; set; }
    [Parameter("UseAdxGate", DefaultValue = false)] public bool UseAdxGate { get; set; }
    [Parameter("AdxMin", DefaultValue = 30.0)] public double AdxMin { get; set; }

    private ExponentialMovingAverage _ef, _es, _def;
    private StochasticOscillator _st, _dst;
    private BollingerBands _dbb;
    private DirectionalMovementSystem _dms;
    private RelativeStrengthIndex _rsi;
    private Bars _dbars;
    private int _pendingSide;
    private double _slp;
    private int _lvl;
    private int _lossStreak;
    private int _skipSignals;

    double Vol()
    {
        double lots = Math.Min(Math.Max(MinLot, Account.Equity / LotDiv), MaxLot);
        double u = Symbol.NormalizeVolumeInUnits(lots * Symbol.LotSize, RoundingMode.Down);
        if (u < Symbol.VolumeInUnitsMin) u = Symbol.VolumeInUnitsMin;
        return u;
    }

    protected override void OnStart()
    {
        _ef = Indicators.ExponentialMovingAverage(Bars.ClosePrices, EmaFast);
        _es = Indicators.ExponentialMovingAverage(Bars.ClosePrices, EmaSlow);
        if (UseStochRsi) _rsi = Indicators.RelativeStrengthIndex(Bars.ClosePrices, StochLen);
        else _st = Indicators.StochasticOscillator(StochLen, StochK, StochD, MovingAverageType.Simple);
        if (UseDayEma || UseDayStoch || UseBbwGate || UseAdxGate)
        {
            _dbars = MarketData.GetBars(TimeFrame.Daily);
            if (UseDayEma) _def = Indicators.ExponentialMovingAverage(_dbars.ClosePrices, DayEmaLen);
            if (UseDayStoch) _dst = Indicators.StochasticOscillator(_dbars, DayStochLen, DayStochK, DayStochD, MovingAverageType.Simple);
            if (UseBbwGate) _dbb = Indicators.BollingerBands(_dbars.ClosePrices, 20, 2, MovingAverageType.Simple);
            if (UseAdxGate) _dms = Indicators.DirectionalMovementSystem(_dbars, 14);
        }
        Positions.Closed += OnPosClosed;
        Print("START SnackbabyA VolMin=" + Symbol.VolumeInUnitsMin);
    }

    protected override void OnBar()
    {
        if (_pendingSide != 0)
        {
            if (Positions.Count == 0)
            {
                var tt = _pendingSide == 1 ? TradeType.Buy : TradeType.Sell;
                var r = ExecuteMarketOrder(tt, SymbolName, Vol(), "snackA");
                if (r.IsSuccessful) { _slp = r.Position.EntryPrice - _pendingSide * SlUsd; _lvl = 0; }
                else Print("ORDER FAIL " + r.Error);
            }
            _pendingSide = 0;
        }

        int i = Bars.Count - 2;
        if (i < MomBars + 1) return;
        double mom = Bars.ClosePrices[i] - Bars.ClosePrices[i - MomBars];
        // เกททิศเทรนด์ (AND ทุกชั้นที่เปิด):
        //  UseM5EmaBias = EMA20/50 บน M5 (ปิดเพื่อตัดออกตามสเปก B)
        //  UseDayEma    = ปิดเดย์เหนือ/ใต้ EMA50 เดย์
        //  UseDayStoch  = stoch กราฟวัน K>D / K<D
        bool bull = true, bear = true;
        if (UseM5EmaBias)
        {
            bull &= _ef.Result[i] > _es.Result[i];
            bear &= _ef.Result[i] < _es.Result[i];
        }
        if (UseDayEma)
        {
            int di = _dbars.ClosePrices.Count - 2;
            double dc = _dbars.ClosePrices[di];
            bull &= dc > _def.Result[di];
            bear &= dc < _def.Result[di];
        }
        if (UseDayStoch)
        {
            int di = _dbars.ClosePrices.Count - 2;
            bull &= _dst.PercentK[di] > _dst.PercentD[di];
            bear &= _dst.PercentK[di] < _dst.PercentD[di];
        }
        bool kUp, kDn;
        if (_rsi != null)
        {
            double kd = SrsiKD(i);
            kUp = kd > 0; kDn = kd < 0;
            if (kd < -1e17) { kUp = false; kDn = false; }
        }
        else { kUp = _st.PercentK[i] > _st.PercentD[i]; kDn = _st.PercentK[i] < _st.PercentD[i]; }
        int sig = 0;
        if (UseCross)
        {
            double kd0 = _rsi != null ? SrsiKD(i) : _st.PercentK[i] - _st.PercentD[i];
            double kd1 = _rsi != null ? SrsiKD(i - 1) : _st.PercentK[i - 1] - _st.PercentD[i - 1];
            if (kd1 <= 0 && kd0 > 0 && bull && !ZBlock(1, i)) sig = 1;
            else if (kd1 >= 0 && kd0 < 0 && bear && !ZBlock(-1, i)) sig = -1;
        }
        else if (mom > MomMin && bull && kUp && !ZBlock(1, i)) sig = 1;
        else if (mom < -MomMin && bear && kDn && !ZBlock(-1, i)) sig = -1;
        if (UseBbwGate)
        {
            int di = _dbars.ClosePrices.Count - 2;
            double mid = _dbb.Main[di];
            if (mid > 0 && (_dbb.Top[di] - _dbb.Bottom[di]) / mid < BbwMin) sig = 0;
        }
        if (UseAdxGate && _dms.ADX[_dbars.ClosePrices.Count - 2] < AdxMin) sig = 0;
        if (sig != 0)
        {
            if (_skipSignals > 0) _skipSignals--;
            else _pendingSide = sig;
        }
    }

    bool ZBlock(int side, int i)
    {
        if (!UseZScore || i < ZLen) return false;
        double m = 0, s = 0;
        for (int j = i - ZLen + 1; j <= i; j++) m += Bars.ClosePrices[j];
        m /= ZLen;
        for (int j = i - ZLen + 1; j <= i; j++) { double d = Bars.ClosePrices[j] - m; s += d * d; }
        s = Math.Sqrt(s / ZLen);
        if (s < 1e-12) return false;
        double z = (Bars.ClosePrices[i] - m) / s;
        return side == 1 ? z > ZMax : z < -ZMax;
    }

    void OnPosClosed(PositionClosedEventArgs a)
    {
        if (a.Position.Label != "snackA") return;
        if (a.Position.NetProfit < 0) _lossStreak++;
        else _lossStreak = 0;
        if (CooldownLosses > 0 && _lossStreak >= CooldownLosses)
        {
            _lossStreak = 0;
            _skipSignals = CooldownSignals;
        }
    }

    double SrsiRaw(int i)
    {
        double lo = 1e18, hi = -1e18;
        for (int j = i - StochLen + 1; j <= i; j++)
        {
            double v = _rsi.Result[j];
            if (v < lo) lo = v;
            if (v > hi) hi = v;
        }
        return hi - lo < 1e-12 ? 50 : 100 * (_rsi.Result[i] - lo) / (hi - lo);
    }

    double SrsiKD(int i)
    {
        int n = StochK + StochD - 1;
        if (i - n + 1 - StochLen + 1 < 0) return -1e18;
        double[] raw = new double[n];
        for (int j = 0; j < n; j++) raw[j] = SrsiRaw(i - n + 1 + j);
        double[] k = new double[StochD];
        for (int j = 0; j < StochD; j++)
        {
            double s2 = 0;
            for (int t = 0; t < StochK; t++) s2 += raw[n - 1 - j - t];
            k[StochD - 1 - j] = s2 / StochK;
        }
        double d = 0;
        for (int j = 0; j < StochD; j++) d += k[j];
        return k[StochD - 1] - d / StochD;
    }

    protected override void OnTick()
    {
        var p = Positions.FirstOrDefault(x => x.Label == "snackA");
        if (p == null) return;
        int side = p.TradeType == TradeType.Buy ? 1 : -1;
        double bid = Symbol.Bid;
        double fav = (bid - p.EntryPrice) * side;
        if (TpUsd > 0)
        {
            if (fav >= TpUsd || (side == 1 ? bid <= _slp : bid >= _slp)) ClosePosition(p);
            return;
        }
        while (fav >= (_lvl + 1) * TrailStep)
        {
            double ns = p.EntryPrice + side * ((_lvl + 1) * TrailStep - TrailOff);
            _slp = side == 1 ? Math.Max(_slp, ns) : Math.Min(_slp, ns);
            _lvl++;
        }
        if (side == 1 ? bid <= _slp : bid >= _slp)
            ClosePosition(p);
    }
}
