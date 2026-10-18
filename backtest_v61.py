#!/usr/bin/env python3
"""
BTC Quant Terminal V6.1 — Backtest Engine
==========================================
Replica exacta de la lógica de quant_bot_24_7.py
Configuración aplicada en la última sesión de V6.1:
  - Timeframe: 4H | Periodos: 500 velas
  - TP1: 1000 pts (75% cierre parcial) | TP2: 1500 pts (25% runner)
  - SL:  700 pts
  - Break-Even lock: +400 pts
  - Max hold: 5 velas (20 horas)
  - Score mínimo: 68
  - Bankroll: $5,000 | Notional: $20,000 | Leverage: 20x
  - Fee: 35 pts (ida + vuelta)
"""

import os, sys, json, math, urllib.request, urllib.error
from datetime import datetime, timezone

# ─── CONFIGURACIÓN V6.1 ─────────────────────────────────────────────────────
QUANT_CONFIG = {
    'symbol': 'BTCUSDT', 'timeframe': '4h', 'limit': 500,
    'min_score_threshold': 68,
    'atr_multiplier': 1.2,
    'min_stop_loss_pts': 180, 'max_stop_loss_pts': 1500,
    'tp1_atr_multiplier': 1.2, 'tp2_atr_multiplier': 3.6,
    'tp1_pts': 1000, 'tp2_pts': 1500,
    'tp1_partial_pct': 0.75,  # 75% cierre en TP1
    'tp2_runner_pct': 0.25,   # 25% runner hasta TP2
    'break_even_lock_pts': 300,
    'max_hold_candles': 5,
    'friction_fee_pts': 35,
    'bankroll_usdt': 5000.0,
    'trade_notional_usdt': 20000.0,
    'leverage': 20
}

# ─── DATA FETCH ───────────────────────────────────────────────────────────────
def fetch_binance_klines(symbol='BTCUSDT', interval='4h', limit=600):
    endpoints = [
        f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}",
    ]
    for url in endpoints:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'BTCQuantBacktest/6.1'})
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = json.loads(r.read().decode())
                if isinstance(raw, list) and len(raw) > 50:
                    return [{'t': int(k[0]), 'o': float(k[1]), 'h': float(k[2]),
                              'l': float(k[3]), 'c': float(k[4]), 'v': float(k[5])} for k in raw]
        except Exception as e:
            print(f"[WARN] Endpoint falló: {e}")
    return None

# ─── INDICADORES (mismos que quant_bot_24_7.py) ───────────────────────────────
def calculate_tr(h, l, prev_c):
    if prev_c is None: return h - l
    return max(h - l, abs(h - prev_c), abs(l - prev_c))

def calculate_atr(klines, period=14):
    if len(klines) < period + 1: return 500.0
    atr = sum(calculate_tr(klines[i]['h'], klines[i]['l'], klines[i-1]['c']) for i in range(1, period+1)) / period
    for i in range(period+1, len(klines)):
        atr = (atr * (period-1) + calculate_tr(klines[i]['h'], klines[i]['l'], klines[i-1]['c'])) / period
    return atr

def calculate_ema(values, period):
    if not values: return []
    k = 2.0 / (period + 1)
    ema = [0.0] * len(values)
    n = min(period, len(values))
    ema[n-1] = sum(values[:n]) / n
    for i in range(n, len(values)):
        ema[i] = values[i] * k + ema[i-1] * (1 - k)
    return ema

def calculate_choppiness(klines, period=14):
    if len(klines) <= period: return 50.0
    tr_sum = 0.0; max_h = -1e18; min_l = 1e18
    for i in range(len(klines) - period, len(klines)):
        prev_c = klines[i-1]['c'] if i > 0 else klines[i]['o']
        tr_sum += calculate_tr(klines[i]['h'], klines[i]['l'], prev_c)
        if klines[i]['h'] > max_h: max_h = klines[i]['h']
        if klines[i]['l'] < min_l: min_l = klines[i]['l']
    rng = max_h - min_l
    if rng <= 0: return 50.0
    return min(max(100.0 * (math.log10(tr_sum / rng) / math.log10(period)), 0.0), 100.0)

