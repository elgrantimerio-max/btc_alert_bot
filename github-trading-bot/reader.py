#!/usr/bin/env python3
"""
Lector y Extractor Inteligente de Señales Web.
Capaz de leer e interpretar páginas web en GitHub (GitHub Pages o repositorios),
detectando señales tanto en formato JSON como en HTML (etiquetas, IDs, badges o texto).
"""

import re
import json
import urllib.request
import os
import sys

# Asegurar codificación UTF-8
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def fetch_url_content(url_or_path: str) -> tuple[str, str]:
    """
    Descarga el contenido de una URL o lee un archivo local si es ruta de archivo.
    Retorna (contenido_texto, content_type_aprox).
    """
    if os.path.exists(url_or_path):
        with open(url_or_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(), "local"

    req = urllib.request.Request(
        url_or_path,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml,application/json;q=0.9,*/*;q=0.8"
        }
    )
    with urllib.request.urlopen(req, timeout=12) as response:
        content_type = response.headers.get("Content-Type", "").lower()
        charset = response.headers.get_content_charset() or "utf-8"
        raw_data = response.read()
        return raw_data.decode(charset, errors="ignore"), content_type


def parse_json_signal(data: dict, default_symbol: str = "BTCUSDT", default_amount: float = 500.0) -> dict:
    """Extrae la señal si la web devuelve un JSON."""
    raw_signal = (
        data.get("signal") or data.get("action") or data.get("type") or
        data.get("orden") or data.get("senal") or ""
    ).strip().upper()

    symbol = (
        data.get("symbol") or data.get("ticker") or data.get("pair") or
        data.get("activo") or default_symbol
    ).strip().upper()

    try:
        price = float(data.get("price") or data.get("precio") or 0)
    except (ValueError, TypeError):
        price = 0.0

    try:
        amount_usd = float(data.get("amount_usd") or data.get("amount") or data.get("monto") or default_amount)
    except (ValueError, TypeError):
        amount_usd = default_amount

    action = "HOLD"
    if any(k in raw_signal for k in ["BUY", "COMPRA", "LONG"]):
        action = "BUY"
    elif any(k in raw_signal for k in ["SELL", "VENTA", "SHORT"]):
        action = "SELL"
    elif any(k in raw_signal for k in ["HOLD", "NEUTRAL", "ESPERA", "WAIT"]):
        action = "HOLD"

    return {
        "success": True,
        "format": "JSON",
        "signal": action,
        "symbol": symbol,
        "price": price,
        "amount_usd": amount_usd,
        "raw_match": str(data)
    }


def parse_html_signal(html: str, custom_selector: str = "signal", default_symbol: str = "BTCUSDT", default_amount: float = 500.0) -> dict:
    """Extrae la señal analizando etiquetas HTML y palabras clave."""
    upper_html = html.upper()

    # 1. Búsqueda por id o class específica (ej: id="signal", class="signal", data-signal="BUY")
    specific_patterns = [
        rf'id=["\']?{re.escape(custom_selector)}["\']?[^>]*>([^<]+)<',
        rf'class=["\']?[^"\']*{re.escape(custom_selector)}[^"\']?["\']?[^>]*>([^<]+)<',
        r'data-signal=["\']([^"\']+)["\']'
    ]

    for pattern in specific_patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            extracted_text = match.group(1).strip().upper()
            if any(k in extracted_text for k in ["BUY", "COMPRA", "LONG"]):
                return {
                    "success": True,
                    "format": "HTML_SELECTOR",
                    "signal": "BUY",
                    "symbol": default_symbol,
                    "price": 0.0,
                    "amount_usd": default_amount,
                    "raw_match": extracted_text
                }
            elif any(k in extracted_text for k in ["SELL", "VENTA", "SHORT"]):
                return {
                    "success": True,
                    "format": "HTML_SELECTOR",
                    "signal": "SELL",
                    "symbol": default_symbol,
                    "price": 0.0,
                    "amount_usd": default_amount,
                    "raw_match": extracted_text
                }

    # 2. Búsqueda de patrones de texto en el contenido visible (eliminando tags <script> y <style>)
    clean_text = re.sub(r'<script.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    clean_text = re.sub(r'<style.*?</style>', '', clean_text, flags=re.DOTALL | re.IGNORECASE)
    clean_text = re.sub(r'<[^>]+>', ' ', clean_text)
    clean_upper = clean_text.upper()

    # Detectar activos conocidos en el texto (ej: BTCUSDT, ETHUSDT, SOLUSDT)
    ticker_match = re.search(r'\b(BTCUSDT|ETHUSDT|SOLUSDT|BNBUSDT|XRPUSDT|ADAUSDT)\b', clean_upper)
    detected_symbol = ticker_match.group(1) if ticker_match else default_symbol

    # Evaluar señales de Compra
    buy_matches = ["SEÑAL DE COMPRA", "SEÑAL: COMPRA", "SIGNAL: BUY", "BUY SIGNAL", "ALERTA COMPRA", "COMPRAR AHORA"]
    for bm in buy_matches:
        if bm in clean_upper:
            return {
                "success": True,
                "format": "HTML_TEXT_KEYWORD",
                "signal": "BUY",
                "symbol": detected_symbol,
                "price": 0.0,
                "amount_usd": default_amount,
                "raw_match": bm
            }

    # Evaluar señales de Venta
    sell_matches = ["SEÑAL DE VENTA", "SEÑAL: VENTA", "SIGNAL: SELL", "SELL SIGNAL", "ALERTA VENTA", "VENDER AHORA"]
    for sm in sell_matches:
        if sm in clean_upper:
            return {
                "success": True,
                "format": "HTML_TEXT_KEYWORD",
                "signal": "SELL",
                "symbol": detected_symbol,
                "price": 0.0,
                "amount_usd": default_amount,
                "raw_match": sm
            }

    # Evaluar si indica explícitamente NEUTRAL o ESPERA
    neutral_matches = ["SIN SEÑAL", "NEUTRAL", "HOLD", "EN ESPERA", "ESPERANDO SEÑAL", "WAITING"]
    for nm in neutral_matches:
        if nm in clean_upper:
            return {
                "success": True,
                "format": "HTML_TEXT_KEYWORD",
                "signal": "HOLD",
                "symbol": detected_symbol,
                "price": 0.0,
                "amount_usd": default_amount,
                "raw_match": nm
            }

    # Si no detectó palabras compuestas, buscar palabras sueltas claras
    if re.search(r'\b(COMPRA|BUY)\b', clean_upper) and not re.search(r'\b(VENTA|SELL)\b', clean_upper):
        return {
            "success": True,
            "format": "HTML_KEYWORD_FALLBACK",
            "signal": "BUY",
            "symbol": detected_symbol,
            "price": 0.0,
            "amount_usd": default_amount,
            "raw_match": "BUY/COMPRA token"
        }
    elif re.search(r'\b(VENTA|SELL)\b', clean_upper) and not re.search(r'\b(COMPRA|BUY)\b', clean_upper):
        return {
            "success": True,
            "format": "HTML_KEYWORD_FALLBACK",
            "signal": "SELL",
            "symbol": detected_symbol,
            "price": 0.0,
            "amount_usd": default_amount,
            "raw_match": "SELL/VENTA token"
        }

    return {
        "success": True,
        "format": "HTML_NO_ACTION",
        "signal": "HOLD",
        "symbol": detected_symbol,
        "price": 0.0,
        "amount_usd": default_amount,
        "raw_match": "No se detectaron palabras clave de acción"
    }


def read_signal_from_web(url: str, custom_selector: str = "signal", default_symbol: str = "BTCUSDT", default_amount: float = 500.0) -> dict:
    """Función principal: descarga e interpreta la web automáticamente (JSON o HTML)."""
    try:
        content, content_type = fetch_url_content(url)
    except Exception as e:
        return {
            "success": False,
            "error": f"Error al acceder a la URL '{url}': {str(e)}",
            "signal": "NONE"
        }

    # Intentar interpretar como JSON primero
    stripped = content.strip()
    if (stripped.startswith("{") and stripped.endswith("}")) or "json" in content_type:
        try:
            json_data = json.loads(stripped)
            return parse_json_signal(json_data, default_symbol, default_amount)
        except json.JSONDecodeError:
            pass

    # Interpretar como HTML
    return parse_html_signal(content, custom_selector, default_symbol, default_amount)


if __name__ == "__main__":
    test_target = sys.argv[1] if len(sys.argv) > 1 else "https://httpbin.org/json"
    print(f"Probando lectura sobre: {test_target}")
    result = read_signal_from_web(test_target)
    print(json.dumps(result, indent=2, ensure_ascii=False))
