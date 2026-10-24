#!/usr/bin/env python3
"""
BTC Quant Terminal V6.5 - Unified Cloud Guardian Engine (quant_bot_24_7.py)
Autonomous Engine for GitHub Actions, Cloud Runners & Local Services
Uses Unified engine.quant_core (Single Source of Truth) with:
  - Real Native Order Flow & Taker CVD
  - Orthogonal 3-Factor Model & Calibrated Logistic Probability
  - Dynamic Volatility ATR Targets (SL / TP1 / TP2)
  - Fixed Fractional Account Risk Sizing (2% Capital Risk)
"""

import os
import sys
import json
import time
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Import Unified Engine Core
from engine.quant_core import (
    Kline,
    evaluate_signal,
    calculate_atr,
    calculate_dynamic_targets,
    calculate_fixed_fractional_size,
    QUANT_CONFIG
)

# 1. CONFIGURATION & CREDENTIALS
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

# Local .env fallback support
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

STATE_FILE = 'state.json'
LAST_ALERT_FILE = 'last_alert.json'
JOURNAL_FILE = 'journal.json'


# 2. TELEGRAM DISPATCHER
def send_telegram_alert(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TELEGRAM CONFIG ERROR] Alerta NO enviada: Falta TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID.")
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
                plain_text = text.replace('<b>', '').replace('</b>', '').replace('<code>', '').replace('</code>', '').replace('<i>', '').replace('</i>', '')
                plain_payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': plain_text}
                plain_data = json.dumps(plain_payload).encode('utf-8')
                plain_req = urllib.request.Request(
                    TELEGRAM_API_URL, data=plain_data,
                    headers={'Content-Type': 'application/json', 'User-Agent': 'BTCQuantGuardian/6.5'}
                )
                with urllib.request.urlopen(plain_req, timeout=10) as resp:
                    return json.loads(resp.read().decode('utf-8')).get('ok', False)
        except Exception:
            pass
        return False
    except Exception as e:
        print(f"[TELEGRAM ERROR] No se pudo enviar mensaje: {e}")
        return False


# 3. BINANCE DATA FETCHING WITH NATIVE TAKER FLOW
def fetch_binance_klines(symbol: str = 'BTCUSDT', timeframe: str = '4h', limit: int = 500) -> Optional[list[Kline]]:
    endpoints = [
        f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={timeframe}&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={timeframe}&limit={limit}",
        f"https://api1.binance.com/api/v3/klines?symbol={symbol}&interval={timeframe}&limit={limit}"
    ]

    for url in endpoints:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'BTCQuantGuardian/6.5'})
            with urllib.request.urlopen(req, timeout=12) as response:
                raw = json.loads(response.read().decode('utf-8'))
                if isinstance(raw, list) and len(raw) > 50:
                    klines = [Kline.from_raw(k) for k in raw]
                    native_str = "🟢 Nativo Binance (Columna 9)" if klines[-1].is_taker_native else "⚪ Sintético"
                    print(f"[DATA] {len(klines)} velas cargadas desde {url.split('/')[2]} | Taker Flow: {native_str}")
                    return klines
        except Exception as e:
            print(f"[DATA WARN] Falló endpoint {url}: {e}")
            continue

    print("[DATA ERROR] No se pudieron obtener velas de ningún endpoint de Binance.")
    return None


def fetch_binance_open_interest(symbol: str = 'BTCUSDT') -> Optional[float]:
    try:
        url = f"https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}"
        req = urllib.request.Request(url, headers={'User-Agent': 'BTCQuantGuardian/6.5'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            oi = float(data.get('openInterest', 0))
            print(f"[DATA] Binance Futures Open Interest actual: {oi:,.2f} BTC")
            return oi
    except Exception as e:
        print(f"[DATA WARN] No se pudo obtener Open Interest de Futuros: {e}")
        return None


def fetch_binance_ticker_price(symbol: str = 'BTCUSDT') -> Optional[float]:
    endpoints = [
        f"https://data-api.binance.vision/api/v3/ticker/price?symbol={symbol}",
        f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}",
        f"https://api1.binance.com/api/v3/ticker/price?symbol={symbol}"
    ]
    for url in endpoints:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'BTCQuantGuardian/6.5'})
            with urllib.request.urlopen(req, timeout=6) as response:
                data = json.loads(response.read().decode('utf-8'))
                return float(data['price'])
        except Exception:
            continue
    return None


