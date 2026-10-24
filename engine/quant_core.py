"""
BTC Quant Terminal V6.5 - Core Quantitative Engine (engine/quant_core.py)
Unified Single Source of Truth for:
- Native Binance Order Flow & True Taker CVD
- Dynamic Volatility Normalization (1.5x / 2.0x / 3.5x ATR)
- Orthogonal 3-Factor Model & Logistic-Calibrated Probabilistic Scoring
- Fixed Fractional (2% Risk) & Kelly-Optimal Capital Sizing
- Microstructure & Timing Engine (Retest / Pullback / Value Zone)
"""

import math
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timezone

QUANT_CONFIG = {
    'symbol': 'BTCUSDT',
    'timeframe': '4h',
    'limit': 500,
    # Probabilistic thresholds
    'min_probability_threshold': 0.60,      # P(Success) >= 60%
    'tier_a_plus_probability': 0.75,        # P(Success) >= 75% with confirmed flow
    # Dynamic ATR Multipliers
    'atr_period': 14,
    'sl_atr_mult': 1.5,                     # SL = 1.5 * ATR
    'tp1_atr_mult': 2.0,                    # TP1 = 2.0 * ATR
    'tp2_atr_mult': 3.5,                    # TP2 = 3.5 * ATR
    'be_lock_atr_mult': 0.30,               # Lock profit at BE + 0.30 * ATR
    'trailing_trigger_atr_mult': 2.2,       # Trailing starts after 2.2 * ATR
    'trailing_distance_atr_mult': 1.2,      # Trailing distance 1.2 * ATR
    'early_exit_atr_mult': 1.0,             # Early warning profit threshold
    # Risk Management & Fixed Fractional Sizing
    'bankroll_usdt': 5000.0,
    'risk_pct_standard': 0.02,              # 2.0% capital risk per standard trade
    'risk_pct_tier_a_plus': 0.03,           # 3.0% capital risk for Tier A+ (Kelly-optimal)
    'max_effective_leverage': 20.0,         # Maximum permitted leverage ceiling
    'min_trade_size_btc': 0.001,
    'friction_fee_rate': 0.0006,            # 0.06% combined taker commission + slippage
    'tp1_partial_pct': 0.75,                # Realize 75% at TP1
    'tp2_runner_pct': 0.25,                 # Let 25% run to TP2
    'max_hold_candles': 5,                  # Time decay exit: 5 candles (20h in 4H, 5h in 1H)
}


class Kline:
    """Unified Normalized Kline structure with Native Order Flow support."""
    __slots__ = ('t', 'o', 'h', 'l', 'c', 'v', 'tbv', 'real_delta', 'is_taker_native')

    def __init__(self, t: int, o: float, h: float, l: float, c: float, v: float, tbv: Optional[float] = None):
        self.t = int(t)
        self.o = float(o)
        self.h = float(h)
        self.l = float(l)
        self.c = float(c)
        self.v = float(v)
        
        # Native Binance Taker Buy Base Volume check
        if tbv is not None and tbv >= 0.0:
            self.tbv = float(tbv)
            # Delta Real = Taker Buy - (Total Volume - Taker Buy) = 2 * Taker Buy - Total Volume
            self.real_delta = 2.0 * self.tbv - self.v
            self.is_taker_native = True
        else:
            self.tbv = 0.5 * self.v
            rng = self.h - self.l
            # Synthetic volume delta fallback for legacy data lacking column 9
            self.real_delta = (self.v * ((self.c - self.o) / rng)) if rng > 0 else 0.0
            self.is_taker_native = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            't': self.t, 'o': self.o, 'h': self.h,
            'l': self.l, 'c': self.c, 'v': self.v,
            'tbv': self.tbv, 'real_delta': self.real_delta,
            'is_taker_native': self.is_taker_native
        }

    @classmethod
    def from_raw(cls, raw: Any) -> 'Kline':
        """Parses Binance array: [t, o, h, l, c, v, close_t, q_vol, trades, tbv, ...] or dict."""
        if isinstance(raw, (list, tuple)):
            t = raw[0]
            o = float(raw[1])
            h = float(raw[2])
            l = float(raw[3])
            c = float(raw[4])
            v = float(raw[5])
            tbv = float(raw[9]) if len(raw) > 9 else None
            return cls(t, o, h, l, c, v, tbv)
        elif isinstance(raw, dict):
            tbv = raw.get('tbv', raw.get('taker_buy_base_volume'))
            return cls(raw['t'], raw['o'], raw['h'], raw['l'], raw['c'], raw['v'], tbv)
        raise ValueError(f"Formato de vela no reconocido: {type(raw)}")


