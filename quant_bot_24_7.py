#!/usr/bin/env python3
"""
BTC Quant Terminal V6.1 - 24/7 Cloud Guardian Engine
Autonomous Headless Engine for GitHub Actions & VPS
Monitors Bitcoin (BTC/USDT) every 10 minutes in the cloud and sends real-time Telegram alerts
Target: Capture expansions of 1,200 to 1,500 points (USD) in Long/Short
"""

import os
import sys
import json
import math
import urllib.request
import urllib.error
from datetime import datetime, timezone

# 1. CONFIGURATION & CREDENTIALS
# Priority: Environment Variables (GitHub Secrets) -> Fallback to preconfigured credentials
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8635759809:AAF8YTMVkbVizhe2V7ciw_QtOktDqapJWo4').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '159239770').strip()
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

QUANT_CONFIG = {
    'symbol': 'BTCUSDT',
    'timeframe': '15m',
    'limit': 500,
    'min_score_threshold': 75,
    'atr_multiplier': 1.55,
    'min_stop_loss_pts': 450,
    'max_stop_loss_pts': 750,
    'tp1_pts': 750,
    'tp2_pts': 1350,
    'break_even_lock_pts': 50,
    'early_exit_min_profit_pts': 450,
    'friction_fee_pts': 95
}

STATE_FILE = 'state.json'
LAST_ALERT_FILE = 'last_alert.json'

# 2. TELEGRAM DISPATCHER
def send_telegram_alert(text):
    print(f"[TELEGRAM] Enviando alerta a {TELEGRAM_CHAT_ID}...")
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': text,
        'parse_mode': 'HTML'
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        TELEGRAM_API_URL,
        data=data,
        headers={'Content-Type': 'application/json', 'User-Agent': 'BTCQuantGuardian/6.1'}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            res_data = json.loads(resp.read().decode('utf-8'))
            if res_data.get('ok'):
                print("[TELEGRAM] Alerta entregada con éxito a @MrProezas.")
                return True
            else:
                print(f"[TELEGRAM] Error respuesta Telegram: {res_data}")
                return False
    except Exception as e:
        print(f"[TELEGRAM ERROR] No se pudo enviar mensaje: {e}")
        return False

# 3. BINANCE DATA FETCHING
def fetch_binance_klines():
    endpoints = [
        f"https://data-api.binance.vision/api/v3/klines?symbol={QUANT_CONFIG['symbol']}&interval={QUANT_CONFIG['timeframe']}&limit={QUANT_CONFIG['limit']}",
        f"https://api.binance.com/api/v3/klines?symbol={QUANT_CONFIG['symbol']}&interval={QUANT_CONFIG['timeframe']}&limit={QUANT_CONFIG['limit']}",
        f"https://api1.binance.com/api/v3/klines?symbol={QUANT_CONFIG['symbol']}&interval={QUANT_CONFIG['timeframe']}&limit={QUANT_CONFIG['limit']}"
    ]

    for url in endpoints:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'BTCQuantGuardian/6.1'})
            with urllib.request.urlopen(req, timeout=12) as response:
                raw = json.loads(response.read().decode('utf-8'))
                if isinstance(raw, list) and len(raw) > 50:
                    klines = []
                    for k in raw:
                        klines.append({
                            't': int(k[0]),
                            'o': float(k[1]),
                            'h': float(k[2]),
                            'l': float(k[3]),
                            'c': float(k[4]),
                            'v': float(k[5])
                        })
                    print(f"[DATA] {len(klines)} velas cargadas con éxito desde {url.split('/')[2]}")
                    return klines
        except Exception as e:
            print(f"[DATA WARN] Falló endpoint {url}: {e}")
            continue

    print("[DATA ERROR] No se pudieron obtener velas de ningún endpoint de Binance.")
    return None

# 4. QUANTITATIVE INDICATOR CALCULATIONS
def calculate_tr(h, l, prev_c):
    if prev_c is None:
        return h - l
    return max(h - l, abs(h - prev_c), abs(l - prev_c))

