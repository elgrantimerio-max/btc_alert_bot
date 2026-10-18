#!/usr/bin/env python3
"""
BTC Quant Terminal V6.5 - 24/7 Cloud Guardian Engine
Autonomous Headless Engine for GitHub Actions & VPS
Monitors Bitcoin (BTC/USDT) every 5 minutes in the cloud and sends real-time Telegram alerts
Target: Capture expansions of 1,200 to 1,500 points (USD) in Long/Short
"""

import os
import sys
import json
import math
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

# 1. CONFIGURATION & CREDENTIALS
# Priority: Environment Variables (GitHub Secrets) -> Local .env file
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

# Soporte para archivo local .env (para desarrollo local sin exponer claves en Git)
if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        try:
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k == 'TELEGRAM_BOT_TOKEN' and not TELEGRAM_BOT_TOKEN:
                            TELEGRAM_BOT_TOKEN = v
                        elif k == 'TELEGRAM_CHAT_ID' and not TELEGRAM_CHAT_ID:
                            TELEGRAM_CHAT_ID = v
        except Exception as e:
            print(f"[ENV WARN] Error leyendo archivo .env local: {e}")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage" if TELEGRAM_BOT_TOKEN else ""

QUANT_CONFIG = {
    'symbol': 'BTCUSDT',
    'timeframe': '4h',
    'limit': 500,
    'min_score_threshold': 68,
    'atr_multiplier': 1.2,
    'min_stop_loss_pts': 180,
    'max_stop_loss_pts': 1500,
    'tp1_atr_multiplier': 1.2,
    'tp2_atr_multiplier': 3.6,
    'tp1_pts': 900,
    'tp2_pts': 1500,
    'tp1_partial_pct': 0.75,
    'tp2_runner_pct': 0.25,
    'break_even_lock_pts': 300, # Locks +300 pts profit on BE move
    'max_hold_candles': 5, # 5 velas de 4H = 20 horas (Horizonte Óptimo)
    'break_even_buffer_atr': 0.25,
    'trailing_trigger_atr': 1.8,
    'trailing_distance_atr': 1.1,
    'early_exit_min_profit_pts': 400,
    'friction_fee_pts': 35,
    'bankroll_usdt': 5000.0,
    'trade_notional_usdt': 20000.0,
    'tier_a_plus_notional_usdt': 40000.0,
    'default_trade_size_btc': 0.25,
    'tier_a_plus_trade_size_btc': 0.50,
    'leverage': 20,
    'signal_validity_minutes': 120 # Ventana de validez: 2 horas (24 ciclos del cron de 5 min) para esperar el retest
}

STATE_FILE = 'state.json'
LAST_ALERT_FILE = 'last_alert.json'
JOURNAL_FILE = 'journal.json'

# 2. TELEGRAM DISPATCHER
def send_telegram_alert(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TELEGRAM CONFIG ERROR] Alerta NO enviada: Falta TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID.")
        print("[CONFIGURACIÓN GITHUB SECRETS]")
        print("  1. Entra a tu repositorio: https://github.com/elgrantimerio-max/btctradingbot")
        print("  2. Ve a Settings -> Secrets and variables -> Actions -> New repository secret")
        print("  3. Añade 'TELEGRAM_BOT_TOKEN' con el token proporcionado por @BotFather")
        print("  4. Añade 'TELEGRAM_CHAT_ID' con tu Chat ID numérico")
        return False

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
        headers={'Content-Type': 'application/json', 'User-Agent': 'BTCQuantGuardian/6.5'}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            res_data = json.loads(resp.read().decode('utf-8'))
            if res_data.get('ok'):
                print("[TELEGRAM] Alerta entregada con éxito a Telegram.")
                return True
            else:
                print(f"[TELEGRAM] Error respuesta Telegram: {res_data}")
                return False
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode('utf-8')
            print(f"[TELEGRAM HTTP {e.code}] {err_body}")
            if "can't parse entities" in err_body:
                print("[TELEGRAM RETRY] Error de entidades HTML. Reintentando en texto plano...")
                plain_text = text.replace('<b>', '').replace('</b>', '').replace('<code>', '').replace('</code>', '').replace('<i>', '').replace('</i>', '')
                plain_payload = {
                    'chat_id': TELEGRAM_CHAT_ID,
                    'text': plain_text
                }
                plain_data = json.dumps(plain_payload).encode('utf-8')
                plain_req = urllib.request.Request(
                    TELEGRAM_API_URL,
                    data=plain_data,
                    headers={'Content-Type': 'application/json', 'User-Agent': 'BTCQuantGuardian/6.5'}
                )
                with urllib.request.urlopen(plain_req, timeout=10) as resp:
                    res_data = json.loads(resp.read().decode('utf-8'))
                    if res_data.get('ok'):
                        print("[TELEGRAM RETRY] Alerta entregada con éxito en texto plano.")
                        return True
        except Exception as retry_err:
            print(f"[TELEGRAM RETRY ERROR] {retry_err}")
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
            req = urllib.request.Request(url, headers={'User-Agent': 'BTCQuantGuardian/6.5'})
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