def calculate_adx(klines, period=14):
    if len(klines) <= period * 2: return 25.0
    tr, plus_dm, minus_dm = [], [], []
    for i in range(1, len(klines)):
        hd = klines[i]['h'] - klines[i-1]['h']; ld = klines[i-1]['l'] - klines[i]['l']
        plus_dm.append(hd if (hd > ld and hd > 0) else 0.0)
        minus_dm.append(ld if (ld > hd and ld > 0) else 0.0)
        tr.append(calculate_tr(klines[i]['h'], klines[i]['l'], klines[i-1]['c']))
    tr_s = sum(tr[:period]); p_s = sum(plus_dm[:period]); m_s = sum(minus_dm[:period])
    dx_arr = []
    for i in range(period, len(tr)):
        tr_s = tr_s - tr_s/period + tr[i]
        p_s  = p_s  - p_s/period  + plus_dm[i]
        m_s  = m_s  - m_s/period  + minus_dm[i]
        p_di = (p_s/tr_s*100) if tr_s > 0 else 0.0
        m_di = (m_s/tr_s*100) if tr_s > 0 else 0.0
        dsum = p_di + m_di
        dx_arr.append(abs(p_di - m_di)/dsum*100 if dsum > 0 else 0.0)
    if len(dx_arr) < period: return 25.0
    adx = sum(dx_arr[:period]) / period
    for i in range(period, len(dx_arr)):
        adx = (adx * (period-1) + dx_arr[i]) / period
    return adx

def calculate_rolling_vwap(klines, lookback=96):
    sub = klines[-min(len(klines), lookback):]
    cum_pv = sum(((k['h']+k['l']+k['c'])/3.0)*k['v'] for k in sub)
    cum_v  = sum(k['v'] for k in sub)
    return (cum_pv / cum_v) if cum_v > 0 else klines[-1]['c']

def calculate_rsi(klines, period=14):
    if len(klines) <= period: return 50.0
    g, l = 0.0, 0.0
    for i in range(1, period+1):
        d = klines[i]['c'] - klines[i-1]['c']
        if d >= 0: g += d
        else: l -= d
    ag, al = g/period, l/period
    for i in range(period+1, len(klines)):
        d = klines[i]['c'] - klines[i-1]['c']
        if d >= 0: ag = (ag*(period-1)+d)/period; al = (al*(period-1))/period
        else:       ag = (ag*(period-1))/period;   al = (al*(period-1)-d)/period
    if al == 0: return 100.0
    return 100.0 - (100.0 / (1.0 + ag/al))

def calculate_ichimoku(klines, tenkan_p=9, kijun_p=26, span_b_p=52):
    if len(klines) < span_b_p: return None
    def mid(sub): return (max(k['h'] for k in sub) + min(k['l'] for k in sub)) / 2.0
    n = len(klines)
    ref_idx = max(span_b_p, n - 26)
    span_a = (mid(klines[ref_idx-tenkan_p:ref_idx]) + mid(klines[ref_idx-kijun_p:ref_idx])) / 2.0
    span_b = mid(klines[ref_idx-span_b_p:ref_idx])
    return {
        'kumo_top': max(span_a, span_b), 'kumo_bottom': min(span_a, span_b),
        'tenkan': mid(klines[-tenkan_p:]), 'kijun': mid(klines[-kijun_p:]),
        'is_bullish_cloud': span_a >= span_b
    }

def calculate_ttm_squeeze(klines, period=20, bb_mult=2.0, kc_mult=1.5):
    if len(klines) < period: return {'is_squeeze': False, 'momentum': 0.0}
    sub = klines[-period:]; closes = [k['c'] for k in sub]
    sma = sum(closes)/period; stdev = math.sqrt(sum((c-sma)**2 for c in closes)/period)
    atr = calculate_atr(sub, period)
    bb_up = sma+bb_mult*stdev; bb_lo = sma-bb_mult*stdev
    kc_up = sma+kc_mult*atr;   kc_lo = sma-kc_mult*atr
    is_sq = bb_up < kc_up and bb_lo > kc_lo
    mid_pt = ((max(k['h'] for k in sub)+min(k['l'] for k in sub))/2.0 + sma)/2.0
    return {'is_squeeze': is_sq, 'momentum': sub[-1]['c'] - mid_pt}