# 4. STATE & POSITION MANAGEMENT
def push_git_state_update(commit_message: str = "chore: sync quant guardian state"):
    try:
        if os.path.exists('.git'):
            os.system('git config --global user.name "github-actions[bot]" 2>/dev/null')
            os.system('git config --global user.email "github-actions[bot]@users.noreply.github.com" 2>/dev/null')
            os.system('git add last_alert.json state.json journal.json 2>/dev/null')
            os.system(f'git diff --staged --quiet || (git commit -m "{commit_message} [skip ci]" && git push) 2>/dev/null')
    except Exception as e:
        print(f"[GIT SYNC ERROR] {e}")


def load_state() -> Dict[str, Any]:
    state = {
        'open_position': None,
        'pending_setup': None,
        'last_known_oi': None,
        'oi_delta': 0.0,
        'bankroll_usdt': QUANT_CONFIG['bankroll_usdt'],
        'last_updated': datetime.now(timezone.utc).isoformat()
    }
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    state.update(loaded)
        except Exception as e:
            print(f"[STATE LOAD WARN] {e}")
    return state


def save_state(state: Dict[str, Any]):
    state['last_updated'] = datetime.now(timezone.utc).isoformat()
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[STATE SAVE ERROR] {e}")


def record_closed_trade(pos: Dict[str, Any], exit_price: float, reason: str, state: Dict[str, Any]):
    is_long = pos['direction'] == 'LONG'
    pts = (exit_price - pos['entry_price']) if is_long else (pos['entry_price'] - exit_price)
    btc_qty = pos.get('btc_qty', 0.25)
    notional = pos.get('notional', btc_qty * pos['entry_price'])

    tp1_hit = pos.get('tp1_hit', False)
    realized_usd = pos.get('realized_usd', 0.0)

    if tp1_hit:
        rem_qty = btc_qty * (1.0 - QUANT_CONFIG['tp1_partial_pct'])
        rem_pnl = pts * rem_qty
    else:
        rem_pnl = pts * btc_qty

    friction_usd = max(btc_qty * 35.0, notional * 0.0004)
    total_net_usd = (realized_usd + rem_pnl) - friction_usd
    total_net_pts = round(total_net_usd / btc_qty) if btc_qty > 0 else round(pts)

    margin_used = notional / QUANT_CONFIG['max_effective_leverage']
    roi_pct = round((total_net_usd / margin_used) * 100.0, 1) if margin_used > 0 else 0.0

    trade_record = {
        'id': pos.get('id', f"CLOUD_{int(datetime.now(timezone.utc).timestamp())}"),
        'isAutonomous': True,
        'direction': pos['direction'],
        'tier': pos.get('tier', 'ESTÁNDAR'),
        'openedAt': pos.get('opened_at', datetime.now(timezone.utc).isoformat()),
        'closedAt': datetime.now(timezone.utc).isoformat(),
        'entryPrice': pos['entry_price'],
        'exitPrice': exit_price,
        'size': btc_qty,
        'notional': round(notional, 2),
        'netPts': total_net_pts,
        'netPnlUsd': round(total_net_usd, 2),
        'roiPct': roi_pct,
        'reason': f"🤖 Quant Guardian [{reason}]",
        'tp1Hit': tp1_hit
    }

    # Update bankroll in state
    state['bankroll_usdt'] = round(state.get('bankroll_usdt', QUANT_CONFIG['bankroll_usdt']) + total_net_usd, 2)

    journal = []
    if os.path.exists(JOURNAL_FILE):
        try:
            with open(JOURNAL_FILE, 'r', encoding='utf-8') as f:
                journal = json.load(f)
        except Exception:
            journal = []

    journal.insert(0, trade_record)
    try:
        with open(JOURNAL_FILE, 'w', encoding='utf-8') as f:
            json.dump(journal, f, indent=2)
        print(f"[JOURNAL] Trade registrado: {total_net_pts:+} pts (${total_net_usd:,.2f} USD) | Nuevo Capital: ${state['bankroll_usdt']:,.2f}")
        push_git_state_update(f"chore: record closed trade ({reason})")
    except Exception as e:
        print(f"[JOURNAL ERROR] {e}")