def fetch_binance_open_interest():
    try:
        url = "https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT"
        req = urllib.request.Request(url, headers={'User-Agent': 'BTCQuantGuardian/6.5'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            oi = float(data.get('openInterest', 0))
            print(f"[DATA] Binance Futures Open Interest actual: {oi:,.2f} BTC")
            return oi
    except Exception as e:
        print(f"[DATA WARN] No se pudo obtener Open Interest de Futuros: {e}")
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
        delta = (k['v'] * ((k['c'] - k['o']) / rng)) if rng > 0 else 0.0
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

def calculate_ichimoku(klines, tenkan_p=9, kijun_p=26, span_b_p=52):
    if len(klines) < span_b_p:
        return None

    def get_mid(sub):
        hi = max(k['h'] for k in sub)
        lo = min(k['l'] for k in sub)
        return (hi + lo) / 2.0

    n = len(klines)
    tenkan = get_mid(klines[-tenkan_p:])
    kijun = get_mid(klines[-kijun_p:])

    # Cloud hovering at current candle was projected 26 bars ago
    ref_idx = max(span_b_p, n - 26)
    tenkan_past = get_mid(klines[ref_idx - tenkan_p:ref_idx])
    kijun_past = get_mid(klines[ref_idx - kijun_p:ref_idx])
    span_a = (tenkan_past + kijun_past) / 2.0
    span_b = get_mid(klines[ref_idx - span_b_p:ref_idx])

    kumo_top = max(span_a, span_b)
    kumo_bottom = min(span_a, span_b)
    is_bullish_cloud = span_a >= span_b

    return {
        'tenkan': tenkan,
        'kijun': kijun,
        'span_a': span_a,
        'span_b': span_b,
        'kumo_top': kumo_top,
        'kumo_bottom': kumo_bottom,
        'is_bullish_cloud': is_bullish_cloud
    }

def calculate_ttm_squeeze(klines, period=20, bb_mult=2.0, kc_mult=1.5):
    if len(klines) < period:
        return {'is_squeeze': False, 'momentum': 0.0}

    sub = klines[-period:]
    closes = [k['c'] for k in sub]
    sma = sum(closes) / period
    variance = sum((c - sma) ** 2 for c in closes) / period
    stdev = math.sqrt(variance)

    bb_upper = sma + bb_mult * stdev
    bb_lower = sma - bb_mult * stdev

    atr = calculate_atr(sub, period)
    kc_upper = sma + kc_mult * atr
    kc_lower = sma - kc_mult * atr

    # Squeeze is ON when BB is inside KC
    is_squeeze = (bb_upper < kc_upper) and (bb_lower > kc_lower)

    max_h = max(k['h'] for k in sub)
    min_l = min(k['l'] for k in sub)
    mid_point = ((max_h + min_l) / 2.0 + sma) / 2.0
    momentum = sub[-1]['c'] - mid_point

    return {
        'is_squeeze': is_squeeze,
        'momentum': momentum
    }

# 4b. OPTIMAL PULLBACK / RETEST ENTRY ENGINE
def calculate_optimal_entry(direction, cur_price, atr, ema20, vwap, cur_candle=None):
    if direction not in ('LONG', 'SHORT'):
        return {
            'market_price': cur_price,
            'optimal_price': cur_price,
            'zone_min': cur_price,
            'zone_max': cur_price,
            'timing_status': 'NEUTRAL',
            'timing_advice': 'Esperando señal confirmada',
            'saving_pts': 0
        }

    is_long = direction == 'LONG'
    if is_long:
        ref_support = max(ema20 or cur_price, vwap or cur_price)
        zone_max = round(cur_price - 0.10 * atr, 2)
        zone_min = round(max(cur_price - 0.45 * atr, min(zone_max, ref_support)), 2)
        optimal_price = round((zone_min + zone_max) / 2.0, 2)
        saving_pts = round(max(0.0, cur_price - optimal_price))

        dist_from_support = cur_price - (ema20 or cur_price)
        is_extended = dist_from_support > (0.55 * atr)
        is_at_support = abs(dist_from_support) <= (0.25 * atr)

        if is_at_support:
            timing_advice = f"⚡ ENTRAR AHORA: Precio en Zona de Valor (Retest a EMA20 en ${ref_support:,.2f})"
            timing_status = "ENTER_NOW"
        elif is_extended:
            timing_advice = f"⏳ ESPERAR RETROCESO: Precio extendido (+{round(dist_from_support)} pts de EMA20). Esperar zona ${zone_min:,.2f} - ${zone_max:,.2f} (Ahorro: ~{saving_pts} pts)"
            timing_status = "WAIT_PULLBACK"
        else:
            timing_advice = f"🎯 ENTRADA ÓPTIMA: Orden límite en ${optimal_price:,.2f} o 50% mercado y 50% en retroceso a ${zone_min:,.2f}"
            timing_status = "PULLBACK_FAVORABLE"

        return {
            'market_price': cur_price,
            'optimal_price': optimal_price,
            'zone_min': zone_min,
            'zone_max': zone_max,
            'timing_status': timing_status,
            'timing_advice': timing_advice,
            'saving_pts': saving_pts
        }
    else:
        ref_resistance = min(ema20 or cur_price, vwap or cur_price)
        zone_min = round(cur_price + 0.10 * atr, 2)
        zone_max = round(min(cur_price + 0.45 * atr, max(zone_min, ref_resistance)), 2)
        optimal_price = round((zone_min + zone_max) / 2.0, 2)
        saving_pts = round(max(0.0, optimal_price - cur_price))

        dist_from_resistance = (ema20 or cur_price) - cur_price
        is_extended = dist_from_resistance > (0.55 * atr)
        is_at_resistance = abs(dist_from_resistance) <= (0.25 * atr)

        if is_at_resistance:
            timing_advice = f"⚡ ENTRAR AHORA: Precio en Zona de Valor (Retest bajista a EMA20 en ${ref_resistance:,.2f})"
            timing_status = "ENTER_NOW"
        elif is_extended:
            timing_advice = f"⏳ ESPERAR REBOTE: Precio extendido a la baja (-{round(dist_from_resistance)} pts de EMA20). Esperar rebote a ${zone_min:,.2f} - ${zone_max:,.2f} (Mejora R:R en ~{saving_pts} pts)"
            timing_status = "WAIT_PULLBACK"
        else:
            timing_advice = f"🎯 ENTRADA ÓPTIMA: Orden límite de venta en ${optimal_price:,.2f} o 50% mercado y 50% en rebote a ${zone_max:,.2f}"
            timing_status = "PULLBACK_FAVORABLE"

        return {
            'market_price': cur_price,
            'optimal_price': optimal_price,
            'zone_min': zone_min,
            'zone_max': zone_max,
            'timing_status': timing_status,
            'timing_advice': timing_advice,
            'saving_pts': saving_pts
        }

# 5. PREDICTIVE ENTRY ENGINE (0 - 100 PTS CONFLUENCE)
def evaluate_signal(klines, oi_delta=0.0):
    if len(klines) < 50:
        return None
    cur = klines[-1]
    cur_price = cur['c']

    # 1. Session Filter (Max 15 pts) - Riguroso con Fines de Semana y Horarios Institucionales
    dt = datetime.fromtimestamp(cur['t'] / 1000.0, tz=timezone.utc)
    day_of_week = dt.weekday()  # 0 = Lunes, 5 = Sábado, 6 = Domingo
    utc_hours = dt.hour + dt.minute / 60.0
    is_saturday = (day_of_week == 5)
    is_sunday = (day_of_week == 6)

    if is_saturday or (is_sunday and utc_hours < 22.0):
        # Fin de Semana: Wall Street (NYSE), Londres (LSE) y CME están CERRADOS
        session_name = 'FIN DE SEMANA (BOLSAS CERRADAS)'
        session_score = 0  # 0/15 pts: Sin combustible ni respaldo institucional tradicional
    elif is_sunday and utc_hours >= 22.0:
        # Domingo noche: Apertura semanal de futuros CME y mercados de Asia/Pacífico
        session_name = 'APERTURA SEMANAL CME / PACÍFICO'
        session_score = 6
    else:
        # Lunes a Viernes: Sesiones Institucionales Abiertas
        is_london = 8.0 <= utc_hours < 16.5
        is_ny = 13.0 <= utc_hours < 21.0
        is_overlap = 13.5 <= utc_hours < 16.5  # 13:30 - 16:30 UTC: Coincidencia máxima

        if is_overlap:
            session_name = 'OVERLAP (LONDRES + NY)'
            session_score = 15
        elif is_ny:
            session_name = 'NEW YORK (WALL STREET)'
            session_score = 12
        elif is_london:
            session_name = 'LONDRES (EUROPA)'
            session_score = 12
        elif 0.0 <= utc_hours < 8.0:
            session_name = 'ASIA (TOKIO / HK)'
            session_score = 5
        else:
            session_name = 'INTERSESIÓN (POST-NY)'
            session_score = 3

    session_score = min(15, max(0, session_score))

    # 2. Anti-Chop & TTM Squeeze Regime Detector (Max 15 pts)
    chop = calculate_choppiness(klines, 14)
    adx = calculate_adx(klines, 14)
    ttm = calculate_ttm_squeeze(klines, 20)

    if chop > 61.8 and adx < 22.0:
        return {
            'score': 0,
            'direction': 'HIBERNATION',
            'session': session_name,
            'chop': chop,
            'adx': adx,
            'ttm': ttm,
            'reasons': ['MODO HIBERNACIÓN: Choppiness > 61.8 y ADX < 22 (Mercado sucio sin expansión)'],
            'optimal_entry': {
                'market_price': cur_price, 'optimal_price': cur_price,
                'zone_min': cur_price, 'zone_max': cur_price,
                'timing_status': 'HIBERNATION', 'timing_advice': 'Modo Hibernación activo (Chop > 61.8). No operar.'
            },
            'pillars': {
                'session': session_score,
                'anti_chop': 0,
                'orb': 0,
                'structure': 0,
                'order_flow': 0,
                'liq_sweep': 0
            }
        }

    atr = calculate_atr(klines, 14)
    gray_zone_block = False
    if ttm['is_squeeze']:
        anti_chop_score = 4
    elif adx > 25.0 and chop < 48.0:
        anti_chop_score = 15
    elif chop < 52.0:
        anti_chop_score = 12
    elif chop >= 55.0 and chop <= 61.8 and adx < 20.0:
        anti_chop_score = 4
        gray_zone_block = True
    else:
        anti_chop_score = 7

    anti_chop_score = min(15, anti_chop_score)

    # 3. ORB Box & ADR 24h Fuel (Max 15 pts)
    orb_high, orb_low, orb_active = calculate_orb(klines)
    adr_consumed, adr_remaining = calculate_adr_fuel(klines)
    orb_score = 0
    long_orb = False
    short_orb = False

    if adr_remaining > 700:
        orb_score += 7
        if orb_active and cur_price > orb_high:
            long_orb = True
            orb_score += 8
        elif orb_active and cur_price < orb_low:
            short_orb = True
            orb_score += 8
    else:
        orb_score = 2

    orb_score = min(15, orb_score)

    # 4. VWAP 24h + EMA 20/50/100/200 + RSI(14) + Ichimoku Kumo Filter (Max 30 pts)
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
        structure_score_long += 10
    elif cur_price < vwap and ema20 < ema50:
        structure_score_short += 10

    macro_bull = cur_price > ema200 and ema100 > ema200
    macro_bear = cur_price < ema200 and ema100 < ema200
    if macro_bull: structure_score_long += 8
    elif macro_bear: structure_score_short += 8

    # Filtro Macro Ichimoku Kumo & Rebote Dinámico (Max 10 pts)
    ichi = calculate_ichimoku(klines)
    ichi_blocked_long = False
    ichi_blocked_short = False
    kumo_bounce_long = False
    kumo_bounce_short = False

    if ichi:
        is_near_kumo_top = cur['l'] <= (ichi['kumo_top'] + 0.35 * atr) and cur_price >= ichi['kumo_top']
        is_near_kumo_bot = cur['h'] >= (ichi['kumo_bottom'] - 0.35 * atr) and cur_price <= ichi['kumo_bottom']

        if is_near_kumo_top and cur['c'] >= cur['o']:
            kumo_bounce_long = True
            structure_score_long += 10 # Rebote dinámico en soporte Kumo
        elif cur_price > ichi['kumo_top']:
            structure_score_long += 7
        elif cur_price < ichi['kumo_bottom']:
            ichi_blocked_long = True
            structure_score_long = max(0, structure_score_long - 18)
            structure_score_short += 7
        else:
            structure_score_long = max(0, structure_score_long - 6)
            structure_score_short = max(0, structure_score_short - 6)

        if is_near_kumo_bot and cur['c'] <= cur['o']:
            kumo_bounce_short = True
            structure_score_short += 10 # Rechazo dinámico en resistencia Kumo
        elif cur_price < ichi['kumo_bottom']:
            structure_score_short += 7
        elif cur_price > ichi['kumo_top']:
            ichi_blocked_short = True
            structure_score_short = max(0, structure_score_short - 18)
            structure_score_long += 7

    # RSI (14) Momentum (Max 5 pts)
    if rsi < 35.0:
        structure_score_long += 5
    elif 40.0 <= rsi <= 68.0:
        structure_score_long += 3
    elif rsi > 80.0:
        structure_score_long -= 8

    if rsi > 75.0:
        structure_score_short += 5
    elif 32.0 <= rsi <= 60.0:
        structure_score_short += 3
    elif rsi < 20.0:
        structure_score_short -= 8

    # Filtro de Momentum de Precio (3 velas, Max 5 pts)
    last3 = klines[-4:-1] if len(klines) >= 4 else []
    if len(last3) >= 2:
        bullish_candles = sum(1 for k in last3 if k['c'] > k['o'])
        bearish_candles = sum(1 for k in last3 if k['c'] < k['o'])
        if bullish_candles >= 2:
            structure_score_long += 5
        if bearish_candles >= 2:
            structure_score_short += 5

    # Anti-Overextension / Value Pullback Filter
    dist_from_ema20 = cur_price - ema20
    is_long_overextended = dist_from_ema20 > (1.1 * atr) or rsi > 70.0
    is_short_overextended = dist_from_ema20 < (-1.1 * atr) or rsi < 30.0

    if is_long_overextended:
        structure_score_long = max(0, structure_score_long - 10)
    if is_short_overextended:
        structure_score_short = max(0, structure_score_short - 10)

    # Clamp estructura a maximo 34 pts (15 + 15 + 15 + 34 + 15 + 6 = 100 pts)
    structure_score_long = min(34, max(0, structure_score_long))
    structure_score_short = min(34, max(0, structure_score_short))

    # 5. Order Flow (CVD + RVOL) & Filtro de Dinero Nuevo (OI Delta) (Max 15 pts)
    cvd_delta, rvol, _ = calculate_order_flow(klines)
    if rvol >= 1.2:
        of_score_long = 9 if cvd_delta > 0 else 0
        of_score_short = 9 if cvd_delta < 0 else 0
    else:
        of_score_long = 5 if cvd_delta > 0 else 0
        of_score_short = 5 if cvd_delta < 0 else 0

    if oi_delta > 15:
        of_score_long += 6
        of_score_short += 6
    elif oi_delta < -80:
        of_score_long = max(0, of_score_long - 8)
        of_score_short = max(0, of_score_short - 8)

    of_score_long = min(15, max(0, of_score_long))
    of_score_short = min(15, max(0, of_score_short))

    # 6. Liquidation Sweeps & SFP Trend-Pullback (Max 6 pts)
    recent = klines[-30:-1]
    liq_score_long = 0
    liq_score_short = 0
    if len(recent) > 5:
        r_high = max(k['h'] for k in recent)
        r_low = min(k['l'] for k in recent)
        if cur['l'] < r_low and cur['c'] > r_low:
            liq_score_long = 6 if (macro_bull or cur_price > ema50 or not ichi_blocked_long) else 2
        if cur['h'] > r_high and cur['c'] < r_high:
            liq_score_short = 6 if (macro_bear or cur_price < ema50 or not ichi_blocked_short) else 2

    liq_score_long = min(6, liq_score_long)
    liq_score_short = min(6, liq_score_short)

    total_long = session_score + anti_chop_score + orb_score + structure_score_long + of_score_long + liq_score_long
    total_short = session_score + anti_chop_score + orb_score + structure_score_short + of_score_short + liq_score_short

    is_long_dominant = total_long >= total_short
    raw_score = total_long if is_long_dominant else total_short
    final_score = min(100, round(raw_score))
    direction = 'NEUTRAL'
    reasons = []

    if final_score >= QUANT_CONFIG['min_score_threshold']:
        direction = 'LONG' if is_long_dominant else 'SHORT'
    elif final_score >= 45:
        direction = 'BIAS_LONG' if is_long_dominant else 'BIAS_SHORT'
    else:
        direction = 'NEUTRAL'

    if is_long_dominant:
        if session_score >= 10: reasons.append(f"Sesión {session_name}")
        elif session_score == 0: reasons.append("⚠️ Fin de Semana: Bolsas y CME cerrados (Bajo volumen)")
        if not ttm['is_squeeze']: reasons.append("TTM Squeeze Disparado (Expansión)")
        if anti_chop_score >= 10: reasons.append(f"Régimen Expansivo (Chop {chop:.1f})")
        if long_orb: reasons.append("Ruptura Cajón ORB")
        if cur_price > vwap and ema20 > ema50: reasons.append("Precio sobre VWAP y EMA 20 sobre 50")
        if macro_bull: reasons.append("Macro Alcista (Precio sobre EMA 100 y 200)")
        if ichi and cur_price > ichi['kumo_top']: reasons.append("Precio sobre Nube Ichimoku Kumo (Alcista)")
        reasons.append(f"RSI(14): {rsi:.1f}")
        if of_score_long >= 8: reasons.append(f"CVD Comprador (+{round(cvd_delta)} BTC)")
        if oi_delta > 15: reasons.append(f"Dinero Nuevo Futuros (+{round(oi_delta)} BTC)")
        if liq_score_long > 0: reasons.append("Barrido de Liquidez SFP Alcista (+8 pts)")
        if ichi_blocked_long: reasons.append("⚠️ FILTRO KUMO: Precio bajo la Nube Bajista")
    else:
        if session_score >= 10: reasons.append(f"Sesión {session_name}")
        elif session_score == 0: reasons.append("⚠️ Fin de Semana: Bolsas y CME cerrados (Bajo volumen)")
        if not ttm['is_squeeze']: reasons.append("TTM Squeeze Disparado (Expansión)")
        if anti_chop_score >= 10: reasons.append(f"Régimen Expansivo (Chop {chop:.1f})")
        if short_orb: reasons.append("Ruptura Cajón ORB")
        if cur_price < vwap and ema20 < ema50: reasons.append("Precio bajo VWAP y EMA 20 bajo 50")
        if macro_bear: reasons.append("Macro Bajista (Precio bajo EMA 100 y 200)")
        if ichi and cur_price < ichi['kumo_bottom']: reasons.append("Precio bajo Nube Ichimoku Kumo (Bajista)")
        reasons.append(f"RSI(14): {rsi:.1f}")
        if of_score_short >= 8: reasons.append(f"CVD Vendedor ({round(cvd_delta)} BTC)")
        if oi_delta > 15: reasons.append(f"Dinero Nuevo Vendedor (+{round(oi_delta)} BTC)")
        if liq_score_short > 0: reasons.append("Barrido de Liquidez SFP Bajista (+8 pts)")
        if ichi_blocked_short: reasons.append("⚠️ FILTRO KUMO: Precio sobre la Nube Alcista")

    # Hard Institutional Safety Blocks (Eliminate False Signals)
    if direction == 'LONG' and ichi_blocked_long:
        direction = 'NEUTRAL'
        final_score = min(final_score, 40)
    if direction == 'SHORT' and ichi_blocked_short:
        direction = 'NEUTRAL'
        final_score = min(final_score, 40)

    # Regla Institucional Absoluta: NUNCA operar en corto sobre la EMA 200, ni en largo bajo la EMA 200
    if direction == 'SHORT' and cur_price > ema200:
        direction = 'NEUTRAL'
        final_score = min(final_score, 40)
    elif direction == 'LONG' and cur_price < ema200:
        direction = 'NEUTRAL'
        final_score = min(final_score, 40)

    if ttm['is_squeeze'] and final_score >= QUANT_CONFIG['min_score_threshold']:
        direction = 'BIAS_LONG' if is_long_dominant else 'BIAS_SHORT'
        final_score = QUANT_CONFIG['min_score_threshold'] - 5

    # Filtro de Convicción: requiere mínimo 8 pts de diferencia entre LONG y SHORT
    conviction_gap = abs(total_long - total_short)
    if conviction_gap < 8 and direction in ('LONG', 'SHORT'):
        direction = 'BIAS_LONG' if is_long_dominant else 'BIAS_SHORT'
        final_score = min(final_score, QUANT_CONFIG['min_score_threshold'] - 3)

    # Bloqueo Zona Gris: requiere señal fuerte si está en zona de consolidación
    if gray_zone_block and final_score < (QUANT_CONFIG['min_score_threshold'] + 3) and direction in ('LONG', 'SHORT'):
        direction = 'BIAS_LONG' if is_long_dominant else 'BIAS_SHORT'
        final_score = QUANT_CONFIG['min_score_threshold'] - 4

    tf = QUANT_CONFIG.get('timeframe', '4h')
    if tf == '4h':
        tp1_dist = 900
        tp2_dist = 1500
        sl_dist = 700
    elif tf == '1h':
        tp1_dist = 700
        tp2_dist = 1200
        sl_dist = 500
    else:
        tp1_dist = max(140, round(QUANT_CONFIG.get('tp1_atr_multiplier', 1.2) * atr))
        tp2_dist = max(260, round(QUANT_CONFIG.get('tp2_atr_multiplier', 3.6) * atr))
        sl_dist = round(QUANT_CONFIG.get('atr_multiplier', 1.2) * atr)
        sl_dist = max(QUANT_CONFIG['min_stop_loss_pts'], min(QUANT_CONFIG['max_stop_loss_pts'], sl_dist))

    is_long_target = direction == 'LONG' or (direction != 'SHORT' and is_long_dominant)
    sl = (cur_price - sl_dist) if is_long_target else (cur_price + sl_dist)
    tp1 = (cur_price + tp1_dist) if is_long_target else (cur_price - tp1_dist)
    tp2 = (cur_price + tp2_dist) if is_long_target else (cur_price - tp2_dist)

    optimal_entry = calculate_optimal_entry(direction, cur_price, atr, ema20, vwap, cur)

    dir_cvd_match = (direction == 'LONG' and cvd_delta > 0) or (direction == 'SHORT' and cvd_delta < 0)
    is_tier_a_plus = (final_score >= QUANT_CONFIG['min_score_threshold']) and (rvol >= 1.0) and dir_cvd_match
    tier = 'A+' if is_tier_a_plus else ('ESTÁNDAR' if final_score >= QUANT_CONFIG['min_score_threshold'] else 'NEUTRAL')
    recommended_notional = QUANT_CONFIG.get('tier_a_plus_notional_usdt', 40000.0) if is_tier_a_plus else QUANT_CONFIG.get('trade_notional_usdt', 20000.0)
    recommended_size_btc = QUANT_CONFIG.get('tier_a_plus_trade_size_btc', 0.50) if is_tier_a_plus else QUANT_CONFIG.get('default_trade_size_btc', 0.25)

    eval_dir_is_long = direction == 'LONG' or (direction != 'SHORT' and is_long_dominant)
    pillars = {
        'session': session_score,
        'anti_chop': anti_chop_score,
        'orb': orb_score,
        'structure': structure_score_long if eval_dir_is_long else structure_score_short,
        'order_flow': of_score_long if eval_dir_is_long else of_score_short,
        'liq_sweep': liq_score_long if eval_dir_is_long else liq_score_short
    }

    return {
        'score': final_score,
        'direction': direction,
        'tier': tier,
        'is_tier_a_plus': is_tier_a_plus,
        'recommended_notional': recommended_notional,
        'recommended_size_btc': recommended_size_btc,
        'reasons': reasons,
        'session': session_name,
        'cur_price': cur_price,
        'optimal_entry': optimal_entry,
        'sl': sl,
        'sl_pts': sl_dist,
        'tp1': tp1,
        'tp1_pts': tp1_dist,
        'tp2': tp2,
        'tp2_pts': tp2_dist,
        'rsi': rsi,
        'chop': chop,
        'adx': adx,
        'ttm': ttm,
        'oi_delta': oi_delta,
        'timestamp': cur['t'],
        'pillars': pillars
    }

# 6. DYNAMIC POSITION GUARDIAN & CLOUD PAPER TRADING RECORDER
def record_cloud_closed_trade(pos, exit_price, reason):
    is_long = pos['direction'] == 'LONG'
    pts = (exit_price - pos['entry_price']) if is_long else (pos['entry_price'] - exit_price)
    btc_qty = pos.get('btc_qty', QUANT_CONFIG.get('default_trade_size_btc', 0.25))
    notional = pos.get('notional', QUANT_CONFIG.get('trade_notional_usdt', 20000.0))
    leverage = QUANT_CONFIG.get('leverage', 20)

    tp1_hit = pos.get('tp1_hit', False)
    realized_usd = pos.get('realized_usd', 0.0)

    if tp1_hit:
        remaining_qty = btc_qty * 0.25
        remaining_pnl = pts * remaining_qty
    else:
        remaining_pnl = pts * btc_qty

    friction_usd = QUANT_CONFIG.get('friction_fee_pts', 35) * btc_qty
    total_net_pnl_usd = (realized_usd + remaining_pnl) - friction_usd
    total_net_pts = round(total_net_pnl_usd / btc_qty) if btc_qty > 0 else round(pts)
    margin_used = notional / leverage
    roi_pct = round((total_net_pnl_usd / margin_used) * 100, 1) if margin_used > 0 else 0.0

    trade_record = {
        'id': pos.get('id', f"CLOUD_{int(datetime.now(timezone.utc).timestamp())}"),
        'isAutonomous': True,
        'source': 'AUTONOMOUS',
        'cloud': True,
        'direction': pos['direction'],
        'openedAt': pos.get('opened_at', datetime.now(timezone.utc).isoformat()),
        'closedAt': datetime.now(timezone.utc).isoformat(),
        'entryPrice': pos['entry_price'],
        'exitPrice': exit_price,
        'size': btc_qty,
        'notional': notional,
        'netPts': total_net_pts,
        'netPnlUsd': round(total_net_pnl_usd, 2),
        'roiPct': roi_pct,
        'reason': f"🤖 Quant Guardian [{reason}]",
        'tp1Hit': tp1_hit
    }

    journal = []
    if os.path.exists(JOURNAL_FILE):
        try:
            with open(JOURNAL_FILE, 'r', encoding='utf-8') as f:
                journal = json.load(f)
        except Exception:
            journal = []

    # Insert latest trade at the beginning
    journal.insert(0, trade_record)
    try:
        with open(JOURNAL_FILE, 'w', encoding='utf-8') as f:
            json.dump(journal, f, indent=2)
        print(f"[CLOUD JOURNAL] Operación registrada con éxito en {JOURNAL_FILE}: {total_net_pts:+} pts (${total_net_pnl_usd:,.2f} USD)")
    except Exception as e:
        print(f"[CLOUD JOURNAL ERROR] No se pudo guardar en {JOURNAL_FILE}: {e}")

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

    # 1. TP1 (75% Parcial asegurado, 25% Runner a TP2 1500 pts)
    tp1_target = pos.get('tp1_pts', QUANT_CONFIG['tp1_pts'])
    if not pos.get('tp1_hit') and pts >= tp1_target:
        pos['tp1_hit'] = True
        atr = calculate_atr(klines, 14)
        be_lock = pos.get('break_even_lock_pts', QUANT_CONFIG.get('break_even_lock_pts', 300))
        pos['sl'] = (pos['entry_price'] + be_lock) if is_long else (pos['entry_price'] - be_lock)
        pos['peak_price'] = cur_price
        btc_qty = pos.get('btc_qty', QUANT_CONFIG['trade_notional_usdt'] / pos['entry_price'])
        partial_frac = pos.get('tp1_partial_pct', QUANT_CONFIG.get('tp1_partial_pct', 0.75))
        realized_tp1_usd = tp1_target * partial_frac * btc_qty
        pos['realized_usd'] = pos.get('realized_usd', 0.0) + realized_tp1_usd
        msg = (
            f"🎯 <b>¡TAKE PROFIT (TP1) ALCANZADO (+{round(tp1_target)} PTS)! [CLOUD GUARDIAN]</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Dirección: <b>{pos['direction']}</b>\n"
            f"💵 <b>Precio Actual:</b> ${cur_price:,.2f}\n"
            f"💰 <b>Toma Parcial:</b> {int(partial_frac * 100)}% asegurado (+${realized_tp1_usd:,.2f} USD)\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🛡 <b>ACCIÓN REQUERIDA (EXCHANGE):</b>\n"
            f"👉 Mueve tu Stop-Loss a <b>Break-Even + {be_lock} pts</b> (${pos['sl']:,.2f})\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🚀 <i>¡25% corredor 100% RISK-FREE buscando TP2 (+{pos.get('tp2_pts', 1500)} pts)!</i>"
        )
        send_telegram_alert(msg)
    elif pos.get('tp1_hit'):
        atr = calculate_atr(klines, 14)
        peak = pos.get('peak_price', cur_price)
        if is_long and cur_price > peak:
            pos['peak_price'] = cur_price
            peak = cur_price
        elif not is_long and cur_price < peak:
            pos['peak_price'] = cur_price
            peak = cur_price

        favorable_dist = (peak - pos['entry_price']) if is_long else (pos['entry_price'] - peak)
        if favorable_dist >= (QUANT_CONFIG.get('trailing_trigger_atr', 2.0) * atr):
            trail_dist = QUANT_CONFIG.get('trailing_distance_atr', 1.2) * atr
            new_sl = (peak - trail_dist) if is_long else (peak + trail_dist)
            if is_long and new_sl > pos['sl']:
                pos['sl'] = new_sl
            elif not is_long and new_sl < pos['sl']:
                pos['sl'] = new_sl

    # 2. Early Exit (> +400 pts + opposing momentum)
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

    # 3. TP2
    tp2_target = pos.get('tp2_pts', QUANT_CONFIG['tp2_pts'])
    if pts >= tp2_target:
        msg = (
            f"🏁 <b>OBJETIVO FINAL TP2 ALCANZADO (+{round(pts)} PTS) [CLOUD GUARDIAN]</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Dirección: <b>{pos['direction']}</b>\n"
            f"💵 Cierre en: ${cur_price:,.2f}\n"
            f"💰 Beneficio Neto Capturado: +{round(pts - QUANT_CONFIG['friction_fee_pts'])} pts\n"
            f"🎉 Operación finalizada con éxito."
        )
        send_telegram_alert(msg)
        record_cloud_closed_trade(pos, cur_price, f"TP2 FINAL (+{round(pts)} PTS)")
        state['open_position'] = None

    # 4. Stop-Loss
    sl_hit = (cur_price <= pos['sl']) if is_long else (cur_price >= pos['sl'])
    if sl_hit:
        reason_sl = "STOP BREAK-EVEN" if pos.get('tp1_hit') else "STOP-LOSS"
        msg = (
            f"🛑 <b>{reason_sl} EJECUTADO [CLOUD GUARDIAN]</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Dirección: <b>{pos['direction']}</b>\n"
            f"💵 Precio Cierre: ${cur_price:,.2f}\n"
            f"📉 Puntos: {round(pts)} pts"
        )
        send_telegram_alert(msg)
        record_cloud_closed_trade(pos, cur_price, reason_sl)
        state['open_position'] = None

    # 5. Cierre por Tiempo Máximo (5 Velas / 20 Horas - Horizonte Óptimo)
    if state.get('open_position'):
        opened_str = pos.get('opened_at')
        if opened_str:
            try:
                opened_dt = datetime.fromisoformat(opened_str)
                elapsed_hours = (datetime.now(timezone.utc) - opened_dt).total_seconds() / 3600.0
                max_hours = QUANT_CONFIG.get('max_hold_candles', 5) * 4
                if elapsed_hours >= max_hours:
                    msg = (
                        f"⌛ <b>CIERRE POR TIEMPO MÁXIMO (20H / 5 VELAS) [CLOUD GUARDIAN]</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"Dirección: <b>{pos['direction']}</b>\n"
                        f"💵 Precio Cierre: ${cur_price:,.2f}\n"
                        f"📊 Resultado: {round(pts):+} pts\n"
                        f"💡 Posición liquidada por límite de tiempo de la estrategia óptima."
                    )
                    send_telegram_alert(msg)
                    record_cloud_closed_trade(pos, cur_price, "LÍMITE TIEMPO 20H")
                    state['open_position'] = None
            except Exception:
                pass

    state['last_updated'] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def check_cloud_pending_setup(cur_price, state, klines):
    pending = state.get('pending_setup')
    if not pending or state.get('open_position'):
        return

    # 1. Comprobar Expiración Temporal (2 horas / 24 ciclos del cron de 5 min)
    created_at_str = pending.get('created_at')
    if created_at_str:
        try:
            created_dt = datetime.fromisoformat(created_at_str)
            elapsed_min = (datetime.now(timezone.utc) - created_dt).total_seconds() / 60.0
            max_wait_min = QUANT_CONFIG.get('signal_validity_minutes', 120)
            if elapsed_min > max_wait_min:
                print(f"[RETEST SETUP EXPIRADO] La señal {pending['direction']} expiró tras {elapsed_min:.0f} min sin retest.")
                msg = (
                    f"⌛ <b>SEÑAL PENDIENTE EXPIRADA [CLOUD GUARDIAN]</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Dirección: <b>{pending['direction']}</b>\n"
                    f"⏱ Tiempo: 2 horas sin alcanzar zona de retest.\n"
                    f"💡 Cancelada por protección de capital para evitar entradas tardías en movimientos agotados."
                )
                send_telegram_alert(msg)
                state['pending_setup'] = None
                state['last_updated'] = datetime.now(timezone.utc).isoformat()
                with open(STATE_FILE, 'w') as f:
                    json.dump(state, f, indent=2)
                return
        except Exception:
            pass

    # 2. Comprobar Invalidación de Estructura
    is_long = pending['direction'] == 'LONG'
    sl = pending.get('sl', 0)
    chop = calculate_choppiness(klines, 14)
    invalidated = False
    invalidation_reason = ""

    if is_long and cur_price <= sl:
        invalidated = True
        invalidation_reason = f"Precio cayó por debajo del Stop previsto (${sl:,.2f})"
    elif not is_long and cur_price >= sl:
        invalidated = True
        invalidation_reason = f"Precio superó el Stop previsto (${sl:,.2f})"
    elif chop > 61.8:
        invalidated = True
        invalidation_reason = f"Mercado entró en Choppiness extremo ({chop:.1f} > 61.8)"

    if invalidated:
        print(f"[RETEST SETUP INVALIDADO] {invalidation_reason}")
        msg = (
            f"🛑 <b>SEÑAL PENDIENTE CANCELADA [CLOUD GUARDIAN]</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Dirección: <b>{pending['direction']}</b>\n"
            f"⚠️ Causa: {invalidation_reason}\n"
            f"🛡 El mercado cambió de estructura antes de completar el retest."
        )
        send_telegram_alert(msg)
        state['pending_setup'] = None
        state['last_updated'] = datetime.now(timezone.utc).isoformat()
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
        return

    # 3. Comprobar si el Precio ha entrado en la Zona de Retest
    zone_min = pending.get('zone_min', cur_price)
    zone_max = pending.get('zone_max', cur_price)
    retest_hit = False

    if is_long:
        # En Long, el pullback ocurre cuando el precio retrocede hacia soporte
        retest_hit = (cur_price <= zone_max)
    else:
        # En Short, el rebote ocurre cuando el precio rebota hacia resistencia
        retest_hit = (cur_price >= zone_min)

    if retest_hit:
        trade_id = f"CLOUD_{int(datetime.now(timezone.utc).timestamp())}"
        state['open_position'] = {
            'id': trade_id,
            'direction': pending['direction'],
            'entry_price': cur_price,
            'notional': pending.get('notional', QUANT_CONFIG.get('trade_notional_usdt', 20000.0)),
            'btc_qty': pending.get('btc_qty', 0.25),
            'is_tier_a_plus': pending.get('is_tier_a_plus', False),
            'tier': pending.get('tier', 'ESTÁNDAR'),
            'sl': pending['sl'],
            'tp1': pending['tp1'],
            'tp1_pts': pending['tp1_pts'],
            'tp2': pending['tp2'],
            'tp2_pts': pending['tp2_pts'],
            'tp1_hit': False,
            'early_exit_warned': False,
            'opened_at': datetime.now(timezone.utc).isoformat()
        }
        saving_pts = abs(cur_price - pending.get('signal_price', cur_price))
        print(f"[CLOUD PAPER TRADING] ¡Retest completado! Entrada {pending['direction']} ejecutada en ${cur_price:,.2f} (Ahorro ~{saving_pts:.0f} pts)")
        msg = (
            f"🎯 <b>¡ENTRADA POR RETEST EJECUTADA [CLOUD GUARDIAN]!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Dirección: <b>{pending['direction']}</b> (Tier: <b>{pending.get('tier', 'ESTÁNDAR')}</b>)\n"
            f"💵 <b>Precio Entrada Óptimo:</b> ${cur_price:,.2f}\n"
            f"🎁 <b>Ventaja Capturada:</b> Ahorro de ~{saving_pts:.0f} pts por esperar el retest\n"
            f"🛑 <b>Stop-Loss:</b> ${pending['sl']:,.2f}\n"
            f"🎯 <b>TP1 (75% Parcial):</b> ${pending['tp1']:,.2f} (+{pending['tp1_pts']} pts)\n"
            f"🏁 <b>TP2 (25% Corredor):</b> ${pending['tp2']:,.2f} (+{pending['tp2_pts']} pts)\n"
            f"🛡 <i>Posición abierta en zona de valor institucional sin perseguir el precio.</i>"
        )
        send_telegram_alert(msg)
        state['pending_setup'] = None
        state['last_updated'] = datetime.now(timezone.utc).isoformat()
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)

# 7. MAIN RUNNER
def main():
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] Iniciando escaneo cuántico 24/7 de BTC...")
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        masked_tok = TELEGRAM_BOT_TOKEN[:6] + "..." + TELEGRAM_BOT_TOKEN[-4:] if len(TELEGRAM_BOT_TOKEN) > 10 else "***"
        print(f"[SECURITY] Credenciales Telegram activas vía Secretos de GitHub (Bot: {masked_tok}, Chat ID: {TELEGRAM_CHAT_ID})")
    else:
        print("[SECURITY WARN] TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no detectados en variables de entorno.")
        print("[INFO] Configura 'TELEGRAM_BOT_TOKEN' y 'TELEGRAM_CHAT_ID' en GitHub Secrets (Settings > Secrets and variables > Actions).")

    klines = fetch_binance_klines()
    if not klines:
        print("[ERROR] Imposible continuar sin datos.")
        sys.exit(1)

    cur_price = klines[-1]['c']
    print(f"[PRECIO BTC] ${cur_price:,.2f}")

    # Fetch Futures Open Interest and compute delta
    current_oi = fetch_binance_open_interest()
    oi_delta = 0.0
    state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
                last_oi = state.get('last_known_oi')
                if last_oi is not None and current_oi is not None:
                    oi_delta = current_oi - float(last_oi)
        except Exception:
            pass

    if current_oi is not None:
        state['last_known_oi'] = current_oi
        state['oi_delta'] = oi_delta
        try:
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass

    if current_oi:
        print(f"[OPEN INTEREST] OI: {current_oi:,.1f} BTC | Delta: {oi_delta:+,.1f} BTC")
    else:
        print("[OPEN INTEREST] No disponible (usando Delta 0)")

    # Monitor any existing position in cloud state
    monitor_cloud_position(cur_price, klines)

    # Check and execute pending setup waiting for retest
    check_cloud_pending_setup(cur_price, state, klines)

    # Evaluate new entry signals with OI Delta filter
    sig = evaluate_signal(klines, oi_delta=oi_delta)
    if not sig:
        print("[ANALYSIS] Sin datos suficientes.")
        return

    print(f"[ANALYSIS] Dirección: {sig['direction']} | Score: {sig['score']}% | Sesión: {sig.get('session')}")

    # Check last alert cache to prevent duplicate alerts on the same setup
    last_alert_key = None
    last_alert_time = None
    if os.path.exists(LAST_ALERT_FILE):
        try:
            with open(LAST_ALERT_FILE, 'r') as f:
                last_alert_data = json.load(f)
                last_alert_key = last_alert_data.get('alert_key')
                last_alert_time = last_alert_data.get('timestamp')
        except Exception:
            pass

    opt = sig.get('optimal_entry', {})
    timing_status = opt.get('timing_status', 'FAVORABLE')
    cur_candle_key = f"{sig['direction']}_{sig.get('timestamp')}_{sig.get('tier')}_{timing_status}"

    if sig['score'] >= QUANT_CONFIG['min_score_threshold'] and sig['direction'] in ('LONG', 'SHORT'):
        is_duplicate = (last_alert_key == cur_candle_key)
        if is_duplicate:
            print(f"[ALERT SKIP] Alerta idéntica ya enviada para {cur_candle_key} (Estado actual activo y sin cambios).")
        else:
            print(f"[ÍNDICE DE CONFLUENCIA ÓPTIMO ACTIVO] ¡Score {sig['score']}% [{sig['direction']}]! Despachando a Telegram...")
            is_a_plus = sig.get('is_tier_a_plus', False)
            notional = sig.get('recommended_notional', QUANT_CONFIG.get('trade_notional_usdt', 20000.0))
            leverage = QUANT_CONFIG.get('leverage', 20)
            margin_used = notional / leverage
            free_buffer_pct = 60 if is_a_plus else 80
            btc_qty = sig.get('recommended_size_btc', notional / sig['cur_price'] if sig['cur_price'] > 0 else 0.25)
            sl_usd = sig['sl_pts'] * btc_qty
            tp2_usd = sig['tp2_pts'] * btc_qty

            if is_a_plus:
                header_title = (
                    f"💎 <b>[CLOUD GUARDIAN 24/7] ¡ÍNDICE DE CONFLUENCIA ÓPTIMO A+ [{sig['direction']}]!</b>\n"
                    f"🔥 <b>CONVICCIÓN INSTITUCIONAL MÁXIMA (DOBLE TAMAÑO $40,000 USD)</b>\n"
                    f"⚡ <i>80% Win Rate Histórico • Profit Factor 5.51</i>\n"
                )
                sizing_line = f"💼 <b>Dimensionamiento Dual A+:</b> Posición ${notional:,.0f} USD ({btc_qty:.2f} BTC) | Margen: ${margin_used:,.0f} USD ({free_buffer_pct}% Libre)\n"
            elif timing_status == 'ENTER_NOW':
                header_title = (
                    f"⚡ <b>[CLOUD GUARDIAN 24/7] ¡ÍNDICE DE CONFLUENCIA ÓPTIMO [{sig['direction']}]!</b>\n"
                    f"🎯 <b>NIVEL DE ENTRADA RETEST INMEDIATO CONFIRMADO</b>\n"
                )
                sizing_line = f"💼 <b>Dimensionamiento Estándar:</b> Posición ${notional:,.0f} USD ({btc_qty:.2f} BTC) | Margen: ${margin_used:,.0f} USD ({free_buffer_pct}% Libre)\n"
            else:
                header_title = (
                    f"🚀 <b>[CLOUD GUARDIAN 24/7] ¡ÍNDICE DE CONFLUENCIA ÓPTIMO [{sig['direction']}]!</b>\n"
                )
                sizing_line = f"💼 <b>Dimensionamiento Estándar:</b> Posición ${notional:,.0f} USD ({btc_qty:.2f} BTC) | Margen: ${margin_used:,.0f} USD ({free_buffer_pct}% Libre)\n"

            pillars = sig.get('pillars', {})
            pillars_str = (
                f"🏛 <b>Pilares Cuantitativos ({sig['score']}/100 pts):</b>\n"
                f"  • Sesión: <code>{pillars.get('session', 0)}/15 pts</code> ({sig.get('session', 'N/A')})\n"
                f"  • Régimen Anti-Chop/TTM: <code>{pillars.get('anti_chop', 0)}/15 pts</code> (Chop: {sig.get('chop', 0):.1f})\n"
                f"  • Rango ORB & ADR 24h: <code>{pillars.get('orb', 0)}/15 pts</code>\n"
                f"  • Estructura VWAP/EMAs/Ichimoku: <code>{pillars.get('structure', 0)}/34 pts</code>\n"
                f"  • Flujo Órdenes (CVD/OI): <code>{pillars.get('order_flow', 0)}/15 pts</code>\n"
                f"  • Barrido Liquidez SFP: <code>{pillars.get('liq_sweep', 0)}/6 pts</code>\n"
            )

            opt_str = ""
            if opt:
                opt_str = (
                    f"🎯 <b>Zona Óptima Retest / Pullback:</b> <code>${opt.get('zone_min', sig['cur_price']):,.2f} - ${opt.get('zone_max', sig['cur_price']):,.2f}</code>\n"
                    f"⏱ <b>Timing Sugerido:</b> {opt.get('timing_advice', 'Entrada activa.')}\n"
                )

            msg = (
                f"{header_title}"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 <b>Puntuación de Confluencia:</b> <code>{sig['score']}%</code> (Umbral Mínimo: {QUANT_CONFIG['min_score_threshold']}%)\n"
                f"💵 <b>Precio de Mercado Actual:</b> ${sig['cur_price']:,.2f}\n"
                f"{opt_str}"
                f"{sizing_line}"
                f"🛑 <b>Stop-Loss:</b> ${sig['sl']:,.2f} (Riesgo: -{sig['sl_pts']} pts | ~-${sl_usd:,.2f} USD)\n"
                f"🎯 <b>TP1 (75% Parcial Asegurado):</b> ${sig['tp1']:,.2f} (+{sig['tp1_pts']} pts)\n"
                f"🏁 <b>TP2 (25% Corredor Final):</b> ${sig['tp2']:,.2f} (+{sig['tp2_pts']} pts | ~+${tp2_usd:,.2f} USD)\n"
                f"⏳ <b>Horizonte Óptimo:</b> 5 Velas 4H (20 Horas)\n"
                f"🛡 <b>Regla Institucional:</b> Al tocar TP1, Stop a Break-Even (+300 pts) (100% Risk-Free)\n"
                f"{pillars_str}"
                f"📈 <b>Motivos:</b> {' • '.join(sig['reasons'])}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"☁️ <i>Quant Guardian 24/7 ejecutándose cada 5 minutos en GitHub Actions.</i>"
            )
            send_telegram_alert(msg)

            # Guardar cache de última alerta para evitar duplicados
            with open(LAST_ALERT_FILE, 'w') as f:
                json.dump({
                    'alert_key': cur_candle_key,
                    'direction': sig['direction'],
                    'score': sig['score'],
                    'price': sig['cur_price'],
                    'is_tier_a_plus': is_a_plus,
                    'notional': notional,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }, f, indent=2)

            # Lógica de Disparo Respetando Retest:
            if timing_status == 'WAIT_PULLBACK':
                # Si el precio está sobreextendido, no entrar a mercado ciegamente. Armar señal pendiente de retest por 2 horas
                if not state.get('open_position') and not state.get('pending_setup'):
                    state['pending_setup'] = {
                        'direction': sig['direction'],
                        'score': sig['score'],
                        'tier': sig.get('tier', 'ESTÁNDAR'),
                        'is_tier_a_plus': is_a_plus,
                        'signal_price': sig['cur_price'],
                        'btc_qty': btc_qty,
                        'notional': notional,
                        'sl': sig['sl'],
                        'sl_pts': sig['sl_pts'],
                        'tp1': sig['tp1'],
                        'tp1_pts': sig['tp1_pts'],
                        'tp2': sig['tp2'],
                        'tp2_pts': sig['tp2_pts'],
                        'zone_min': opt.get('zone_min', sig['cur_price']),
                        'zone_max': opt.get('zone_max', sig['cur_price']),
                        'optimal_price': opt.get('optimal_price', sig['cur_price']),
                        'created_at': datetime.now(timezone.utc).isoformat()
                    }
                    state['last_updated'] = datetime.now(timezone.utc).isoformat()
                    with open(STATE_FILE, 'w') as f:
                        json.dump(state, f, indent=2)
                    print(f"[CLOUD PAPER TRADING] Señal {sig['direction']} armada en espera de retest (${opt.get('zone_min'):,.2f} - ${opt.get('zone_max'):,.2f}). Válida por 2 horas (24 ciclos del cron).")
            else:
                # El precio ya está en zona de retest (ENTER_NOW o PULLBACK_FAVORABLE)
                if not state.get('open_position'):
                    trade_id = f"CLOUD_{int(datetime.now(timezone.utc).timestamp())}"
                    state['open_position'] = {
                        'id': trade_id,
                        'direction': sig['direction'],
                        'entry_price': sig['cur_price'],
                        'notional': notional,
                        'btc_qty': btc_qty,
                        'is_tier_a_plus': is_a_plus,
                        'tier': sig.get('tier', 'ESTÁNDAR'),
                        'sl': sig['sl'],
                        'tp1': sig['tp1'],
                        'tp1_pts': sig['tp1_pts'],
                        'tp2': sig['tp2'],
                        'tp2_pts': sig['tp2_pts'],
                        'tp1_hit': False,
                        'early_exit_warned': False,
                        'opened_at': datetime.now(timezone.utc).isoformat()
                    }
                    state['last_updated'] = datetime.now(timezone.utc).isoformat()
                    with open(STATE_FILE, 'w') as f:
                        json.dump(state, f, indent=2)
                    print(f"[CLOUD PAPER TRADING] Nueva posición autónoma abierta en retest: {sig['direction']} en ${sig['cur_price']:,.2f} ({trade_id})")
                else:
                    print(f"[CLOUD PAPER TRADING] Posición {state['open_position']['direction']} aún abierta. No se abren posiciones concurrentes.")
    else:
        print(f"[STATUS] Sin señal de disparo (Score {sig['score']}% < {QUANT_CONFIG['min_score_threshold']}%).")

if __name__ == '__main__':
    if '--test' in sys.argv or '-t' in sys.argv:
        print("[TEST] Ejecutando prueba de conexión con Telegram vía Secrets / .env local...")
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            print("[TEST ERROR] Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID.")
            print("[GUÍA] Define estas variables en tu archivo .env local o en GitHub Secrets.")
            sys.exit(1)
        now_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        test_msg = (
            f"⚡ <b>[TEST CONEXIÓN] BTC Quant Terminal V6.5</b>\n"
            f"📡 <b>Estado del Enlace:</b> 🟢 100% OPERATIVO\n"
            f"🔐 <b>Origen de Claves:</b> GitHub Secrets / .env local\n"
            f"⏱ <b>Timestamp:</b> {now_utc}\n"
            f"🎯 <i>Listo para recibir alertas cuantitativas 24/7.</i>"
        )
        ok = send_telegram_alert(test_msg)
        if ok:
            print("[TEST ÉXITO] Mensaje de prueba entregado correctamente a Telegram.")
        else:
            print("[TEST FALLO] No se pudo entregar el mensaje a Telegram.")
        sys.exit(0 if ok else 1)

    main()
