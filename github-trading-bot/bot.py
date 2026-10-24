#!/usr/bin/env python3
"""
Trading Bot Autónomo (Modo Simulación / Paper Trading)
Diseñado para ejecutarse automáticamente en GitHub Actions cuando se recibe
una señal de compra o venta (repository_dispatch / workflow_dispatch).
"""

import os
import sys
import csv
import json
import uuid
import urllib.request
from datetime import datetime, timezone

# Asegurar codificación UTF-8 en salida de terminal
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


# Rutas de datos
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PORTFOLIO_FILE = os.path.join(DATA_DIR, "portfolio.json")
TRADES_FILE = os.path.join(DATA_DIR, "trades.csv")
SUMMARY_FILE = os.path.join(DATA_DIR, "SUMMARY.md")

SIMULATED_FEE_RATE = 0.001  # 0.1% comisión simulada (estándar exchanges)


def get_current_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def fetch_live_price_fallback(symbol: str) -> float:
    """
    Intenta obtener el precio de mercado actual si el payload no incluye uno válido.
    Funciona para cripto vía Binance REST API pública sin necesidad de API Key.
    """
    clean_symbol = symbol.upper().replace("-", "").replace("/", "")
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={clean_symbol}"
        req = urllib.request.Request(url, headers={"User-Agent": "GitHubTradingBot/1.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                return float(data["price"])
    except Exception as e:
        print(f"[Aviso] No se pudo obtener precio en vivo para {clean_symbol}: {e}")
    return 0.0


def load_portfolio() -> dict:
    if not os.path.exists(PORTFOLIO_FILE):
        return {
            "currency": "USD",
            "initial_capital": 10000.0,
            "cash_balance": 10000.0,
            "positions": {},
            "total_trades": 0,
            "last_updated": None
        }
    with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_portfolio(portfolio: dict):
    portfolio["last_updated"] = get_current_utc_str()
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, indent=2, ensure_ascii=False)


def append_trade_to_csv(trade: dict):
    file_exists = os.path.exists(TRADES_FILE)
    fieldnames = [
        "timestamp", "trade_id", "action", "symbol", "price",
        "quantity", "total_value", "fee", "balance_after",
        "pnl", "signal_source", "status", "notes"
    ]
    with open(TRADES_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(trade)


def update_summary_markdown(portfolio: dict):
    """Genera un archivo resumen data/SUMMARY.md visible en GitHub con el estado de la cuenta."""
    trades = []
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            trades = list(reader)

    open_positions = portfolio.get("positions", {})
    last_10_trades = trades[-10:] if len(trades) > 10 else trades
    last_10_trades.reverse()

    md_lines = [
        "# 📊 Resumen de Operaciones y Portafolio",
        "",
        f"> **Última actualización:** `{portfolio.get('last_updated', 'N/A')}`",
        "",
        "## 💼 Estado de la Cuenta",
        f"- **Capital Inicial:** `${portfolio.get('initial_capital', 10000):,.2f} {portfolio.get('currency', 'USD')}`",
        f"- **Saldo en Efectivo Disponible:** `${portfolio.get('cash_balance', 0):,.2f} {portfolio.get('currency', 'USD')}`",
        f"- **Total de Operaciones Registradas:** `{portfolio.get('total_trades', 0)}`",
        f"- **Posiciones Abiertas:** `{len(open_positions)}`",
        "",
        "### 📌 Posiciones Abiertas",
        ""
    ]

    if open_positions:
        md_lines.append("| Activo | Cantidad | Precio Promedio Entrada | Inversión Total |")
        md_lines.append("|:------|:---------|:------------------------|:----------------|")
        for sym, pos in open_positions.items():
            qty = float(pos.get("quantity", 0))
            avg_p = float(pos.get("avg_price", 0))
            cost = qty * avg_p
            md_lines.append(f"| **{sym}** | `{qty:.6f}` | `${avg_p:,.2f}` | `${cost:,.2f}` |")
    else:
        md_lines.append("_No hay posiciones abiertas actualmente._")

    md_lines.extend([
        "",
        "### 🕒 Últimas Operaciones Ejecutadas",
        ""
    ])

    if last_10_trades:
        md_lines.append("| Fecha UTC | ID | Acción | Activo | Precio | Cantidad | Monto | PnL | Origen Señal |")
        md_lines.append("|:---|:---|:---|:---|:---|:---|:---|:---|:---|")
        for t in last_10_trades:
            action_badge = "🟢 COMPRA" if t.get("action") == "BUY" else "🔴 VENTA"
            pnl_val = t.get("pnl", "-")
            pnl_badge = f"`{pnl_val}`" if pnl_val != "-" else "-"
            md_lines.append(
                f"| {t.get('timestamp')} | `{t.get('trade_id')}` | {action_badge} | **{t.get('symbol')}** | "
                f"${float(t.get('price', 0)):,.2f} | `{float(t.get('quantity', 0)):.6f}` | "
                f"${float(t.get('total_value', 0)):,.2f} | {pnl_badge} | {t.get('signal_source', '-')} |"
            )
    else:
        md_lines.append("_Aún no se ha registrado ninguna operación._")

    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")


def execute_buy(portfolio: dict, symbol: str, price: float, amount_usd: float, source: str, notes: str):
    cash = portfolio["cash_balance"]

    if cash < amount_usd:
        print(f"[RECHAZADO] Saldo insuficiente. Saldo actual: ${cash:.2f}, Solicitado: ${amount_usd:.2f}")
        trade_id = str(uuid.uuid4())[:8]
        failed_trade = {
            "timestamp": get_current_utc_str(),
            "trade_id": trade_id,
            "action": "BUY",
            "symbol": symbol,
            "price": price,
            "quantity": 0,
            "total_value": 0,
            "fee": 0,
            "balance_after": cash,
            "pnl": "-",
            "signal_source": source,
            "status": "REJECTED_INSUFFICIENT_FUNDS",
            "notes": notes
        }
        append_trade_to_csv(failed_trade)
        return False

    fee = amount_usd * SIMULATED_FEE_RATE
    net_investment = amount_usd - fee
    quantity = net_investment / price

    portfolio["cash_balance"] -= amount_usd
    positions = portfolio.setdefault("positions", {})

    if symbol in positions:
        curr = positions[symbol]
        total_qty = curr["quantity"] + quantity
        avg_price = ((curr["quantity"] * curr["avg_price"]) + (quantity * price)) / total_qty
        positions[symbol] = {
            "quantity": total_qty,
            "avg_price": avg_price
        }
    else:
        positions[symbol] = {
            "quantity": quantity,
            "avg_price": price
        }

    portfolio["total_trades"] = portfolio.get("total_trades", 0) + 1
    trade_id = str(uuid.uuid4())[:8]

    trade = {
        "timestamp": get_current_utc_str(),
        "trade_id": trade_id,
        "action": "BUY",
        "symbol": symbol,
        "price": f"{price:.4f}",
        "quantity": f"{quantity:.6f}",
        "total_value": f"{amount_usd:.2f}",
        "fee": f"{fee:.4f}",
        "balance_after": f"{portfolio['cash_balance']:.2f}",
        "pnl": "-",
        "signal_source": source,
        "status": "FILLED",
        "notes": notes
    }

    append_trade_to_csv(trade)
    save_portfolio(portfolio)
    update_summary_markdown(portfolio)

    print(f"\n✅ [COMPRA EJECUTADA]")
    print(f"   ID: {trade_id}")
    print(f"   Activo: {symbol}")
    print(f"   Precio: ${price:,.4f}")
    print(f"   Cantidad: {quantity:.6f}")
    print(f"   Monto invertido: ${amount_usd:.2f} (Comisión: ${fee:.4f})")
    print(f"   Nuevo saldo disponible: ${portfolio['cash_balance']:,.2f}")
    return True


def execute_sell(portfolio: dict, symbol: str, price: float, quantity_to_sell: float, source: str, notes: str):
    positions = portfolio.get("positions", {})
    if symbol not in positions or positions[symbol]["quantity"] <= 0:
        print(f"[RECHAZADO] No posees posiciones abiertas de {symbol} para vender.")
        trade_id = str(uuid.uuid4())[:8]
        failed_trade = {
            "timestamp": get_current_utc_str(),
            "trade_id": trade_id,
            "action": "SELL",
            "symbol": symbol,
            "price": price,
            "quantity": 0,
            "total_value": 0,
            "fee": 0,
            "balance_after": portfolio["cash_balance"],
            "pnl": "-",
            "signal_source": source,
            "status": "REJECTED_NO_POSITION",
            "notes": notes
        }
        append_trade_to_csv(failed_trade)
        return False

    current_qty = positions[symbol]["quantity"]
    avg_entry_price = positions[symbol]["avg_price"]

    # Si no se especifica cantidad o es mayor a la disponible, vender el 100%
    if quantity_to_sell <= 0 or quantity_to_sell > current_qty:
        quantity_to_sell = current_qty

    gross_value = quantity_to_sell * price
    fee = gross_value * SIMULATED_FEE_RATE
    net_proceeds = gross_value - fee

    # Calcular PnL neto
    cost_basis = quantity_to_sell * avg_entry_price
    realized_pnl = net_proceeds - cost_basis

    portfolio["cash_balance"] += net_proceeds

    remaining_qty = current_qty - quantity_to_sell
    if remaining_qty <= 1e-8:
        del positions[symbol]
    else:
        positions[symbol]["quantity"] = remaining_qty

    portfolio["total_trades"] = portfolio.get("total_trades", 0) + 1
    trade_id = str(uuid.uuid4())[:8]

    trade = {
        "timestamp": get_current_utc_str(),
        "trade_id": trade_id,
        "action": "SELL",
        "symbol": symbol,
        "price": f"{price:.4f}",
        "quantity": f"{quantity_to_sell:.6f}",
        "total_value": f"{gross_value:.2f}",
        "fee": f"{fee:.4f}",
        "balance_after": f"{portfolio['cash_balance']:.2f}",
        "pnl": f"{realized_pnl:+.2f}",
        "signal_source": source,
        "status": "FILLED",
        "notes": notes
    }

    append_trade_to_csv(trade)
    save_portfolio(portfolio)
    update_summary_markdown(portfolio)

    print(f"\n✅ [VENTA EJECUTADA]")
    print(f"   ID: {trade_id}")
    print(f"   Activo: {symbol}")
    print(f"   Precio: ${price:,.4f}")
    print(f"   Cantidad vendida: {quantity_to_sell:.6f}")
    print(f"   Valor bruto: ${gross_value:.2f} (Comisión: ${fee:.4f})")
    print(f"   PnL Realizado: ${realized_pnl:+,.2f}")
    print(f"   Nuevo saldo disponible: ${portfolio['cash_balance']:,.2f}")
    return True


def main():
    print("=" * 60)
    print("🤖 GITHUB AUTOMATED TRADING BOT - EXECUTION ENGINE")
    print(f"🕒 Timestamp: {get_current_utc_str()}")
    print("=" * 60)

    # Parámetros recibidos por Variables de Entorno (desde GitHub Actions o local)
    action = os.getenv("ACTION", "BUY").strip().upper()
    symbol = os.getenv("SYMBOL", "BTCUSDT").strip().upper()
    signal_source = os.getenv("SIGNAL_SOURCE", "Web Signal").strip()
    notes = os.getenv("NOTES", "").strip()

    try:
        price = float(os.getenv("PRICE", "0"))
    except ValueError:
        price = 0.0

    try:
        amount_usd = float(os.getenv("AMOUNT_USD", "500"))
    except ValueError:
        amount_usd = 500.0

    try:
        quantity = float(os.getenv("QUANTITY", "0"))
    except ValueError:
        quantity = 0.0

    # Si no se pasó un precio válido (> 0), consultar API de precio en vivo
    if price <= 0:
        print(f"[Info] Precio no especificado en la señal. Consultando precio en vivo para {symbol}...")
        price = fetch_live_price_fallback(symbol)
        if price <= 0:
            print(f"[Error] No se pudo determinar el precio para {symbol}. Operación cancelada.")
            sys.exit(1)
        print(f"[Info] Precio de mercado obtenido: ${price:,.4f}")

    portfolio = load_portfolio()

    if action == "BUY":
        success = execute_buy(portfolio, symbol, price, amount_usd, signal_source, notes)
    elif action == "SELL":
        success = execute_sell(portfolio, symbol, price, quantity, signal_source, notes)
    else:
        print(f"[Error] Acción desconocida '{action}'. Debe ser BUY o SELL.")
        sys.exit(1)

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