def calculate_order_flow(klines):
    deltas = []
    for k in klines:
        rng = k['h']-k['l']
        buy = (k['c']-k['l'])/rng if rng > 0 else 0.5
        sell= (k['h']-k['c'])/rng if rng > 0 else 0.5
        deltas.append(k['v']*(buy-sell))
    last3 = sum(deltas[-3:]) if len(deltas) >= 3 else 0.0
    rvol = 1.0
    if len(klines) >= 20:
        avg20 = sum(k['v'] for k in klines[-20:]) / 20.0
        rvol = klines[-1]['v'] / avg20 if avg20 > 0 else 1.0
    return last3, rvol

# ─── EVALUATE SIGNAL (misma lógica que el bot) ────────────────────────────────
def evaluate_signal(klines):
    if len(klines) < 50: return None
    cur = klines[-1]; cur_price = cur['c']

    # Session Filter (Wall Street / London / Overlap / Weekend)
    day_of_week = dt.weekday() # 5=Sat, 6=Sun
    is_saturday = (day_of_week == 5)
    is_sunday = (day_of_week == 6)

    if is_saturday or (is_sunday and utc_h < 22.0):
        session = 'WEEKEND'
        ss = 0
    elif is_sunday and utc_h >= 22.0:
        session = 'CME_OPEN'
        ss = 6
    else:
        is_london = 8.0 <= utc_h < 16.5
        is_ny = 13.0 <= utc_h < 21.0
        is_overlap = 13.5 <= utc_h < 16.5
        if is_overlap:
            session = 'OVERLAP'
            ss = 15
        elif is_ny:
            session = 'NEWYORK'
            ss = 12
        elif is_london:
            session = 'LONDON'
            ss = 12
        elif 0.0 <= utc_h < 8.0:
            session = 'ASIAN'
            ss = 5
        else:
            session = 'INTERSESSION'
            ss = 3
    ss = min(15, max(0, ss))

    chop = calculate_choppiness(klines, 14)
    adx  = calculate_adx(klines, 14)
    ttm  = calculate_ttm_squeeze(klines, 20)
    atr  = calculate_atr(klines, 14)

    if chop > 61.8 and adx < 22.0:
        return {'score': 0, 'direction': 'HIBERNATION', 'session': session}

    gray_zone = False
    if ttm['is_squeeze']:        acs = 4
    elif adx > 25.0 and chop < 48.0: acs = 15
    elif chop < 52.0:            acs = 12
    elif 55.0 <= chop <= 61.8 and adx < 20.0: acs = 4; gray_zone = True
    else:                        acs = 7
    acs = min(15, acs)

    # ORB (simplificado para backtest: precio vs rolling 30-vela)
    recent = klines[-31:-1]
    orb_high = max(k['h'] for k in recent) if recent else cur_price
    orb_low  = min(k['l'] for k in recent) if recent else cur_price
    lookback = klines[-97:-1]
    h24 = max(k['h'] for k in lookback) if lookback else cur_price
    l24 = min(k['l'] for k in lookback) if lookback else cur_price
    adr_remaining = max(0.0, 2500.0 - (h24 - l24))
    orb_score = 0; long_orb = False; short_orb = False
    if adr_remaining > 700:
        orb_score += 7
        if cur_price > orb_high: long_orb = True; orb_score += 8
        elif cur_price < orb_low: short_orb = True; orb_score += 8
    else: orb_score = 2
    orb_score = min(15, orb_score)

    vwap  = calculate_rolling_vwap(klines, 96)
    closes = [k['c'] for k in klines]
    ema20  = calculate_ema(closes, 20)[-1]
    ema50  = calculate_ema(closes, 50)[-1]
    ema100 = calculate_ema(closes, 100)[-1]
    ema200 = calculate_ema(closes, 200)[-1]
    rsi    = calculate_rsi(klines, 14)

    sl_long = sl_short = 0
    if cur_price > vwap and ema20 > ema50: sl_long += 10
    elif cur_price < vwap and ema20 < ema50: sl_short += 10
    macro_bull = cur_price > ema200 and ema100 > ema200
    macro_bear = cur_price < ema200 and ema100 < ema200
    if macro_bull: sl_long += 8
    elif macro_bear: sl_short += 8

    ichi = calculate_ichimoku(klines)
    ib_long = ib_short = False
    if ichi:
        if cur_price > ichi['kumo_top']:       sl_long += 7; sl_short = max(0, sl_short-18); ib_short = True
        elif cur_price < ichi['kumo_bottom']:  sl_short += 7; sl_long = max(0, sl_long-18);  ib_long = True
        else: sl_long = max(0, sl_long-6); sl_short = max(0, sl_short-6)

    if rsi < 35.0:   sl_long += 5
    elif 40 <= rsi <= 68: sl_long += 3
    elif rsi > 80.0:  sl_long -= 8
    if rsi > 75.0:   sl_short += 5
    elif 32 <= rsi <= 60: sl_short += 3
    elif rsi < 20.0:  sl_short -= 8

    last3 = klines[-4:-1]
    if len(last3) >= 2:
        if sum(1 for k in last3 if k['c'] > k['o']) >= 2: sl_long  += 5
        if sum(1 for k in last3 if k['c'] < k['o']) >= 2: sl_short += 5

    dist20 = cur_price - ema20
    if dist20 > 1.1*atr or rsi > 70: sl_long  = max(0, sl_long  - 10)
    if dist20 < -1.1*atr or rsi < 30: sl_short = max(0, sl_short - 10)
    sl_long  = min(30, max(0, sl_long))
    sl_short = min(30, max(0, sl_short))

    cvd_delta, rvol = calculate_order_flow(klines)
    of_long  = (9 if cvd_delta > 0 else 0) if rvol >= 1.2 else (5 if cvd_delta > 0 else 0)
    of_short = (9 if cvd_delta < 0 else 0) if rvol >= 1.2 else (5 if cvd_delta < 0 else 0)
    of_long  = min(15, max(0, of_long))
    of_short = min(15, max(0, of_short))

    liq_long = liq_short = 0
    rec30 = klines[-31:-1]
    if len(rec30) > 5:
        rh = max(k['h'] for k in rec30); rl = min(k['l'] for k in rec30)
        if cur['l'] < rl and cur['c'] > rl: liq_long  = 6 if (macro_bull or cur_price > ema50) else 2
        if cur['h'] > rh and cur['c'] < rh: liq_short = 6 if (macro_bear or cur_price < ema50) else 2
    liq_long  = min(6, liq_long)
    liq_short = min(6, liq_short)

    total_long  = ss + acs + orb_score + sl_long  + of_long  + liq_long
    total_short = ss + acs + orb_score + sl_short + of_short + liq_short

    is_long_dom = total_long >= total_short
    raw = total_long if is_long_dom else total_short
    score = min(100, round(raw))
    thresh = QUANT_CONFIG['min_score_threshold']

    direction = 'NEUTRAL'
    if score >= thresh: direction = 'LONG' if is_long_dom else 'SHORT'
    elif score >= 45:   direction = 'BIAS_LONG' if is_long_dom else 'BIAS_SHORT'

    # Safety blocks
    if direction == 'LONG'  and ib_long:  direction = 'NEUTRAL'; score = min(score, 40)
    if direction == 'SHORT' and ib_short: direction = 'NEUTRAL'; score = min(score, 40)
    if direction == 'SHORT' and cur_price > ema200: direction = 'NEUTRAL'; score = min(score, 40)
    if direction == 'LONG'  and cur_price < ema200: direction = 'NEUTRAL'; score = min(score, 40)
    if ttm['is_squeeze'] and score >= thresh:
        direction = 'BIAS_LONG' if is_long_dom else 'BIAS_SHORT'; score = thresh - 5
    if abs(total_long-total_short) < 8 and direction in ('LONG','SHORT'):
        direction = 'BIAS_LONG' if is_long_dom else 'BIAS_SHORT'; score = min(score, thresh-3)
    if gray_zone and score < thresh+3 and direction in ('LONG','SHORT'):
        direction = 'BIAS_LONG' if is_long_dom else 'BIAS_SHORT'; score = thresh-4

    # Levels V6.1
    tp1_pts, tp2_pts, sl_pts = 1000, 1500, 700
    is_long_tgt = (direction == 'LONG')
    sl_p  = (cur_price - sl_pts)  if is_long_tgt else (cur_price + sl_pts)
    tp1_p = (cur_price + tp1_pts) if is_long_tgt else (cur_price - tp1_pts)
    tp2_p = (cur_price + tp2_pts) if is_long_tgt else (cur_price - tp2_pts)

    return {
        'score': score, 'direction': direction, 'session': session,
        'cur_price': cur_price, 'sl': sl_p, 'tp1': tp1_p, 'tp2': tp2_p,
        'sl_pts': sl_pts, 'tp1_pts': tp1_pts, 'tp2_pts': tp2_pts,
        'rsi': rsi, 'chop': chop, 'adx': adx, 'atr': atr,
        'ema20': ema20, 'ema50': ema50, 'ema200': ema200, 'vwap': vwap
    }