def calculate_atr(klines, period=14):
    if len(klines) < period + 1:
        return 500.0
    tr_sum = sum(calculate_tr(klines[i]['h'], klines[i]['l'], klines[i-1]['c']) for i in range(1, period + 1))
    atr = tr_sum / period
    for i in range(period + 1, len(klines)):
        tr = calculate_tr(klines[i]['h'], klines[i]['l'], klines[i-1]['c'])
        atr = (atr * (period - 1) + tr) / period
    return atr

def calculate_ema(values, period):
    if not values:
        return []
    k = 2.0 / (period + 1)
    ema_arr = [0.0] * len(values)
    initial_count = min(period, len(values))
    ema_arr[initial_count - 1] = sum(values[:initial_count]) / initial_count
    for i in range(initial_count, len(values)):
        ema_arr[i] = values[i] * k + ema_arr[i - 1] * (1 - k)
    return ema_arr

def calculate_choppiness(klines, period=14):
    if len(klines) <= period:
        return 50.0
    sub = klines[-period:]
    tr_sum = 0.0
    max_h = -float('inf')
    min_l = float('inf')
    for i in range(len(klines) - period, len(klines)):
        prev_c = klines[i-1]['c'] if i > 0 else klines[i]['o']
        tr_sum += calculate_tr(klines[i]['h'], klines[i]['l'], prev_c)
        if klines[i]['h'] > max_h: max_h = klines[i]['h']
        if klines[i]['l'] < min_l: min_l = klines[i]['l']
    rng = max_h - min_l
    if rng <= 0:
        return 50.0
    chop = 100.0 * (math.log10(tr_sum / rng) / math.log10(period))
    return min(max(chop, 0.0), 100.0)

def calculate_adx(klines, period=14):
    if len(klines) <= period * 2:
        return 25.0
    tr = []
    plus_dm = []
    minus_dm = []
    for i in range(1, len(klines)):
        h_diff = klines[i]['h'] - klines[i-1]['h']
        l_diff = klines[i-1]['l'] - klines[i]['l']
        plus_dm.append(h_diff if (h_diff > l_diff and h_diff > 0) else 0.0)
        minus_dm.append(l_diff if (l_diff > h_diff and l_diff > 0) else 0.0)
        tr.append(calculate_tr(klines[i]['h'], klines[i]['l'], klines[i-1]['c']))

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

def calculate_rolling_vwap(klines, lookback=96):
    count = min(len(klines), lookback)
    sub = klines[-count:]
    cum_pv = sum(((k['h'] + k['l'] + k['c']) / 3.0) * k['v'] for k in sub)
    cum_v = sum(k['v'] for k in sub)
    return (cum_pv / cum_v) if cum_v > 0 else klines[-1]['c']

def calculate_order_flow(klines):
    deltas = []
    cum_cvd = 0.0
    for k in klines:
        rng = k['h'] - k['l']
        buy_ratio = (k['c'] - k['l']) / rng if rng > 0 else 0.5
        sell_ratio = (k['h'] - k['c']) / rng if rng > 0 else 0.5
        delta = k['v'] * (buy_ratio - sell_ratio)
        deltas.append(delta)
        cum_cvd += delta

    last_3_deltas = sum(deltas[-3:]) if len(deltas) >= 3 else 0.0
    rvol = 1.0
    if len(klines) >= 20:
        last_20_vol = sum(k['v'] for k in klines[-20:]) / 20.0
        cur_vol = klines[-1]['v']
        rvol = (cur_vol / last_20_vol) if last_20_vol > 0 else 1.0
    return last_3_deltas, rvol, cum_cvd