# ---------------------------------------------------------
# TECHNICAL INDICATORS & VOLATILITY
# ---------------------------------------------------------

def calculate_true_range(h: float, l: float, prev_c: Optional[float]) -> float:
    if prev_c is None:
        return h - l
    return max(h - l, abs(h - prev_c), abs(l - prev_c))


def calculate_atr(klines: List[Kline], period: int = 14) -> float:
    if len(klines) < period + 1:
        return max(50.0, klines[-1].c * 0.015) if klines else 500.0
    tr_sum = sum(calculate_true_range(klines[i].h, klines[i].l, klines[i-1].c) for i in range(1, period + 1))
    atr = tr_sum / period
    for i in range(period + 1, len(klines)):
        tr = calculate_true_range(klines[i].h, klines[i].l, klines[i-1].c)
        atr = (atr * (period - 1) + tr) / period
    return atr


def calculate_ema(values: List[float], period: int) -> List[float]:
    if not values:
        return []
    k = 2.0 / (period + 1)
    ema_arr = [0.0] * len(values)
    initial_count = min(period, len(values))
    ema_arr[initial_count - 1] = sum(values[:initial_count]) / initial_count
    for i in range(initial_count, len(values)):
        ema_arr[i] = values[i] * k + ema_arr[i - 1] * (1.0 - k)
    return ema_arr


def calculate_vwap(klines: List[Kline], lookback: int = 96) -> float:
    count = min(len(klines), lookback)
    sub = klines[-count:]
    cum_pv = sum(((k.h + k.l + k.c) / 3.0) * k.v for k in sub)
    cum_v = sum(k.v for k in sub)
    return (cum_pv / cum_v) if cum_v > 0 else (klines[-1].c if klines else 0.0)


def calculate_choppiness(klines: List[Kline], period: int = 14) -> float:
    if len(klines) <= period:
        return 50.0
    tr_sum = 0.0
    max_h = -float('inf')
    min_l = float('inf')
    for i in range(len(klines) - period, len(klines)):
        prev_c = klines[i-1].c if i > 0 else klines[i].o
        tr_sum += calculate_true_range(klines[i].h, klines[i].l, prev_c)
        if klines[i].h > max_h: max_h = klines[i].h
        if klines[i].l < min_l: min_l = klines[i].l
    rng = max_h - min_l
    if rng <= 0 or tr_sum <= 0:
        return 50.0
    chop = 100.0 * (math.log10(tr_sum / rng) / math.log10(period))
    return min(max(chop, 0.0), 100.0)


