#!/usr/bin/env python3
"""
Script de prueba local para simular la llegada de señales sin necesidad de GitHub.
Ejecuta 'bot.py' pasándole variables de entorno exactamente como lo haría GitHub Actions.
"""

import os
import sys
import subprocess

# Asegurar compatibilidad UTF-8 en terminales Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT_SCRIPT = os.path.join(BASE_DIR, "bot.py")


def run_local_signal(action="BUY", symbol="BTCUSDT", price=0.0, amount_usd=500.0, quantity=0.0, source="Test Local", notes=""):
    env = os.environ.copy()
    env["ACTION"] = action
    env["SYMBOL"] = symbol
    env["PRICE"] = str(price)
    env["AMOUNT_USD"] = str(amount_usd)
    env["QUANTITY"] = str(quantity)
    env["SIGNAL_SOURCE"] = source
    env["NOTES"] = notes

    print(f"\n🚀 Simulando señal: {action} {symbol} (Monto: ${amount_usd}, Precio: {price or 'Mercado'})...\n")
    subprocess.run([sys.executable, BOT_SCRIPT], env=env, check=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].upper() == "SELL":
        run_local_signal(action="SELL", symbol="BTCUSDT", notes="Venta de prueba local")
    else:
        run_local_signal(action="BUY", symbol="BTCUSDT", amount_usd=750.0, notes="Compra de prueba local")