def monitor_live_position(cur_price: float, klines: list[Kline], state: Dict[str, Any]):
    pos = state.get('open_position')
    if not pos:
        return

    is_long = pos['direction'] == 'LONG'
    pts = (cur_price - pos['entry_price']) if is_long else (pos['entry_price'] - cur_price)
    atr = calculate_atr(klines, 14)

    # 1. TP1 Target Check
    tp1_target = pos.get('tp1_pts', 2.0 * atr)
    if not pos.get('tp1_hit') and pts >= tp1_target:
        pos['tp1_hit'] = True
        pos['tp1_hit_time'] = datetime.now(timezone.utc).isoformat()
        be_lock = pos.get('be_lock_pts', 0.30 * atr)
        pos['sl'] = (pos['entry_price'] + be_lock) if is_long else (pos['entry_price'] - be_lock)
        pos['peak_price'] = cur_price
        btc_qty = pos.get('btc_qty', 0.25)
        partial_frac = QUANT_CONFIG['tp1_partial_pct']
        realized_tp1_usd = tp1_target * partial_frac * btc_qty
        pos['realized_usd'] = pos.get('realized_usd', 0.0) + realized_tp1_usd

        msg = (
            f"🎯 <b>¡TAKE PROFIT (TP1) ALCANZADO (+{round(tp1_target)} PTS)!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Dirección: <b>{pos['direction']}</b> ({pos.get('tier', 'ESTÁNDAR')})\n"
            f"💵 <b>Precio Actual:</b> ${cur_price:,.2f}\n"
            f"💰 <b>Toma Parcial:</b> {int(partial_frac * 100)}% asegurado (+${realized_tp1_usd:,.2f} USD)\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🛡 <b>ACCIÓN REQUERIDA (EXCHANGE):</b>\n"
            f"👉 Mueve Stop-Loss a <b>Break-Even + {round(be_lock)} pts</b> (${pos['sl']:,.2f})\n"
            f"🚀 <i>{int((1.0 - partial_frac) * 100)}% corredor 100% RISK-FREE buscando TP2 (+{pos.get('tp2_pts', 3.5 * atr):.0f} pts)!</i>"
        )
        send_telegram_alert(msg)
        save_state(state)
        push_git_state_update("chore: live guardian TP1 hit and moved SL to BE")

    # Dynamic Trailing SL after TP1
    elif pos.get('tp1_hit'):
        peak = pos.get('peak_price', cur_price)
        if (is_long and cur_price > peak) or (not is_long and cur_price < peak):
            pos['peak_price'] = cur_price
            peak = cur_price

        fav_dist = (peak - pos['entry_price']) if is_long else (pos['entry_price'] - peak)
        trail_trigger = pos.get('trailing_trigger', 2.2 * atr)
        if fav_dist >= trail_trigger:
            trail_dist = pos.get('trailing_distance', 1.2 * atr)
            new_sl = (peak - trail_dist) if is_long else (peak + trail_dist)
            if (is_long and new_sl > pos['sl']) or (not is_long and new_sl < pos['sl']):
                pos['sl'] = new_sl

    # 2. TP2 Target Check
    tp2_target = pos.get('tp2_pts', 3.5 * atr)
    if pts >= tp2_target:
        msg = (
            f"🏁 <b>OBJETIVO FINAL TP2 ALCANZADO (+{round(pts)} PTS)!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Dirección: <b>{pos['direction']}</b>\n"
            f"💵 Cierre en: ${cur_price:,.2f}\n"
            f"🎉 Operación finalizada con éxito completo."
        )
        send_telegram_alert(msg)
        record_closed_trade(pos, cur_price, f"TP2 FINAL (+{round(pts)} PTS)", state)
        state['open_position'] = None
        save_state(state)
        return

    # 3. Stop-Loss Check
    sl_hit = (cur_price <= pos['sl']) if is_long else (cur_price >= pos['sl'])
    if sl_hit:
        reason_sl = f"STOP BREAK-EVEN (+{round(pos.get('be_lock_pts', 0))} pts)" if pos.get('tp1_hit') else f"STOP-LOSS (-{round(pos.get('sl_pts', 0))} pts)"
        msg = (
            f"🛑 <b>{reason_sl} EJECUTADO</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Dirección: <b>{pos['direction']}</b>\n"
            f"💵 Precio Cierre: ${cur_price:,.2f}\n"
            f"📉 Resultado Puntos: {round(pts):+} pts"
        )
        send_telegram_alert(msg)
        record_closed_trade(pos, cur_price, reason_sl, state)
        state['open_position'] = None
        save_state(state)
        return

    # 4. Timeout Check (Max Hold Duration)
    opened_str = pos.get('opened_at')
    if opened_str:
        try:
            opened_dt = datetime.fromisoformat(opened_str)
            elapsed_hours = (datetime.now(timezone.utc) - opened_dt).total_seconds() / 3600.0
            max_hours = 20.0
            if elapsed_hours >= max_hours:
                msg = (
                    f"⌛ <b>CIERRE POR TIEMPO MÁXIMO ({max_hours:.0f}H)</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Dirección: <b>{pos['direction']}</b>\n"
                    f"💵 Precio Cierre: ${cur_price:,.2f}\n"
                    f"📊 PnL: {round(pts):+} pts\n"
                    f"💡 Posición liquidada por límite de tiempo de la estrategia."
                )
                send_telegram_alert(msg)
                record_closed_trade(pos, cur_price, f"LÍMITE TIEMPO {max_hours:.0f}H", state)
                state['open_position'] = None
                save_state(state)
        except Exception:
            pass