def calculate_rsi(klines, period=14):
    if len(klines) <= period:
        return 50.0
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        diff = klines[i]['c'] - klines[i-1]['c']
        if diff >= 0: gains += diff
        else: losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(klines)):
        diff = klines[i]['c'] - klines[i-1]['c']
        if diff >= 0:
            avg_gain = (avg_gain * (period - 1) + diff) / period
            avg_loss = (avg_loss * (period - 1)) / period
        else:
            avg_gain = (avg_gain * (period - 1)) / period
            avg_loss = (avg_loss * (period - 1) - diff) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def calculate_orb(klines):
    if not klines:
        return 0, 0, False
    latest_time = klines[-1]['t']
    dt = datetime.fromtimestamp(latest_time / 1000.0, tz=timezone.utc)
    day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start_ms = int(day_start.timestamp() * 1000)
    orb_end_ms = day_start_ms + 8 * 3600 * 1000

    orb_high = -float('inf')
    orb_low = float('inf')
    found = False
    for k in klines:
        if day_start_ms <= k['t'] <= orb_end_ms:
            found = True
            if k['h'] > orb_high: orb_high = k['h']
            if k['l'] < orb_low: orb_low = k['l']
    return (orb_high if found else klines[0]['h']), (orb_low if found else klines[0]['l']), found

def calculate_adr_fuel(klines):
    lookback = min(len(klines), 96)
    sub = klines[-lookback:]
    h_24h = max(k['h'] for k in sub)
    l_24h = min(k['l'] for k in sub)
    consumed = h_24h - l_24h
    benchmark = 2500.0
    remaining = max(0.0, benchmark - consumed)
    return consumed, remaining

