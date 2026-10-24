#!/usr/bin/env python3
"""
Script para reiniciar el portafolio y el registro de operaciones.
Útil para comenzar una nueva fase de pruebas desde cero.
"""

import os
import json
import csv
import sys

# Asegurar compatibilidad UTF-8 en terminales Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
PORTFOLIO_FILE = os.path.join(DATA_DIR, "portfolio.json")
TRADES_FILE = os.path.join(DATA_DIR, "trades.csv")
SUMMARY_FILE = os.path.join(DATA_DIR, "SUMMARY.md")


def reset(initial_capital: float = 10000.0):
    os.makedirs(DATA_DIR, exist_ok=True)

    portfolio = {
        "currency": "USD",
        "initial_capital": initial_capital,
        "cash_balance": initial_capital,
        "positions": {},
        "total_trades": 0,
        "last_updated": None
    }
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, indent=2, ensure_ascii=False)

    fieldnames = [
        "timestamp", "trade_id", "action", "symbol", "price",
        "quantity", "total_value", "fee", "balance_after",
        "pnl", "signal_source", "status", "notes"
    ]
    with open(TRADES_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        f.write("# 📊 Resumen de Operaciones y Portafolio\n\n_Portafolio reiniciado. Listo para recibir operaciones._\n")

    print(f"✅ Portafolio reiniciado con éxito. Capital inicial: ${initial_capital:,.2f} USD")


if __name__ == "__main__":
    cap = 10000.0
    if len(sys.argv) > 1:
        try:
            cap = float(sys.argv[1])
        except ValueError:
            pass
    reset(cap)
