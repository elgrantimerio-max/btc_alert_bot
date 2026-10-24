import sys
import os

# Asegurar codificación UTF-8
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from reader import parse_json_signal, parse_html_signal

# Test 1: JSON
res_json = parse_json_signal({"signal": "BUY", "symbol": "ETHUSDT", "price": 2750.50, "amount": 600})
print("Test 1 (JSON):", res_json["signal"], res_json["symbol"], res_json["price"])

# Test 2: HTML with id="signal"
res_html_id = parse_html_signal("""
<html>
  <body>
    <h1>Panel de Trading</h1>
    <div class="card">
      <span id="signal" class="badge">COMPRA</span>
    </div>
  </body>
</html>
""")
print("Test 2 (HTML ID):", res_html_id["signal"], res_html_id["format"])

# Test 3: HTML with text keywords
res_html_text = parse_html_signal("""
<html>
  <body>
    <h2>Estrategia RSI</h2>
    <p>El mercado de SOLUSDT ha emitido una SEÑAL DE VENTA.</p>
  </body>
</html>
""")
print("Test 3 (HTML Text):", res_html_text["signal"], res_html_text["symbol"])

# Test 4: HTML neutral / wait
res_html_neutral = parse_html_signal("""
<html>
  <body>
    <p>Estado del algoritmo: EN ESPERA de nueva señal</p>
  </body>
</html>
""")
print("Test 4 (HTML Neutral):", res_html_neutral["signal"])