# 5. PREDICTIVE ENTRY ENGINE (0 - 100 PTS CONFLUENCE)
def evaluate_signal(klines):
    if len(klines) < 50:
        return None
    cur = klines[-1]
    cur_price = cur['c']

    # 1. Session Filter
    dt = datetime.fromtimestamp(cur['t'] / 1000.0, tz=timezone.utc)
    utc_hours = dt.hour + dt.minute / 60.0
    is_weekend = dt.weekday() in (5, 6)

    is_london = 8.0 <= utc_hours < 16.5
    is_ny = 13.5 <= utc_hours < 21.0
    is_overlap = is_london and is_ny

    session_name = 'ASIAN'
    session_score = 5
    if is_overlap:
        session_name = 'OVERLAP (LONDRES + NY)'
        session_score = 20
    elif is_london:
        session_name = 'LONDRES'
        session_score = 15
    elif is_ny:
        session_name = 'NEW YORK'
        session_score = 15

    if is_weekend:
        session_score = max(0, session_score - 10)

    # 2. Anti-Chop Regime Detector
    chop = calculate_choppiness(klines, 14)
    adx = calculate_adx(klines, 14)
    if chop > 61.8 and adx < 22.0:
        return {
            'score': 0,
            'direction': 'HIBERNATION',
            'session': session_name,
            'chop': chop,
            'adx': adx,
            'reasons': ['MODO HIBERNACIÓN: Choppiness > 61.8 y ADX < 22 (Mercado sucio sin expansión)']
        }

    anti_chop_score = 15 if (chop < 45.0 or adx > 25.0) else 8

    # 3. ORB Box & ADR 24h Fuel
    orb_high, orb_low, orb_active = calculate_orb(klines)
    adr_consumed, adr_remaining = calculate_adr_fuel(klines)
    orb_score = 0
    long_orb = False
    short_orb = False

    if adr_remaining > 700:
        orb_score += 10
        if orb_active and cur_price > orb_high:
            long_orb = True
            orb_score += 10
        elif orb_active and cur_price < orb_low:
            short_orb = True
            orb_score += 10
    else:
        orb_score = 2

    # 4. VWAP 24h + EMA 20/50/100/200 + RSI(14)
    vwap = calculate_rolling_vwap(klines, 96)
    closes = [k['c'] for k in klines]
    ema20 = calculate_ema(closes, 20)[-1]
    ema50 = calculate_ema(closes, 50)[-1]
    ema100 = calculate_ema(closes, 100)[-1]
    ema200 = calculate_ema(closes, 200)[-1]
    rsi = calculate_rsi(klines, 14)

    structure_score_long = 0
    structure_score_short = 0

    if cur_price > vwap and ema20 > ema50:
        structure_score_long += 12
    elif cur_price < vwap and ema20 < ema50:
        structure_score_short += 12

    macro_bull = cur_price > ema200 and ema100 > ema200
    macro_bear = cur_price < ema200 and ema100 < ema200
    if macro_bull: structure_score_long += 8
    elif macro_bear: structure_score_short += 8

    if 38.0 <= rsi <= 68.0: structure_score_long += 5
    elif rsi < 30.0: structure_score_long += 8
    elif rsi > 80.0: structure_score_long -= 8

    if 32.0 <= rsi <= 62.0: structure_score_short += 5
    elif rsi > 70.0: structure_score_short += 8
    elif rsi < 20.0: structure_score_short -= 8

    structure_score_long = max(0, structure_score_long)
    structure_score_short = max(0, structure_score_short)

    # 5. Order Flow (CVD + RVOL)
    cvd_delta, rvol, _ = calculate_order_flow(klines)
    of_score_long = (15 if cvd_delta > 0 else 0) if rvol >= 1.2 else (8 if cvd_delta > 0 else 0)
    of_score_short = (15 if cvd_delta < 0 else 0) if rvol >= 1.2 else (8 if cvd_delta < 0 else 0)

    # 6. Liquidation Sweeps & SFP
    recent = klines[-30:-1]
    liq_score_long = 0
    liq_score_short = 0
    if len(recent) > 5:
        r_high = max(k['h'] for k in recent)
        r_low = min(k['l'] for k in recent)
        if cur['l'] < r_low and cur['c'] > r_low: liq_score_long = 20
        if cur['h'] > r_high and cur['c'] < r_high: liq_score_short = 20

    total_long = session_score + anti_chop_score + orb_score + structure_score_long + of_score_long + liq_score_long
    total_short = session_score + anti_chop_score + orb_score + structure_score_short + of_score_short + liq_score_short

    direction = 'NEUTRAL'
    final_score = 0
    reasons = []

    if total_long >= total_short and total_long >= 50:
        direction = 'LONG'
        final_score = min(100, total_long)
        if session_score >= 15: reasons.append(f"Sesión {session_name}")
        if anti_chop_score >= 10: reasons.append(f"Régimen Expansivo (Chop {chop:.1f})")
        if long_orb: reasons.append("Ruptura Cajón ORB")
        if cur_price > vwap and ema20 > ema50: reasons.append("Precio > VWAP & EMA 20 > 50")
        if macro_bull: reasons.append("Macro Alcista (Precio > EMA 100/200)")
        reasons.append(f"RSI(14): {rsi:.1f}")
        if of_score_long >= 10: reasons.append(f"CVD Comprador (+{round(cvd_delta)} BTC)")
        if liq_score_long > 0: reasons.append("Barrido de Liquidez SFP Alcista")
    elif total_short > total_long and total_short >= 50:
        direction = 'SHORT'
        final_score = min(100, total_short)
        if session_score >= 15: reasons.append(f"Sesión {session_name}")
        if anti_chop_score >= 10: reasons.append(f"Régimen Expansivo (Chop {chop:.1f})")
        if short_orb: reasons.append("Ruptura Cajón ORB")
        if cur_price < vwap and ema20 < ema50: reasons.append("Precio < VWAP & EMA 20 < 50")
        if macro_bear: reasons.append("Macro Bajista (Precio < EMA 100/200)")
        reasons.append(f"RSI(14): {rsi:.1f}")
        if of_score_short >= 10: reasons.append(f"CVD Vendedor ({round(cvd_delta)} BTC)")
        if liq_score_short > 0: reasons.append("Barrido de Liquidez SFP Bajista")

    atr = calculate_atr(klines, 14)
    sl_dist = round(QUANT_CONFIG['atr_multiplier'] * atr)
    sl_dist = max(QUANT_CONFIG['min_stop_loss_pts'], min(QUANT_CONFIG['max_stop_loss_pts'], sl_dist))

    sl = (cur_price - sl_dist) if direction == 'LONG' else (cur_price + sl_dist)
    tp1 = (cur_price + QUANT_CONFIG['tp1_pts']) if direction == 'LONG' else (cur_price - QUANT_CONFIG['tp1_pts'])
    tp2 = (cur_price + QUANT_CONFIG['tp2_pts']) if direction == 'LONG' else (cur_price - QUANT_CONFIG['tp2_pts'])

    return {
        'score': final_score,
        'direction': direction,
        'reasons': reasons,
        'session': session_name,
        'cur_price': cur_price,
        'sl': sl,
        'sl_pts': sl_dist,
        'tp1': tp1,
        'tp2': tp2,
        'tp2_pts': QUANT_CONFIG['tp2_pts'],
        'rsi': rsi,
        'chop': chop,
        'adx': adx,
        'timestamp': cur['t']
    }