# 5. SIGNAL EVALUATION & EXECUTION PIPELINE
def evaluate_and_trigger_new_signal(klines: list[Kline], state: Dict[str, Any], oi_delta: float = 0.0):
    sig = evaluate_signal(klines, oi_delta=oi_delta)
    if not sig:
        print("[ANALYSIS] Sin datos suficientes.")
        return

    factors = sig['factors']
    indicators = sig['indicators']
    targets = sig['targets']
    sizing = sig['sizing']

    print(f"[ANALYSIS] Dirección: {sig['direction']} | P(Éxito): {sig['score']}% | Factores [Z_trend: {factors['z_trend']:+.2f}, R_regime: {factors['r_regime']:.2f}, P_flow: {factors['p_flow']:+.2f}]")

    last_alert_key = None
    if os.path.exists(LAST_ALERT_FILE):
        try:
            with open(LAST_ALERT_FILE, 'r', encoding='utf-8') as f:
                last_alert_key = json.load(f).get('alert_key')
        except Exception:
            pass

    cur_candle_key = f"{sig['direction']}_{sig.get('timestamp')}_{sig.get('tier')}"

    if sig['direction'] in ('LONG', 'SHORT'):
        is_duplicate = (last_alert_key == cur_candle_key)
        if is_duplicate:
            print(f"[ALERT SKIP] Alerta idéntica ya enviada para {cur_candle_key}.")
        else:
            print(f"[SEÑAL DISPARADA] P(Éxito): {sig['score']}% [{sig['direction']}]! Despachando a Telegram...")
            is_a_plus = sig['is_tier_a_plus']
            tier_label = "💎 TIER A+ (ALTA CONVICCIÓN)" if is_a_plus else "⚡ ESTÁNDAR"

            taker_native_str = "🟢 Nativo Binance" if indicators['is_taker_native'] else "⚪ Sintético"

            msg = (
                f"{'💎' if is_a_plus else '🚀'} <b>[BTC QUANT V6.5] SEÑAL CALIBRADA [{sig['direction']}]</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 <b>Nivel:</b> <b>{tier_label}</b>\n"
                f"📈 <b>Probabilidad de Éxito Calibrada:</b> <code>{sig['score']}%</code>\n"
                f"💵 <b>Precio Actual:</b> ${sig['cur_price']:,.2f}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🏛 <b>Modelo de 3 Factores Ortogonales:</b>\n"
                f"  • Inercia / Tendencia (Z-Trend): <code>{factors['z_trend']:+.2f}</code>\n"
                f"  • Régimen Volatilidad (R-Regime): <code>{factors['r_regime']:.2f}</code> (Chop: {indicators['chop']})\n"
                f"  • Flujo Órdenes Real (P-Flow): <code>{factors['p_flow']:+.2f}</code> ({indicators['taker_ratio']*100:+.1f}% Taker)\n"
                f"  • Fuente Flujo: {taker_native_str}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💼 <b>Dimensionamiento por Riesgo Fijo (Fixed Fractional):</b>\n"
                f"  • Riesgo de Cuenta: <code>{sizing['risk_pct']}%</code> (${sizing['risk_usd']:,.2f} USD)\n"
                f"  • Tamaño Posición: <code>{sizing['size_btc']:.4f} BTC</code> (${sizing['notional_usd']:,.2f} USD)\n"
                f"  • Apalancamiento Efectivo: <code>{sizing['effective_leverage']}x</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🛑 <b>Stop-Loss Dinámico (1.5x ATR):</b> ${targets['sl']:,.2f} (-{targets['sl_dist']} pts)\n"
                f"🎯 <b>TP1 Parcial (75%):</b> ${targets['tp1']:,.2f} (+{targets['tp1_dist']} pts)\n"
                f"🏁 <b>TP2 Corredor (25%):</b> ${targets['tp2']:,.2f} (+{targets['tp2_dist']} pts)\n"
                f"🛡 <i>Al alcanzar TP1, Stop a Break-Even + {targets['be_lock_pts']} pts automático.</i>"
            )
            send_telegram_alert(msg)

            # Save alert cache
            try:
                with open(LAST_ALERT_FILE, 'w', encoding='utf-8') as f:
                    json.dump({
                        'alert_key': cur_candle_key,
                        'direction': sig['direction'],
                        'score': sig['score'],
                        'price': sig['cur_price'],
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }, f, indent=2)
            except Exception:
                pass

            # Open Live Cloud Paper Trading position if FLAT
            if not state.get('open_position'):
                trade_id = f"CLOUD_{int(datetime.now(timezone.utc).timestamp())}"
                state['open_position'] = {
                    'id': trade_id,
                    'direction': sig['direction'],
                    'entry_price': sig['cur_price'],
                    'btc_qty': sizing['size_btc'],
                    'notional': sizing['notional_usd'],
                    'is_tier_a_plus': is_a_plus,
                    'tier': sig['tier'],
                    'sl': targets['sl'],
                    'sl_pts': targets['sl_dist'],
                    'tp1': targets['tp1'],
                    'tp1_pts': targets['tp1_dist'],
                    'tp2': targets['tp2'],
                    'tp2_pts': targets['tp2_dist'],
                    'be_lock_pts': targets['be_lock_pts'],
                    'trailing_trigger': targets['trailing_trigger'],
                    'trailing_distance': targets['trailing_distance'],
                    'tp1_hit': False,
                    'opened_at': datetime.now(timezone.utc).isoformat()
                }
                save_state(state)
                push_git_state_update("chore: cloud guardian opened trade")
                print(f"[PAPER TRADING] Nueva posición abierta: {sig['direction']} en ${sig['cur_price']:,.2f} ({sizing['size_btc']} BTC)")
    else:
        print(f"[STATUS] Sin señal de disparo activa. Dominante: {sig.get('dominant_dir')} ({sig['score']}%)")

    save_state(state)