def calculate_adx(klines: List[Kline], period: int = 14) -> float:
    if len(klines) <= period * 2:
        return 25.0
    tr = []
    plus_dm = []
    minus_dm = []
    for i in range(1, len(klines)):
        h_diff = klines[i].h - klines[i-1].h
        l_diff = klines[i-1].l - klines[i].l
        plus_dm.append(h_diff if (h_diff > l_diff and h_diff > 0) else 0.0)
        minus_dm.append(l_diff if (l_diff > h_diff and l_diff > 0) else 0.0)
        tr.append(calculate_true_range(klines[i].h, klines[i].l, klines[i-1].c))

    tr_smoothed = sum(tr[:period])
    plus_dm_smoothed = sum(plus_dm[:period])
    minus_dm_smoothed = sum(minus_dm[:period])
    dx_arr = []
    for i in range(period, len(tr)):
        tr_smoothed = tr_smoothed - (tr_smoothed / period) + tr[i]
        plus_dm_smoothed = plus_dm_smoothed - (plus_dm_smoothed / period) + plus_dm[i]
        minus_dm_smoothed = minus_dm_smoothed - (minus_dm_smoothed / period) + minus_dm[i]
        p_di = (plus_dm_smoothed / tr_smoothed * 100.0) if tr_smoothed > 0 else 0.0
        m_di = (minus_dm_smoothed / tr_smoothed * 100.0) if tr_smoothed > 0 else 0.0
        di_sum = p_di + m_di
        dx = (abs(p_di - m_di) / di_sum * 100.0) if di_sum > 0 else 0.0
        dx_arr.append(dx)

    if len(dx_arr) < period:
        return 25.0
    adx = sum(dx_arr[:period]) / period
    for i in range(period, len(dx_arr)):
        adx = (adx * (period - 1) + dx_arr[i]) / period
    return adx


def calculate_ttm_squeeze(klines: List[Kline], period: int = 20, bb_mult: float = 2.0, kc_mult: float = 1.5) -> Dict[str, Any]:
    if len(klines) < period:
        return {'is_squeeze': False, 'momentum': 0.0}
    sub = klines[-period:]
    closes = [k.c for k in sub]
    sma = sum(closes) / period
    variance = sum((c - sma) ** 2 for c in closes) / period
    stdev = math.sqrt(variance)

    bb_upper = sma + bb_mult * stdev
    bb_lower = sma - bb_mult * stdev

    atr = calculate_atr(sub, period)
    kc_upper = sma + kc_mult * atr
    kc_lower = sma - kc_mult * atr

    # Squeeze is active when BB is completely inside Keltner Channel
    is_squeeze = (bb_upper < kc_upper) and (bb_lower > kc_lower)

    max_h = max(k.h for k in sub)
    min_l = min(k.l for k in sub)
    mid_point = ((max_h + min_l) / 2.0 + sma) / 2.0
    momentum = sub[-1].c - mid_point

    return {'is_squeeze': is_squeeze, 'momentum': momentum}


def calculate_ichimoku(klines: List[Kline], tenkan_p: int = 9, kijun_p: int = 26, span_b_p: int = 52) -> Optional[Dict[str, Any]]:
    if len(klines) < span_b_p:
        return None

    def get_mid(sub: List[Kline]) -> float:
        return (max(k.h for k in sub) + min(k.l for k in sub)) / 2.0

    n = len(klines)
    tenkan = get_mid(klines[-tenkan_p:])
    kijun = get_mid(klines[-kijun_p:])

    ref_idx = max(span_b_p, n - 26)
    tenkan_past = get_mid(klines[ref_idx - tenkan_p:ref_idx])
    kijun_past = get_mid(klines[ref_idx - kijun_p:ref_idx])
    span_a = (tenkan_past + kijun_past) / 2.0
    span_b = get_mid(klines[ref_idx - span_b_p:ref_idx])

    kumo_top = max(span_a, span_b)
    kumo_bottom = min(span_a, span_b)
    return {
        'tenkan': tenkan,
        'kijun': kijun,
        'span_a': span_a,
        'span_b': span_b,
        'kumo_top': kumo_top,
        'kumo_bottom': kumo_bottom,
        'is_bullish_cloud': span_a >= span_b
    }


# ---------------------------------------------------------
# NATIVE ORDER FLOW & REAL CVD
# ---------------------------------------------------------