# 6. DYNAMIC POSITION GUARDIAN (State Monitor)
def monitor_cloud_position(cur_price, klines):
    if not os.path.exists(STATE_FILE):
        return
    try:
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
    except Exception:
        return

    pos = state.get('open_position')
    if not pos:
        return

    is_long = pos['direction'] == 'LONG'
    pts = (cur_price - pos['entry_price']) if is_long else (pos['entry_price'] - cur_price)

    # 1. TP1 (+750 pts)
    if not pos.get('tp1_hit') and pts >= QUANT_CONFIG['tp1_pts']:
        pos['tp1_hit'] = True
        pos['sl'] = (pos['entry_price'] + QUANT_CONFIG['break_even_lock_pts']) if is_long else (pos['entry_price'] - QUANT_CONFIG['break_even_lock_pts'])
        msg = (
            f"🎯 <b>TP1 ALCANZADO (+750 PTS) [CLOUD GUARDIAN]</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Dirección: <b>{pos['direction']}</b>\n"
            f"💵 Precio Actual: ${cur_price:,.2f}\n"
            f"🛡 <b>Gestión:</b> SL movido a <b>Break-Even (+50 pts)</b> (${pos['sl']:,.2f})\n"
            f"🚀 ¡Operación protegida buscando TP2 (+1.350 pts)!"
        )
        send_telegram_alert(msg)

    # 2. Early Exit (> +450 pts + opposing momentum)
    if pts >= QUANT_CONFIG['early_exit_min_profit_pts'] and not pos.get('early_exit_warned'):
        rsi = calculate_rsi(klines, 14)
        if (is_long and rsi > 82.0) or (not is_long and rsi < 18.0):
            pos['early_exit_warned'] = True
            msg = (
                f"⚠️ <b>SALIDA ANTICIPADA RECOMENDADA [CLOUD GUARDIAN]</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Dirección: <b>{pos['direction']}</b>\n"
                f"💵 Precio Actual: ${cur_price:,.2f} (+{round(pts)} pts)\n"
                f"⚠️ Causa: Agotamiento extremo RSI {rsi:.1f}\n"
                f"💡 Considerar tomar ganancias ahora."
            )
            send_telegram_alert(msg)

    # 3. TP2 (+1350 pts)
    if pts >= QUANT_CONFIG['tp2_pts']:
        msg = (
            f"🏁 <b>OBJETIVO FINAL TP2 ALCANZADO (+{round(pts)} PTS) [CLOUD GUARDIAN]</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Dirección: <b>{pos['direction']}</b>\n"
            f"💵 Cierre en: ${cur_price:,.2f}\n"
            f"💰 Beneficio Neto Capturado: +{round(pts - QUANT_CONFIG['friction_fee_pts'])} pts\n"
            f"🎉 Operación finalizada con éxito."
        )
        send_telegram_alert(msg)
        state['open_position'] = None

    # 4. Stop-Loss
    sl_hit = (cur_price <= pos['sl']) if is_long else (cur_price >= pos['sl'])
    if sl_hit:
        msg = (
            f"🛑 <b>STOP-LOSS EJECUTADO [CLOUD GUARDIAN]</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Dirección: <b>{pos['direction']}</b>\n"
            f"💵 Precio Cierre: ${cur_price:,.2f}\n"
            f"📉 Puntos: {round(pts)} pts"
        )
        send_telegram_alert(msg)
        state['open_position'] = None

    state['last_updated'] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

