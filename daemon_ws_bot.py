#!/usr/bin/env python3
"""
BTC Quant Terminal V6.5 - Real-Time WebSocket Daemon (daemon_ws_bot.py)
Replaces periodic GitHub Actions Cron polling with an ultra-low latency (<50ms)
event-driven architecture connected directly to Binance WebSockets.

Features:
- Real-time tick monitoring for immediate SL / TP / Break-Even execution.
- Native Binance Order Flow & Taker CVD streaming.
- Auto-reconnecting WebSocket engine with heartbeat surveillance.
- Zero server costs or VPS ready (Docker Compose compatible).
"""

import os
import sys
import json
import time
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import websockets

from engine.quant_core import (
    Kline,
    evaluate_signal,
    calculate_atr,
    calculate_dynamic_targets,
    calculate_fixed_fractional_size,
    QUANT_CONFIG
)
from quant_bot_24_7 import (
    fetch_binance_klines,
    fetch_binance_open_interest,
    send_telegram_alert,
    load_state,
    save_state,
    monitor_live_position,
    evaluate_and_trigger_new_signal,
    STATE_FILE,
    JOURNAL_FILE
)

BINANCE_WS_URL = "wss://stream.binance.com:9443/ws/btcusdt@kline_4h"


class BinanceQuantDaemon:
    def __init__(self, symbol: str = 'btcusdt', timeframe: str = '4h'):
        self.symbol = symbol.lower()
        self.timeframe = timeframe.lower()
        self.ws_url = f"wss://stream.binance.com:9443/ws/{self.symbol}@kline_{self.timeframe}"
        self.state = load_state()
        self.klines: list[Kline] = []
        self.last_oi_fetch_time = 0.0
        self.oi_delta = 0.0
        self.is_running = True

    async def initialize_history(self):
        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}] Inicializando historial de velas para {self.symbol.upper()} ({self.timeframe})...")
        fresh = fetch_binance_klines(symbol=self.symbol.upper(), timeframe=self.timeframe, limit=200)
        if fresh:
            self.klines = fresh
            print(f"[DAEMON] {len(self.klines)} velas cargadas en memoria. Último cierre: ${self.klines[-1].c:,.2f}")
        else:
            print("[DAEMON ERROR] No se pudieron cargar velas históricas iniciales.")

        oi = fetch_binance_open_interest(self.symbol.upper())
        if oi is not None:
            last_oi = self.state.get('last_known_oi')
            if last_oi is not None:
                self.oi_delta = oi - float(last_oi)
            self.state['last_known_oi'] = oi
            self.state['oi_delta'] = self.oi_delta
            save_state(self.state)
            self.last_oi_fetch_time = time.time()

    async def handle_candle_update(self, kline_data: Dict[str, Any]):
        """
        Processes real-time kline WebSocket payloads from Binance.
        """
        k = kline_data['k']
        cur_price = float(k['c'])
        high_price = float(k['h'])
        low_price = float(k['l'])
        is_candle_closed = k['x']
        tbv = float(k.get('V', 0.0))  # Taker buy base asset volume in stream

        # 1. Update latest kline in memory
        if self.klines:
            self.klines[-1].c = cur_price
            if high_price > self.klines[-1].h: self.klines[-1].h = high_price
            if low_price < self.klines[-1].l: self.klines[-1].l = low_price
            if tbv > 0: self.klines[-1].tbv = tbv

        # 2. Sub-second Position Guardian: check open position stops/targets
        if self.state.get('open_position'):
            monitor_live_position(cur_price, self.klines, self.state)

        # 3. Periodic Open Interest update every 5 minutes
        now = time.time()
        if (now - self.last_oi_fetch_time) >= 300:
            fresh_oi = fetch_binance_open_interest(self.symbol.upper())
            if fresh_oi is not None:
                if self.state.get('last_known_oi') is not None:
                    self.oi_delta = fresh_oi - float(self.state['last_known_oi'])
                self.state['last_known_oi'] = fresh_oi
                self.state['oi_delta'] = self.oi_delta
                save_state(self.state)
            self.last_oi_fetch_time = now

        # 4. If candle just finalized (or periodic evaluation), re-run signal pipeline
        if is_candle_closed:
            print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}] 🔔 ¡Vela {self.timeframe} CERRADA en ${cur_price:,.2f}! Evaluando señal cuantitativa...")
            fresh_kline = Kline(k['t'], float(k['o']), high_price, low_price, cur_price, float(k['v']), tbv)
            self.klines.append(fresh_kline)
            if len(self.klines) > 300:
                self.klines.pop(0)

            evaluate_and_trigger_new_signal(self.klines, self.state, oi_delta=self.oi_delta)

    async def run_websocket_loop(self):
        reconnect_delay = 2
        max_reconnect_delay = 60

        while self.is_running:
            try:
                print(f"[WEBSOCKET] Conectando a {self.ws_url}...")
                async with websockets.connect(
                    self.ws_url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5
                ) as ws:
                    print(f"🟢 [WEBSOCKET CONECTADO] Flujo en tiempo real activo para {self.symbol.upper()} ({self.timeframe}).")
                    reconnect_delay = 2  # Reset backoff on success

                    # Initial scan upon connect
                    if self.klines:
                        evaluate_and_trigger_new_signal(self.klines, self.state, oi_delta=self.oi_delta)

                    async for message in ws:
                        data = json.loads(message)
                        if 'k' in data:
                            await self.handle_candle_update(data)

            except (websockets.ConnectionClosed, websockets.WebSocketException) as e:
                print(f"[WEBSOCKET WARN] Conexión interrumpida: {e}. Reintentando en {reconnect_delay}s...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(max_reconnect_delay, reconnect_delay * 2)

            except Exception as e:
                print(f"[DAEMON ERROR] Excepción inesperada en bucle: {e}")
                await asyncio.sleep(5)


async def main_async():
    tf = os.environ.get('QUANT_TIMEFRAME', '4h').lower()
    symbol = os.environ.get('QUANT_SYMBOL', 'btcusdt').lower()
    daemon = BinanceQuantDaemon(symbol=symbol, timeframe=tf)
    await daemon.initialize_history()
    await daemon.run_websocket_loop()


def main():
    print("=" * 70)
    print("🚀 BTC QUANT TERMINAL V6.5 — DAEMON DE ALTA FRECUENCIA WEBSOCKET")
    print("=" * 70)
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n[DAEMON] Apagado ordenado solicitado por usuario (Ctrl+C).")


if __name__ == '__main__':
    main()