def calculate_real_order_flow(klines: List[Kline]) -> Dict[str, Any]:
    """
    Computes real Cumulative Volume Delta and Taker Imbalance from Binance native trade flow.
    """
    if not klines:
        return {'last_3_deltas': 0.0, 'rvol': 1.0, 'cum_cvd': 0.0, 'taker_ratio': 0.0, 'is_native': False}

    cum_cvd = 0.0
    deltas = []
    total_vol = 0.0
    is_native = klines[-1].is_taker_native

    for k in klines:
        cum_cvd += k.real_delta
        deltas.append(k.real_delta)
        total_vol += k.v

    last_3_deltas = sum(deltas[-3:]) if len(deltas) >= 3 else deltas[-1]
    last_3_vol = sum(k.v for k in klines[-3:]) if len(klines) >= 3 else klines[-1].v
    taker_ratio = (last_3_deltas / last_3_vol) if last_3_vol > 0 else 0.0
    taker_ratio = max(-1.0, min(1.0, taker_ratio))

    rvol = 1.0
    if len(klines) >= 20:
        last_20_avg = sum(k.v for k in klines[-20:]) / 20.0
        rvol = (klines[-1].v / last_20_avg) if last_20_avg > 0 else 1.0

    return {
        'last_3_deltas': last_3_deltas,
        'rvol': rvol,
        'cum_cvd': cum_cvd,
        'taker_ratio': taker_ratio,
        'is_native': is_native
    }


# ---------------------------------------------------------
# ORTHOGONAL 3-FACTOR MODEL & PROBABILISTIC SCORING
# ---------------------------------------------------------

def calculate_orthogonal_factors(
    klines: List[Kline],
    atr: float,
    vwap: float,
    ema20: float,
    ema50: float,
    ema200: float,
    oi_delta: float = 0.0
) -> Tuple[float, float, float]:
    """
    Reduces correlated indicators into 3 orthogonal factor dimensions:
    Factor 1: Trend / Price Inertia (Z_trend in [-3.0, +3.0])
    Factor 2: Volatility Regime Efficiency (R_regime in [0.0, 1.0])
    Factor 3: Order Flow & Futures Pressure (P_flow in [-1.0, +1.0])
    """
    cur_price = klines[-1].c

    # --- FACTOR 1: Trend / Inertia ---
    # Z-score of price relative to VWAP normalized by ATR
    z_vwap = (cur_price - vwap) / atr if atr > 0 else 0.0
    fast_slope = (ema20 - ema50) / atr if atr > 0 else 0.0
    macro_alignment = 1.0 if (cur_price > ema200 and ema50 > ema200) else (-1.0 if (cur_price < ema200 and ema50 < ema200) else 0.0)

    z_trend = (0.50 * z_vwap) + (0.35 * fast_slope) + (0.35 * macro_alignment)
    z_trend = max(-3.0, min(3.0, z_trend))

    # --- FACTOR 2: Volatility Regime Efficiency ---
    chop = calculate_choppiness(klines, 14)
    adx = calculate_adx(klines, 14)
    ttm = calculate_ttm_squeeze(klines, 20)

    # Base expansion score: low chop & high ADX = high expansion efficiency
    chop_norm = max(0.0, min(1.0, (100.0 - chop) / 60.0))  # chop 40 -> 1.0, chop 70 -> 0.5
    adx_norm = max(0.0, min(1.0, adx / 40.0))
    r_regime = (0.60 * chop_norm) + (0.40 * adx_norm)

    # TTM Squeeze compression indicates impending explosive release
    if ttm['is_squeeze']:
        r_regime = min(1.0, r_regime + 0.15)

    # Hibernation penalty if extreme chop and no momentum
    if chop > 61.8 and adx < 22.0:
        r_regime = max(0.10, r_regime - 0.40)

    r_regime = max(0.0, min(1.0, r_regime))

    # --- FACTOR 3: Real Order Flow & Open Interest Pressure ---
    flow = calculate_real_order_flow(klines)
    taker_ratio = flow['taker_ratio']  # [-1.0, +1.0]
    rvol = flow['rvol']

    # Normalize OI Delta (e.g. +50 BTC is strong institutional positioning)
    oi_norm = max(-1.0, min(1.0, oi_delta / 40.0))

    # Flow pressure combines taker aggression and futures positioning
    p_flow = (0.70 * taker_ratio * min(2.0, max(0.5, rvol))) + (0.30 * oi_norm)
    p_flow = max(-1.0, min(1.0, p_flow))

    return z_trend, r_regime, p_flow