# 7. MAIN RUNNER
def main():
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] Iniciando escaneo cuántico 24/7 de BTC...")
    klines = fetch_binance_klines()
    if not klines:
        print("[ERROR] Imposible continuar sin datos.")
        sys.exit(1)

    cur_price = klines[-1]['c']
    print(f"[PRECIO BTC] ${cur_price:,.2f}")

    # Monitor any existing position in cloud state
    monitor_cloud_position(cur_price, klines)

    # Evaluate new entry signals
    sig = evaluate_signal(klines)
    if not sig:
        print("[ANALYSIS] Sin datos suficientes.")
        return

    print(f"[ANALYSIS] Dirección: {sig['direction']} | Score: {sig['score']}% | Sesión: {sig.get('session')}")

    # Check last alert cache to prevent duplicate alerts on the same candle
    last_alert_key = None
    if os.path.exists(LAST_ALERT_FILE):
        try:
            with open(LAST_ALERT_FILE, 'r') as f:
                last_alert_data = json.load(f)
                last_alert_key = last_alert_data.get('alert_key')
        except Exception:
            pass

    cur_candle_key = f"{sig['direction']}_{sig.get('timestamp')}"

    if sig['score'] >= QUANT_CONFIG['min_score_threshold'] and sig['direction'] in ('LONG', 'SHORT'):
        if last_alert_key == cur_candle_key:
            print(f"[ALERT SKIP] Alerta ya enviada previamente para la vela {cur_candle_key}.")
        else:
            print(f"[SEÑAL CLARA DETECTADA] ¡Score {sig['score']}%! Despachando a Telegram @MrProezas...")
            msg = (
                f"🚀 <b>NUEVA ENTRADA CUANTITATIVA [{sig['direction']}] [CLOUD 24/7]</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 <b>Puntuación de Confluencia:</b> <code>{sig['score']}%</code> (Umbral: {QUANT_CONFIG['min_score_threshold']}%)\n"
                f"💵 <b>Precio de Entrada:</b> ${sig['cur_price']:,.2f}\n"
                f"🛑 <b>Stop-Loss:</b> ${sig['sl']:,.2f} (Riesgo: {sig['sl_pts']} pts)\n"
                f"🎯 <b>TP1 (50% Parcial):</b> ${sig['tp1']:,.2f} (+750 pts)\n"
                f"🏁 <b>TP2 (50% Final):</b> ${sig['tp2']:,.2f} (+{sig['tp2_pts']} pts)\n"
                f"⏱ <b>Sesión:</b> {sig['session']}\n"
                f"📈 <b>Motivo:</b> {' • '.join(sig['reasons'])}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"☁️ <i>Generado automáticamente 24/7 por GitHub Actions en la nube.</i>"
            )
            success = send_telegram_alert(msg)
            if success:
                # Save alert key
                with open(LAST_ALERT_FILE, 'w') as f:
                    json.dump({
                        'alert_key': cur_candle_key,
                        'direction': sig['direction'],
                        'score': sig['score'],
                        'price': sig['cur_price'],
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }, f, indent=2)

                # Record in state for cloud monitoring
                with open(STATE_FILE, 'w') as f:
                    json.dump({
                        'open_position': {
                            'direction': sig['direction'],
                            'entry_price': sig['cur_price'],
                            'sl': sig['sl'],
                            'tp1': sig['tp1'],
                            'tp2': sig['tp2'],
                            'tp1_hit': False,
                            'early_exit_warned': False,
                            'opened_at': datetime.now(timezone.utc).isoformat()
                        },
                        'last_updated': datetime.now(timezone.utc).isoformat()
                    }, f, indent=2)
    else:
        print(f"[STATUS] Sin señal de disparo (Score {sig['score']}% < {QUANT_CONFIG['min_score_threshold']}%).")

if __name__ == '__main__':
    main()
