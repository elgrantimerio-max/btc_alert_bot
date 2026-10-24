#!/usr/bin/env python3
"""
Script de Análisis de Operaciones para el Trading Bot.
Lee 'data/trades.csv' y 'data/portfolio.json' y genera métricas estadísticas completas:
Tasa de aciertos (Win Rate), Ganancia Neta (PnL), Comisiones pagadas, Mejor y Peor operación.
"""

import os
import csv
import json
import sys

# Asegurar compatibilidad UTF-8 en terminales Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRADES_FILE = os.path.join(BASE_DIR, "data", "trades.csv")
PORTFOLIO_FILE = os.path.join(BASE_DIR, "data", "portfolio.json")


def analyze():
    print("=" * 65)
    print("📈 INFORME DE RENDIMIENTO Y ANÁLISIS DE OPERACIONES")
    print("=" * 65)

    if not os.path.exists(TRADES_FILE):
        print(f"[!] No se encontró el archivo {TRADES_FILE}. Ejecuta alguna operación primero.")
        return

    trades = []
    with open(TRADES_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("status") == "FILLED":
                trades.append(row)

    if not trades:
        print("No hay operaciones completadas (FILLED) para analizar aún.")
        return

    portfolio = {}
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            portfolio = json.load(f)

    total_trades = len(trades)
    buys = [t for t in trades if t.get("action") == "BUY"]
    sells = [t for t in trades if t.get("action") == "SELL"]

    total_fees = sum(float(t.get("fee", 0)) for t in trades)
    total_volume = sum(float(t.get("total_value", 0)) for t in trades)

    # Analizar PnL de ventas cerradas
    realized_pnls = []
    for s in sells:
        pnl_str = s.get("pnl", "-")
        if pnl_str and pnl_str != "-":
            try:
                realized_pnls.append(float(pnl_str))
            except ValueError:
                pass

    winning_trades = [p for p in realized_pnls if p > 0]
    losing_trades = [p for p in realized_pnls if p < 0]
    breakeven_trades = [p for p in realized_pnls if p == 0]

    total_realized_pnl = sum(realized_pnls)
    gross_profits = sum(winning_trades)
    gross_losses = abs(sum(losing_trades))

    win_rate = (len(winning_trades) / len(realized_pnls) * 100) if realized_pnls else 0.0
    profit_factor = (gross_profits / gross_losses) if gross_losses > 0 else (999.0 if gross_profits > 0 else 0.0)

    best_trade = max(realized_pnls) if realized_pnls else 0.0
    worst_trade = min(realized_pnls) if realized_pnls else 0.0

    initial_capital = portfolio.get("initial_capital", 10000.0)
    cash_balance = portfolio.get("cash_balance", initial_capital)
    positions = portfolio.get("positions", {})

    print(f"💰 Capital Inicial:           ${initial_capital:,.2f} USD")
    print(f"💵 Saldo Efectivo Disponible:  ${cash_balance:,.2f} USD")
    print(f"🔄 Total de Órdenes:           {total_trades} (Compras: {len(buys)}, Ventas: {len(sells)})")
    print(f"📊 Volumen Total Operado:      ${total_volume:,.2f} USD")
    print(f"💸 Comisiones Pagadas:         ${total_fees:,.2f} USD")
    print("-" * 65)
    print("🎯 MÉTRICAS DE VENTAS Y PnL CERRADO:")
    print(f"   • Operaciones Cerradas:     {len(realized_pnls)}")
    print(f"   • Operaciones Ganadoras:    {len(winning_trades)}")
    print(f"   • Operaciones Perdedoras:   {len(losing_trades)}")
    print(f"   • Tasa de Acierto (Win Rate): {win_rate:.1f}%")
    print(f"   • PnL Realizado Neto:       ${total_realized_pnl:+,.2f} USD")
    print(f"   • Profit Factor:            {profit_factor:.2f}")
    print(f"   • Mejor Operación:          ${best_trade:+,.2f} USD")
    print(f"   • Peor Operación:           ${worst_trade:+,.2f} USD")
    print("-" * 65)

    if positions:
        print("📌 POSICIONES ACTIVAS EN CARTERA:")
        for sym, pos in positions.items():
            qty = float(pos.get("quantity", 0))
            avg_p = float(pos.get("avg_price", 0))
            print(f"   • {sym}: {qty:.6f} unidades @ Promedio ${avg_p:,.2f} (Total: ${qty*avg_p:,.2f})")
    else:
        print("📌 POSICIONES ACTIVAS: Ninguna (100% en liquidez)")

    print("=" * 65)


if __name__ == "__main__":
    analyze()