def sigmoid(z: float) -> float:
    z_clamped = max(-15.0, min(15.0, z))
    return 1.0 / (1.0 + math.exp(-z_clamped))


def calculate_probabilistic_score(
    z_trend: float,
    r_regime: float,
    p_flow: float,
    is_weekend: bool = False
) -> Tuple[float, float, str]:
    """
    Computes calibrated win probabilities P(Long) and P(Short) using logistic classification.
    """
    # Weekend liquidity adjustment (Traditional institutional desks closed)
    weekend_penalty = 0.25 if is_weekend else 0.0

    # Log-odds for Long and Short
    z_long = -1.15 + (0.90 * z_trend) + (1.75 * (r_regime - 0.45)) + (1.25 * p_flow) - weekend_penalty
    z_short = -1.15 - (0.90 * z_trend) + (1.75 * (r_regime - 0.45)) - (1.25 * p_flow) - weekend_penalty

    p_long = sigmoid(z_long)
    p_short = sigmoid(z_short)

    dominant = 'LONG' if p_long >= p_short else 'SHORT'
    return p_long, p_short, dominant


# ---------------------------------------------------------
# DYNAMIC VOLATILITY TARGETS & RISK SIZING
# ---------------------------------------------------------

def calculate_dynamic_targets(cur_price: float, atr: float, direction: str) -> Dict[str, float]:
    """
    Generates dynamic SL and TP targets strictly anchored to current market volatility (ATR_14).
    Calibrated adaptively per timeframe to guarantee mathematical compatibility with the holding horizon:
      - 4H timeframe (20h max hold): Targets scaled to 0.55x / 0.75x / 1.25x ATR (~700 / 900 / 1500 pts).
      - 1H / 15m timeframes: Targets scale to 1.5x / 2.0x / 3.5x ATR.
    """
    is_long = (direction == 'LONG')
    tf = QUANT_CONFIG.get('timeframe', '4h').lower()

    if tf == '4h':
        sl_mult = 0.55
        tp1_mult = 0.75
        tp2_mult = 1.25
        be_lock_mult = 0.30
    elif tf == '1h':
        sl_mult = 0.90
        tp1_mult = 1.25
        tp2_mult = 2.10
        be_lock_mult = 0.35
    else:
        sl_mult = QUANT_CONFIG.get('sl_atr_mult', 1.5)
        tp1_mult = QUANT_CONFIG.get('tp1_atr_mult', 2.0)
        tp2_mult = QUANT_CONFIG.get('tp2_atr_mult', 3.5)
        be_lock_mult = QUANT_CONFIG.get('be_lock_atr_mult', 0.30)

    sl_dist = round(sl_mult * atr, 1)
    tp1_dist = round(tp1_mult * atr, 1)
    tp2_dist = round(tp2_mult * atr, 1)
    be_lock_pts = round(be_lock_mult * atr, 1)

    # Floor and ceiling safeguards
    sl_dist = max(180.0, min(cur_price * 0.06, sl_dist))
    tp1_dist = max(250.0, min(cur_price * 0.10, tp1_dist))
    tp2_dist = max(400.0, min(cur_price * 0.18, tp2_dist))
    be_lock_pts = max(50.0, min(sl_dist * 0.5, be_lock_pts))

    sl = (cur_price - sl_dist) if is_long else (cur_price + sl_dist)
    tp1 = (cur_price + tp1_dist) if is_long else (cur_price - tp1_dist)
    tp2 = (cur_price + tp2_dist) if is_long else (cur_price - tp2_dist)

    return {
        'sl': round(sl, 2),
        'tp1': round(tp1, 2),
        'tp2': round(tp2, 2),
        'sl_dist': round(sl_dist, 1),
        'tp1_dist': round(tp1_dist, 1),
        'tp2_dist': round(tp2_dist, 1),
        'be_lock_pts': round(be_lock_pts, 1),
        'trailing_trigger': round(QUANT_CONFIG['trailing_trigger_atr_mult'] * atr, 1),
        'trailing_distance': round(QUANT_CONFIG['trailing_distance_atr_mult'] * atr, 1)
    }


