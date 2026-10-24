#!/usr/bin/env python3
"""
Monitor Autónomo en Segundo Plano (GitHub Actions Cron).
Se ejecuta automáticamente cada 5 minutos en la nube, lee la web configurada en 'config.json',
detecta si hay una nueva señal de COMPRA o VENTA y efectúa la orden de Paper Trading
sin necesidad de que el usuario tenga abierto el navegador ni el PC encendido.
"""

import os
import sys
import json
from datetime import datetime, timezone

# Asegurar codificación UTF-8
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
DATA_DIR = os.path.join(BASE_DIR, "data")
LAST_SIGNAL_FILE = os.path.join(DATA_DIR, "last_signal.json")

# Importar motor del bot y extractor web
from bot import (
    load_portfolio,
    execute_buy,
    execute_sell,
    fetch_live_price_fallback,
    get_current_utc_str
)
from reader import read_signal_from_web


def load_config() -> dict:
    default_config = {
        "target_url": "https://TU_USUARIO.github.io/TU_WEB_REPOSITORIO/",
        "default_symbol": "BTCUSDT",
        "default_amount_usd": 500.0,
        "anti_duplicate": True,
        "html_custom_selector": "signal"
    }
    if not os.path.exists(CONFIG_FILE):
        return default_config
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return {**default_config, **json.load(f)}


def load_last_signal() -> dict:
    if not os.path.exists(LAST_SIGNAL_FILE):
        return {
            "last_action": None,
            "last_symbol": None,
            "last_checked_timestamp": None,
            "last_executed_trade_id": None
        }
    with open(LAST_SIGNAL_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_last_signal(state: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LAST_SIGNAL_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def run_monitor():
    print("=" * 65)
    print("🛰️  MONITOR AUTÓNOMO DE SEÑALES WEB (GITHUB ACTIONS)")
    print(f"🕒  Timestamp: {get_current_utc_str()}")
    print("=" * 65)

    config = load_config()
    target_url = os.getenv("TARGET_URL", config.get("target_url", "")).strip()
    default_symbol = config.get("default_symbol", "BTCUSDT")
    default_amount = float(config.get("default_amount_usd", 500.0))
    custom_selector = config.get("html_custom_selector", "signal")
    anti_duplicate = config.get("anti_duplicate", True)

    print(f"🎯 URL de monitoreo: {target_url}")
    print(f"⚙️  Activo por defecto: {default_symbol} | Monto: ${default_amount:,.2f} USD")

    # Validar si el usuario aún no configuró su URL real
    is_local_path = os.path.exists(target_url)
    if "TU_USUARIO" in target_url or (not target_url.startswith(("http://", "https://")) and not is_local_path):
        print("\n⚠️  [AVISO DE CONFIGURACIÓN]")
        print("   Aún no has configurado la URL real de tu web en 'config.json'.")
        print("   Edita 'config.json' y reemplaza 'target_url' con el enlace a tu web o archivo en GitHub.")
        print("   El monitor continuará activo y revisará la página en la siguiente ronda.")
        return


    # Leer e interpretar la web
    parsed = read_signal_from_web(
        url=target_url,
        custom_selector=custom_selector,
        default_symbol=default_symbol,
        default_amount=default_amount
    )

    if not parsed.get("success"):
        print(f"\n❌ [ERROR AL LEER LA WEB]: {parsed.get('error')}")
        return

    signal = parsed.get("signal", "HOLD")
    symbol = parsed.get("symbol", default_symbol)
    price = float(parsed.get("price", 0.0))
    amount_usd = float(parsed.get("amount_usd", default_amount))
    format_type = parsed.get("format", "UNKNOWN")
    raw_match = parsed.get("raw_match", "")

    print(f"\n📡 Resultado de lectura ({format_type}):")
    print(f"   • Señal detectada: {signal}")
    print(f"   • Activo: {symbol}")
    print(f"   • Coincidencia: '{raw_match}'")

    last_state = load_last_signal()
    last_state["last_checked_timestamp"] = get_current_utc_str()

    if signal == "HOLD":
        print("\n💤 Estado en HOLD / Espera. No se requiere ejecutar ninguna operación.")
        save_last_signal(last_state)
        return

    # Control de duplicados: evitar comprar/vender repetidamente cada 5 minutos sobre la misma señal
    if anti_duplicate:
        if last_state.get("last_action") == signal and last_state.get("last_symbol") == symbol:
            print(f"\n⏳ [FILTRO ANTIDUPLICADO ACTIVO]")
            print(f"   La señal detectada ({signal} en {symbol}) ya fue ejecutada en la ronda anterior.")
            print(f"   El bot esperará un cambio de señal (ej: de BUY a SELL o cambio de activo) antes de operar de nuevo.")
            save_last_signal(last_state)
            return

    # Si no se pasó precio en la web, obtener precio en vivo de mercado
    if price <= 0:
        print(f"\n[Info] Consultando precio de mercado en tiempo real para {symbol}...")
        price = fetch_live_price_fallback(symbol)
        if price <= 0:
            print(f"❌ No se pudo determinar el precio para {symbol}. Operación abortada.")
            return

    portfolio = load_portfolio()
    source_label = f"Web Auto-Reader ({format_type})"
    notes = f"Detectado automáticamente en: {target_url}"

    success = False
    if signal == "BUY":
        success = execute_buy(portfolio, symbol, price, amount_usd, source_label, notes)
    elif signal == "SELL":
        # En caso de venta automática, si no se especificó cantidad, vende el 100% de la posición existente
        success = execute_sell(portfolio, symbol, price, 0.0, source_label, notes)

    if success:
        last_state["last_action"] = signal
        last_state["last_symbol"] = symbol
        last_state["last_price"] = price
        last_state["status"] = "EXECUTED"
        save_last_signal(last_state)
        print(f"\n🎉 ¡Orden de {signal} ejecutada y registrada con éxito en data/trades.csv!")
    else:
        print(f"\n⚠️ La orden de {signal} no pudo completarse (revisa fondos o posiciones).")


if __name__ == "__main__":
    run_monitor()
