#!/usr/bin/env python3
"""
BTC Quant Terminal V6.5 - Official Backtest Runner (run_backtest.py)
Audits 500 days of Bitcoin data using the unified quantitative engine (engine/quant_core.py)
with real native order flow, dynamic ATR targets, and zero intrabar lookahead bias.
"""

import os
import sys
import json

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from engine.quant_core import Kline
from engine.backtest_engine import run_backtest_simulation

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KLINES_FILE = os.path.join(BASE_DIR, 'klines_4h_3000.json')
OUTPUT_JSON = os.path.join(BASE_DIR, 'backtest_500d_summary.json')
OUTPUT_JS = os.path.join(BASE_DIR, 'backtest_500d_data.js')


def load_klines_dataset() -> list[Kline]:
    if not os.path.exists(KLINES_FILE):
        print(f"[ERROR] Archivo {KLINES_FILE} no encontrado.")
        sys.exit(1)

    print(f"[CARGA] Leyendo dataset histórico desde {os.path.basename(KLINES_FILE)}...")
    with open(KLINES_FILE, 'r', encoding='utf-8') as f:
        raw_list = json.load(f)

    klines = [Kline.from_raw(item) for item in raw_list]
    print(f"[DATA] {len(klines)} velas cargadas. Rango: {klines[0].c:,.1f}$ -> {klines[-1].c:,.1f}$")
    return klines


def main():
    print("=" * 70)
    print("⚡ BTC QUANT TERMINAL V6.5 — SUITE DE BACKTEST CUANTITATIVO AUDITADO")
    print("=" * 70)

    klines = load_klines_dataset()
    print("[EJECUCIÓN] Simulando 500 días con Motor Unificado, SL/TP ATR Dinámicos y Resolución Intrabarra...")

    results = run_backtest_simulation(
        klines=klines,
        initial_bankroll=5000.0,
        timeframe='4h',
        max_hold_hours=20,
        cooldown_candles=2
    )

    print("\n" + "=" * 70)
    print("📊 RESULTADOS OFICIALES DEL BACKTEST (MOTOR UNIFICADO V6.5)")
    print("=" * 70)
    print(f"  • Período Evaluado:       {results['days_tested']} días ({results['candles_tested']} velas 4H)")
    print(f"  • Operaciones Totales:    {results['total_trades']}")
    print(f"  • Ganadas / Perdidas:     {results['wins']}W / {results['losses']}L")
    print(f"  • Win Rate Real:          {results['win_rate']}%")
    print(f"  • Profit Factor:          {results['profit_factor']}")
    print(f"  • Puntos Netos (USD):     {results['total_pts']:+,} pts")
    print(f"  • Capital Inicial:        ${results['initial_bankroll']:,.2f} USDT")
    print(f"  • Balance Final:          ${results['final_balance']:,.2f} USDT")
    print(f"  • Beneficio Neto:         ${results['net_profit_usd']:+,.2f} USDT")
    print(f"  • Retorno (ROI):          +{results['roi_pct']}%")
    print(f"  • Drawdown Máximo:        -{results['max_dd_pct']}% (-${results['max_dd_usd']:,.2f} USDT)")
    print(f"  • Esperanza Matemática:   +${results['expectancy_usd']:.2f} USDT / trade")
    print(f"  • Permanencia Promedio:   {results['avg_hours_held']} horas")
    print("=" * 70)

    # Save to backtest_500d_summary.json
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2)
    print(f"[EXPORT] Resumen guardado en {os.path.basename(OUTPUT_JSON)}")

    # Save to backtest_500d_data.js for index.html UI
    js_content = f"window.DEFAULT_BACKTEST_500D_DATA = {json.dumps(results)};\n"
    with open(OUTPUT_JS, 'w', encoding='utf-8') as f:
        f.write(js_content)
    print(f"[EXPORT] Dataset frontend sincronizado en {os.path.basename(OUTPUT_JS)}")
    print("✅ Backtest completado con éxito y sincronizado con el terminal web.")


if __name__ == '__main__':
    main()