# 6. RUNNER MODES: SINGLE CYCLE & CONTINUOUS DAEMON
def run_single_cycle():
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] Escaneo Cuántico Unificado V6.5...")
    klines = fetch_binance_klines(timeframe=QUANT_CONFIG.get('timeframe', '4h'))
    if not klines:
        print("[ERROR] Imposible continuar sin velas.")
        sys.exit(1)

    cur_price = klines[-1].c
    print(f"[PRECIO BTC] ${cur_price:,.2f}")

    current_oi = fetch_binance_open_interest()
    state = load_state()
    oi_delta = 0.0

    if current_oi is not None:
        last_oi = state.get('last_known_oi')
        if last_oi is not None:
            oi_delta = current_oi - float(last_oi)
        state['last_known_oi'] = current_oi
        state['oi_delta'] = oi_delta
        print(f"[OPEN INTEREST] OI: {current_oi:,.1f} BTC | Delta: {oi_delta:+,.1f} BTC")

    # Monitor open position
    monitor_live_position(cur_price, klines, state)

    # Evaluate new signals
    evaluate_and_trigger_new_signal(klines, state, oi_delta=oi_delta)


def run_continuous(duration_seconds: int = 2700, interval_seconds: int = 15):
    start_time = time.time()
    end_time = start_time + duration_seconds
    cycle = 0
    full_scan_interval = 60
    last_full_scan = 0

    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] Iniciando GUARDIAN CONTINUO 24/7...")
    state = load_state()
    klines = fetch_binance_klines(timeframe=QUANT_CONFIG.get('timeframe', '4h'))
    if not klines:
        return

    current_oi = fetch_binance_open_interest()
    oi_delta = 0.0
    if current_oi is not None and state.get('last_known_oi') is not None:
        oi_delta = current_oi - float(state['last_known_oi'])
        state['last_known_oi'] = current_oi
        state['oi_delta'] = oi_delta
        save_state(state)

    evaluate_and_trigger_new_signal(klines, state, oi_delta=oi_delta)
    last_full_scan = time.time()

    while time.time() < end_time:
        cycle += 1
        now = time.time()
        try:
            cur_price = fetch_binance_ticker_price()
            if cur_price:
                klines[-1].c = cur_price
                if cur_price > klines[-1].h: klines[-1].h = cur_price
                if cur_price < klines[-1].l: klines[-1].l = cur_price

                if state.get('open_position'):
                    monitor_live_position(cur_price, klines, state)

            if (now - last_full_scan) >= full_scan_interval:
                fresh = fetch_binance_klines(timeframe=QUANT_CONFIG.get('timeframe', '4h'))
                if fresh:
                    klines = fresh
                    cur_price = klines[-1].c
                evaluate_and_trigger_new_signal(klines, state, oi_delta=oi_delta)
                last_full_scan = now

                pos = state.get('open_position')
                pos_str = f"{pos['direction']} @ ${pos['entry_price']:,.1f} (SL: ${pos['sl']:,.1f})" if pos else "FLAT"
                print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}] Heartbeat #{cycle} | BTC: ${cur_price:,.2f} | Pos: {pos_str}")

        except Exception as e:
            print(f"[LOOP WARN] {e}")

        time.sleep(interval_seconds)

    push_git_state_update("chore: continuous session handover")


def main():
    if '--continuous' in sys.argv or '-c' in sys.argv:
        run_continuous()
    else:
        run_single_cycle()


if __name__ == '__main__':
    if '--test' in sys.argv or '-t' in sys.argv:
        print("[TEST] Verificando conectividad Telegram y Motor Unificado V6.5...")
        msg = "⚡ <b>[TEST UNIFICADO V6.5]</b> BTC Quant Terminal conectado y operativo con motor <code>engine.quant_core</code>."
        ok = send_telegram_alert(msg)
        print("[TEST RESULTADO]", "Éxito" if ok else "Fallo (Credenciales faltantes o incorrectas)")
        sys.exit(0 if ok else 1)
    main()