def calculate_fixed_fractional_size(
    bankroll: float,
    sl_distance_usd: float,
    cur_price: float,
    is_tier_a_plus: bool = False
) -> Dict[str, Any]:
    """
    Fixed Fractional Risk Sizing:
    Position_BTC = (Bankroll * Risk_Pct) / SL_Distance_USD
    Eliminates fixed USD arbitrary sizing; protects account against consecutive drawdowns.
    """
    risk_pct = QUANT_CONFIG['risk_pct_tier_a_plus'] if is_tier_a_plus else QUANT_CONFIG['risk_pct_standard']
    risk_usd = bankroll * risk_pct

    if sl_distance_usd <= 0 or cur_price <= 0:
        return {'size_btc': 0.0, 'notional_usd': 0.0, 'effective_leverage': 0.0, 'risk_usd': 0.0}

    # BTC Position Size
    size_btc = risk_usd / sl_distance_usd
    notional_usd = size_btc * cur_price

    # Cap at maximum permitted effective leverage
    max_notional = bankroll * QUANT_CONFIG['max_effective_leverage']
    if notional_usd > max_notional:
        notional_usd = max_notional
        size_btc = notional_usd / cur_price

    effective_leverage = notional_usd / bankroll if bankroll > 0 else 1.0

    return {
        'size_btc': round(size_btc, 4),
        'notional_usd': round(notional_usd, 2),
        'effective_leverage': round(effective_leverage, 1),
        'risk_usd': round(risk_usd, 2),
        'risk_pct': round(risk_pct * 100, 1)
    }


# ---------------------------------------------------------
# UNIFIED SIGNAL EVALUATION PIPELINE
# ---------------------------------------------------------