# ─── BACKTEST ENGINE ──────────────────────────────────────────────────────────
def run_backtest(klines):
    cfg = QUANT_CONFIG
    bankroll    = cfg['bankroll_usdt']
    notional    = cfg['trade_notional_usdt']
    leverage    = cfg['leverage']
    tp1_pct     = cfg['tp1_partial_pct']   # 0.75
    tp2_pct     = cfg['tp2_runner_pct']    # 0.25
    be_lock_pts = cfg['break_even_lock_pts']
    max_hold    = cfg['max_hold_candles']
    fee_pts     = cfg['friction_fee_pts']
    pts_per_usd = notional / klines[0]['c']  # approx BTC per notional

    trades = []
    equity_curve = [bankroll]
    in_trade = False
    entry_sig = None
    entry_idx = None
    be_triggered = False

    WARMUP = 210  # suficiente para EMA200

    for i in range(WARMUP, len(klines)):
        window = klines[:i+1]
        sig = evaluate_signal(window)
        if not sig: continue

        # ── Gestión de trade abierto ──
        if in_trade:
            cur  = klines[i]
            edir = entry_sig['direction']
            ep   = entry_sig['cur_price']
            tp1  = entry_sig['tp1']
            tp2  = entry_sig['tp2']
            sl   = entry_sig['sl']
            hold = i - entry_idx

            is_long = (edir == 'LONG')
            outcome = None; pnl_pts = None

            # Simular precio dentro de la vela (high/low)
            if is_long:
                # TP1 hit?
                if cur['h'] >= tp1:
                    # tp1 75% → tp2 25%
                    tp1_pnl = (tp1 - ep - fee_pts) * tp1_pct
                    runner_sl = ep + be_lock_pts if be_triggered else sl
                    # TP2 hit in same candle?
                    if cur['h'] >= tp2:
                        tp2_pnl = (tp2 - ep - fee_pts) * tp2_pct
                        outcome = 'TP2'; pnl_pts = tp1_pnl + tp2_pnl
                    elif cur['l'] <= runner_sl:
                        tp2_pnl = (runner_sl - ep - fee_pts) * tp2_pct
                        outcome = 'TP1+BE'; pnl_pts = tp1_pnl + tp2_pnl
                    else:
                        # Runner abierto, check SL side
                        outcome = 'TP1_OPEN'; pnl_pts = tp1_pnl  # parcial
                        in_trade = True  # keep
                        be_triggered = True
                        # update SL to break-even
                        entry_sig['sl'] = ep + be_lock_pts
                        entry_sig['partial_done'] = True
                        equity_curve.append(equity_curve[-1])
                        continue
                elif cur['l'] <= sl:
                    pnl_pts = -(entry_sig['sl_pts'] + fee_pts)
                    outcome = 'SL'
                elif hold >= max_hold:
                    pnl_pts = (cur['c'] - ep - fee_pts) * (1.0 if not entry_sig.get('partial_done') else tp2_pct)
                    outcome = 'TIMEOUT'
            else:  # SHORT
                if cur['l'] <= tp1:
                    tp1_pnl = (ep - tp1 - fee_pts) * tp1_pct
                    runner_sl = ep - be_lock_pts if be_triggered else sl
                    if cur['l'] <= tp2:
                        tp2_pnl = (ep - tp2 - fee_pts) * tp2_pct
                        outcome = 'TP2'; pnl_pts = tp1_pnl + tp2_pnl
                    elif cur['h'] >= runner_sl:
                        tp2_pnl = (ep - runner_sl - fee_pts) * tp2_pct
                        outcome = 'TP1+BE'; pnl_pts = tp1_pnl + tp2_pnl
                    else:
                        outcome = 'TP1_OPEN'; pnl_pts = tp1_pnl
                        in_trade = True; be_triggered = True
                        entry_sig['sl'] = ep - be_lock_pts
                        entry_sig['partial_done'] = True
                        equity_curve.append(equity_curve[-1])
                        continue
                elif cur['h'] >= sl:
                    pnl_pts = -(entry_sig['sl_pts'] + fee_pts)
                    outcome = 'SL'
                elif hold >= max_hold:
                    pnl_pts = (ep - cur['c'] - fee_pts) * (1.0 if not entry_sig.get('partial_done') else tp2_pct)
                    outcome = 'TIMEOUT'

            if outcome and pnl_pts is not None:
                # PnL en USD: pts * (notional/price)
                pnl_usd = pnl_pts * (notional / ep)
                new_equity = equity_curve[-1] + pnl_usd
                equity_curve.append(new_equity)
                trades.append({
                    'entry_i': entry_idx, 'exit_i': i,
                    'direction': edir, 'entry': ep,
                    'exit_price': klines[i]['c'], 'outcome': outcome,
                    'pnl_pts': pnl_pts, 'pnl_usd': pnl_usd,
                    'equity': new_equity,
                    'hold_candles': hold,
                    'entry_date': datetime.fromtimestamp(klines[entry_idx]['t']/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M'),
                    'exit_date':  datetime.fromtimestamp(klines[i]['t']/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M'),
                    'score': entry_sig['score'],
                    'rsi': entry_sig['rsi'], 'chop': entry_sig['chop']
                })
                in_trade = False; entry_sig = None; entry_idx = None; be_triggered = False
            else:
                equity_curve.append(equity_curve[-1])

        # ── Buscar nueva entrada ──
        if not in_trade and sig['direction'] in ('LONG', 'SHORT'):
            in_trade = True
            entry_sig = sig
            entry_sig['partial_done'] = False
            entry_idx = i
            equity_curve.append(equity_curve[-1])

    return trades, equity_curve

# ─── ANÁLISIS DE RESULTADOS ──────────────────────────────────────────────────
def analyze(trades, equity_curve, klines):
    if not trades:
        print("\n[!] Sin trades en el período. Score threshold quizá demasiado alto.")
        return

    total = len(trades)
    wins  = [t for t in trades if t['pnl_usd'] > 0]
    loses = [t for t in trades if t['pnl_usd'] <= 0]
    tp2s  = [t for t in trades if t['outcome'] == 'TP2']
    tp1be = [t for t in trades if t['outcome'] == 'TP1+BE']
    sls   = [t for t in trades if t['outcome'] == 'SL']
    touts = [t for t in trades if t['outcome'] == 'TIMEOUT']
    longs = [t for t in trades if t['direction'] == 'LONG']
    shrts = [t for t in trades if t['direction'] == 'SHORT']

    init_eq = QUANT_CONFIG['bankroll_usdt']
    final_eq = equity_curve[-1]
    total_pnl = final_eq - init_eq
    roi_pct = (total_pnl / init_eq) * 100.0
    win_rate = len(wins) / total * 100.0 if total > 0 else 0.0

    avg_win  = sum(t['pnl_usd'] for t in wins)  / len(wins)  if wins  else 0.0
    avg_loss = sum(t['pnl_usd'] for t in loses) / len(loses) if loses else 0.0
    rr_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')

    # Max drawdown
    peak = init_eq; max_dd = 0.0
    for eq in equity_curve:
        if eq > peak: peak = eq
        dd = (peak - eq) / peak * 100.0
        if dd > max_dd: max_dd = dd

    gross_profit = sum(t['pnl_usd'] for t in wins)
    gross_loss   = abs(sum(t['pnl_usd'] for t in loses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    avg_hold = sum(t['hold_candles'] for t in trades) / total

    # Período
    start_dt = klines[0]['t']
    end_dt   = klines[-1]['t']
    n_days   = (end_dt - start_dt) / (1000*3600*24)

    # Sessions breakdown
    session_data = {}
    for t in trades:
        s = entry_sig_lookup(t, klines)
        if s not in session_data: session_data[s] = {'n':0,'wins':0,'pnl':0.0}
        session_data[s]['n'] += 1
        if t['pnl_usd'] > 0: session_data[s]['wins'] += 1
        session_data[s]['pnl'] += t['pnl_usd']

    print("\n" + "═"*65)
    print("  📊  BTC QUANT TERMINAL V6.1 — BACKTEST REPORT")
    print("  Últimas 500 velas 4H  |  Configuración: SL=700 TP1=1000 TP2=1500")
    print("═"*65)
    print(f"  📅  Período: {datetime.fromtimestamp(start_dt/1000,tz=timezone.utc).strftime('%Y-%m-%d')} → {datetime.fromtimestamp(end_dt/1000,tz=timezone.utc).strftime('%Y-%m-%d')} ({n_days:.0f} días)")
    print(f"  💰  Bankroll Inicial:   ${init_eq:,.2f}")
    print(f"  💰  Bankroll Final:     ${final_eq:,.2f}")
    print(f"  📈  ROI Total:          {roi_pct:+.2f}%  (${total_pnl:+,.2f})")
    print(f"  📉  Max Drawdown:       {max_dd:.2f}%")
    print(f"  ⚡  Profit Factor:      {profit_factor:.2f}x")
    print("─"*65)
    print(f"  🔢  Total de Trades:    {total}")
    print(f"  ✅  Win Rate:           {win_rate:.1f}%  ({len(wins)}W / {len(loses)}L)")
    print(f"  🎯  TP2 Full:           {len(tp2s)}  ({len(tp2s)/total*100:.1f}%)")
    print(f"  🛡️  TP1+Break-Even:    {len(tp1be)}  ({len(tp1be)/total*100:.1f}%)")
    print(f"  🔴  Stop-Loss:          {len(sls)}   ({len(sls)/total*100:.1f}%)")
    print(f"  ⏱️  Timeout (20h):     {len(touts)} ({len(touts)/total*100:.1f}%)")
    print(f"  📊  Longs:             {len(longs)}  |  Shorts: {len(shrts)}")
    print("─"*65)
    print(f"  💚  Avg Ganancia:      ${avg_win:+,.2f}")
    print(f"  ❤️  Avg Pérdida:      ${avg_loss:+,.2f}")
    print(f"  ⚖️  Ratio R:R real:   {rr_ratio:.2f}:1")
    print(f"  ⏳  Hold Promedio:     {avg_hold:.1f} velas ({avg_hold*4:.0f}h)")
    print("─"*65)

    # Top 5 best trades
    sorted_best = sorted(trades, key=lambda x: x['pnl_usd'], reverse=True)[:5]
    print("\n  🏆  TOP 5 MEJORES TRADES:")
    for t in sorted_best:
        print(f"    {t['entry_date']} {t['direction']:5s} → {t['outcome']:7s}  PnL: ${t['pnl_usd']:+,.2f}  (Score:{t['score']})")

    # Top 5 worst trades
    sorted_worst = sorted(trades, key=lambda x: x['pnl_usd'])[:5]
    print("\n  💀  TOP 5 PEORES TRADES:")
    for t in sorted_worst:
        print(f"    {t['entry_date']} {t['direction']:5s} → {t['outcome']:7s}  PnL: ${t['pnl_usd']:+,.2f}  (Score:{t['score']})")

    print("\n" + "═"*65)
    print("  📋  ANÁLISIS ROI Y MEJORAS SUGERIDAS")
    print("═"*65)

    suggestions = []

    if win_rate < 50:
        suggestions.append(("🔧 Score Threshold", f"Win rate {win_rate:.1f}% < 50%. Subir min_score_threshold de 68 a 72-75 para filtrar señales marginales."))
    if rr_ratio < 1.5:
        suggestions.append(("🔧 R:R Real Bajo", f"R:R efectivo de {rr_ratio:.2f}:1. Considerar TP1 en 1200 pts o SL en 600 pts para mejorar ratio."))
    if len(sls) / total > 0.40:
        suggestions.append(("🔧 SL Frecuente", f"{len(sls)/total*100:.0f}% de los trades tocan SL. Revisar el ATR-filter: SL de 700 pts puede ser demasiado estrecho en regímenes de alta volatilidad."))
    if avg_hold > 3.5:
        suggestions.append(("🔧 Hold Alto", f"Hold promedio de {avg_hold:.1f} velas. Activar early_exit cuando precio regresa al VWAP en la vela 3 con +300 pts de ganancia."))
    if len(tp2s) / total < 0.15:
        suggestions.append(("🔧 TP2 Escaso", f"Solo {len(tp2s)/total*100:.1f}% de trades llegan a TP2. Reducir TP2 de 1500 a 1200 pts para capturar más extensiones completas."))
    if profit_factor < 1.5:
        suggestions.append(("🔧 Profit Factor Bajo", "Profit Factor < 1.5x. Añadir filtro de sesión estricto: solo operar OVERLAP+LONDON (máximo score 15). Bloquear señales en sesión ASIÁTICA si chop > 55."))
    if max_dd > 20:
        suggestions.append(("⚠️ Drawdown Alto", f"Drawdown de {max_dd:.1f}%. Reducir notional a $15,000 (x15) o implementar pausa de 24h tras 2 SL consecutivos."))

    if not suggestions:
        suggestions.append(("✅ Sistema Sólido", "Todos los KPIs en rangos saludables. Considerar aumentar notional gradualmente a $25,000 si win rate > 55%."))

    for title, desc in suggestions:
        print(f"\n  {title}:")
        print(f"    {desc}")

    print("\n" + "═"*65)
    return {
        'roi_pct': roi_pct, 'total_pnl': total_pnl,
        'win_rate': win_rate, 'max_dd': max_dd,
        'profit_factor': profit_factor, 'rr_ratio': rr_ratio,
        'total_trades': total, 'tp2_count': len(tp2s),
        'sl_count': len(sls), 'suggestions': [s[0] for s in suggestions]
    }

def entry_sig_lookup(t, klines):
    """Retorna sesión aproximada del trade (para agrupación)."""
    dt = datetime.fromtimestamp(klines[t['entry_i']]['t']/1000, tz=timezone.utc)
    h = dt.hour
    if 13 <= h < 17: return 'OVERLAP'
    elif 8 <= h < 16: return 'LONDON'
    elif 13 <= h < 21: return 'NEWYORK'
    return 'ASIAN'

# ─── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("[*] Descargando datos de Binance (últimas 600 velas 4H de BTCUSDT)...")
    klines = fetch_binance_klines('BTCUSDT', '4h', 600)
    if not klines:
        print("[ERROR] No se pudieron obtener datos de Binance.")
        sys.exit(1)

    # Usar exactamente los últimos 500 periodos para el backtest
    klines = klines[-500:]
    print(f"[*] {len(klines)} velas cargadas. Iniciando backtest V6.1...\n")

    trades, equity_curve = run_backtest(klines)
    results = analyze(trades, equity_curve, klines)

    # Guardar resultados en JSON
    out_file = os.path.join(os.path.dirname(__file__), 'backtest_results_v61.json')
    with open(out_file, 'w') as f:
        json.dump({
            'config': QUANT_CONFIG,
            'results': results,
            'trades': trades,
            'equity_curve': equity_curve
        }, f, indent=2, default=str)
    print(f"\n[✓] Resultados guardados en: {out_file}")