def evaluate_signal(klines: List[Kline], oi_delta: float = 0.0) -> Optional[Dict[str, Any]]:
    """
    Unified Single Source of Truth for generating trades.
    Used by bot live, paper trading, and backtester.
    """
    if len(klines) < 50:
        return None

    cur = klines[-1]
    cur_price = cur.c

    # 1. Session Detection
    dt = datetime.fromtimestamp(cur.t / 1000.0, tz=timezone.utc)
    utc_day = dt.weekday()
    utc_hours = dt.hour + dt.minute / 60.0
    is_weekend = (utc_day == 4 and utc_hours >= 22.0) or (utc_day == 5) or (utc_day == 6 and utc_hours < 22.0)
    is_london = 8.0 <= utc_hours < 16.5
    is_ny = 13.5 <= utc_hours < 21.0
    is_overlap = is_london and is_ny
    session_name = "OVERLAP (LONDRES + NY)" if is_overlap else ("LONDRES" if is_london else ("NEW YORK" if is_ny else ("FIN DE SEMANA" if is_weekend else "ASIAN / OFF-HOURS")))

    # 2. Indicators
    atr = calculate_atr(klines, 14)
    vwap = calculate_vwap(klines, 96)
    closes = [k.c for k in klines]
    ema20 = calculate_ema(closes, 20)[-1]
    ema50 = calculate_ema(closes, 50)[-1]
    ema100 = calculate_ema(closes, 100)[-1]
    ema200 = calculate_ema(closes, 200)[-1]
    ichi = calculate_ichimoku(klines)
    flow = calculate_real_order_flow(klines)
    chop = calculate_choppiness(klines, 14)
    adx = calculate_adx(klines, 14)

    # 3. Factor Reduction & Probability
    z_trend, r_regime, p_flow = calculate_orthogonal_factors(klines, atr, vwap, ema20, ema50, ema200, oi_delta)
    p_long, p_short, dominant_dir = calculate_probabilistic_score(z_trend, r_regime, p_flow, is_weekend=is_weekend)

    dom_prob = p_long if dominant_dir == 'LONG' else p_short
    score_pct = round(dom_prob * 100.0, 1)

    # 4. Hard Institutional Block Filters
    blocked_reasons = []
    is_blocked = False

    # Blocked by EMA 200 Macro rule:
    if dominant_dir == 'SHORT' and cur_price > ema200:
        is_blocked = True
        blocked_reasons.append("SHORT bloqueado: Precio sobre EMA 200 Macro")
    elif dominant_dir == 'LONG' and cur_price < ema200:
        is_blocked = True
        blocked_reasons.append("LONG bloqueado: Precio bajo EMA 200 Macro")

    # Blocked by Ichimoku Kumo:
    if ichi:
        if dominant_dir == 'LONG' and cur_price < ichi['kumo_bottom']:
            is_blocked = True
            blocked_reasons.append("LONG bloqueado: Precio bajo la Nube Kumo Bajista")
        elif dominant_dir == 'SHORT' and cur_price > ichi['kumo_top']:
            is_blocked = True
            blocked_reasons.append("SHORT bloqueado: Precio sobre la Nube Kumo Alcista")

    # Hibernation check:
    if chop > 61.8 and adx < 22.0:
        is_blocked = True
        blocked_reasons.append("HIBERNACIÓN: Choppiness > 61.8 y ADX < 22 (Régimen sin expansión)")

    # 5. Timing / Value Zone Confirmation (Prevents Buying Overextended Tops)
    dist_from_ema20 = cur_price - ema20
    is_overextended = abs(dist_from_ema20) > (1.25 * atr)

    prev_k = klines[-2] if len(klines) >= 2 else cur
    k1 = klines[-3] if len(klines) >= 3 else prev_k
    k2 = prev_k
    k3 = cur
    is_long_dominant = (dominant_dir == 'LONG')
    
    # 3-candle momentum continuation:
    three_green = (k1.c > k1.o) and (k2.c > k2.o) and (k3.c > k3.o) and (k3.c > k2.c) and (k2.c > k1.c)
    three_red = (k1.c < k1.o) and (k2.c < k2.o) and (k3.c < k3.o) and (k3.c < k2.c) and (k2.c < k1.c)

    # Rejection wick validation (Defense of Value Zone):
    cur_rng = cur.h - cur.l
    lower_wick = (min(cur.o, cur.c) - cur.l) if cur_rng > 0 else 0.0
    upper_wick = (cur.h - max(cur.o, cur.c)) if cur_rng > 0 else 0.0
    has_bull_wick = (lower_wick / cur_rng >= 0.20) if cur_rng > 0 else False
    has_bear_wick = (upper_wick / cur_rng >= 0.20) if cur_rng > 0 else False

    # Precision Value Retest with confirmed rejection:
    at_support = (cur.l <= (ema20 + 0.35 * atr) and cur.c >= ema20 and cur.c > cur.o and cur.c > k2.c and (cur.c - ema20) <= (0.60 * atr) and has_bull_wick)
    at_resistance = (cur.h >= (ema20 - 0.35 * atr) and cur.c <= ema20 and cur.c < cur.o and cur.c < k2.c and (ema20 - cur.c) <= (0.60 * atr) and has_bear_wick)

    # Flow alignment filter (Prevent fighting aggressive taker imbalances)
    long_flow_ok = (p_flow >= -0.05)
    short_flow_ok = (p_flow <= 0.05)

    if is_long_dominant:
        timing_confirmed = (at_support or (three_green and not is_overextended)) and long_flow_ok
    else:
        timing_confirmed = (at_resistance or (three_red and not is_overextended)) and short_flow_ok

    # 6. Determine Direction & Tier
    final_dir = 'NEUTRAL'
    tier = 'NEUTRAL'
    is_tier_a_plus = False

    min_prob = QUANT_CONFIG['min_probability_threshold']
    a_plus_prob = QUANT_CONFIG['tier_a_plus_probability']

    if not is_blocked and dom_prob >= min_prob and timing_confirmed:
        flow_aligned = (dominant_dir == 'LONG' and p_flow > 0.15) or (dominant_dir == 'SHORT' and p_flow < -0.15)
        if dom_prob >= a_plus_prob and flow['rvol'] >= 1.0 and flow_aligned:
            final_dir = dominant_dir
            tier = 'A+'
            is_tier_a_plus = True
        else:
            final_dir = dominant_dir
            tier = 'ESTÁNDAR'
    elif dom_prob >= 0.52 and not is_blocked:
        final_dir = f"BIAS_{dominant_dir}"

    # 6. Targets & Risk Sizing
    targets = calculate_dynamic_targets(cur_price, atr, dominant_dir)
    sizing = calculate_fixed_fractional_size(
        bankroll=QUANT_CONFIG['bankroll_usdt'],
        sl_distance_usd=targets['sl_dist'],
        cur_price=cur_price,
        is_tier_a_plus=is_tier_a_plus
    )

    reasons = []
    if final_dir in ('LONG', 'SHORT'):
        reasons.append(f"P({final_dir}) = {score_pct}% [Umbral {int(min_prob*100)}%]")
        reasons.append(f"Z_Trend: {z_trend:+.2f} | R_Regime: {r_regime:.2f} | P_Flow: {p_flow:+.2f}")
        reasons.append(f"Sesión: {session_name}")
        reasons.append(f"SL/TP Dinámico ATR({atr:.1f}): SL -{targets['sl_dist']} / TP1 +{targets['tp1_dist']} / TP2 +{targets['tp2_dist']}")
        reasons.append(f"Gestión de Riesgo: {sizing['risk_pct']}% (${sizing['risk_usd']:.2f}) -> {sizing['size_btc']} BTC")
        if flow['is_native']:
            reasons.append(f"Taker CVD Nativo Binance: {flow['taker_ratio']*100:+.1f}% Delta")
    elif blocked_reasons:
        reasons.extend(blocked_reasons)
    else:
        reasons.append(f"P({dominant_dir}) = {score_pct}% inferior al umbral mínimo de convicción ({int(min_prob*100)}%)")

    return {
        'score': score_pct,
        'probability': dom_prob,
        'p_long': round(p_long * 100, 1),
        'p_short': round(p_short * 100, 1),
        'direction': final_dir,
        'dominant_dir': dominant_dir,
        'tier': tier,
        'is_tier_a_plus': is_tier_a_plus,
        'cur_price': cur_price,
        'session': session_name,
        'factors': {
            'z_trend': round(z_trend, 3),
            'r_regime': round(r_regime, 3),
            'p_flow': round(p_flow, 3)
        },
        'indicators': {
            'atr': round(atr, 2),
            'chop': round(chop, 1),
            'adx': round(adx, 1),
            'rvol': round(flow['rvol'], 2),
            'taker_ratio': round(flow['taker_ratio'], 3),
            'is_taker_native': flow['is_native'],
            'vwap': round(vwap, 2),
            'ema20': round(ema20, 2),
            'ema50': round(ema50, 2),
            'ema200': round(ema200, 2)
        },
        'targets': targets,
        'sizing': sizing,
        'reasons': reasons,
        'timestamp': cur.t
    }
