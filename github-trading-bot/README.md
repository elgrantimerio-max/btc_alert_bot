# 🤖 GitHub Autonomous Trading Bot (Auto-Scraper & Paper Trading)

Bot de trading **100% autónomo y 24/7 en la nube de GitHub Actions**. No necesitas tener tu ordenador encendido, ni abrir el navegador, ni mantener pestañas abiertas.

El bot **lee periódicamente (cada 5 minutos) la web que tienes subida a GitHub**, analiza si ha cambiado el estado a **COMPRA** o **VENTA** (compatible tanto con etiquetas HTML/texto como con archivos JSON), ejecuta la operación simulada con comisiones realistas y precios en tiempo real, y **guarda automáticamente el registro en `data/trades.csv` y un resumen visual en `data/SUMMARY.md`** mediante auto-commit.

---

## 🏗️ Cómo funciona la lectura autónoma

```
  ┌───────────────────────────────┐
  │  Tu Web subida a GitHub       │  (GitHub Pages o repositorio público/privado)
  │  • Muestra COMPRA / VENTA     │  (en un texto, <span id="signal"> o JSON)
  └───────────────┬───────────────┘
                  │ 1. GitHub Actions se despierta solo cada 5 minutos (Cron)
                  ▼
  ┌───────────────────────────────┐
  │  monitor.py (Lector Web)      │  (Descarga la web e interpreta la señal)
  └───────────────┬───────────────┘
                  │ 2. Compara con data/last_signal.json
                  ▼
  ┌───────────────────────────────┐
  │  Filtro Antiduplicados        │  (Si la señal sigue siendo la misma, espera)
  └───────────────┬───────────────┘
                  │ 3. Si hay cambio (ej: salta BUY):
                  ▼
  ┌───────────────────────────────┐
  │  bot.py (Ejecución Paper)     │  (Consulta precio en vivo, calcula saldo y comisión)
  └───────────────┬───────────────┘
                  │ 4. Git auto-commit & push a GitHub
                  ▼
  ┌───────────────────────────────┐
  │  Historial Persistente        │
  │  • data/trades.csv            │  -> Excel, Google Sheets, Pandas
  │  • data/portfolio.json        │  -> Saldo y posiciones activas
  │  • data/SUMMARY.md            │  -> Panel visual en el repositorio
  └───────────────────────────────┘
```

---

## 📁 Archivos Principales

```text
├── .github/workflows/
│   ├── scheduled_monitor.yml    # Cron cada 5 minutos (100% autónomo en la nube)
│   └── trade_trigger.yml        # Ejecución manual bajo demanda
├── config.json                  # URL de tu web a vigilar y configuración del bot
├── monitor.py                   # Coordinador del ciclo autónomo y filtro antiduplicados
├── reader.py                    # Extractor inteligente (interpreta JSON y HTML)
├── bot.py                       # Motor de trading (Paper trading, precios en vivo, PnL)
├── data/
│   ├── trades.csv               # Historial de todas las órdenes para análisis posterior
│   ├── portfolio.json           # Saldo disponible y posiciones en cartera
│   ├── last_signal.json         # Memoria de la última señal procesada (evita duplicados)
│   └── SUMMARY.md               # Dashboard generado automáticamente en Markdown
├── scripts/
│   ├── analyze_trades.py        # Reporte estadístico (Win Rate, Profit Factor, PnL neto)
│   ├── reset_portfolio.py       # Reinicia el saldo a $10,000 USD
│   └── test_reader.py           # Suite de pruebas para verificar formatos de lectura
└── web_demo/
    ├── mock_web.html            # Web de prueba local para validar la lectura
    └── index.html               # Panel interactivo para pruebas manuales
```

---

## ⚙️ Configuración (Sólo 1 paso en `config.json`)

Abre el archivo [config.json](file:///C:/Users/eloyg/.gemini/antigravity/scratch/github-trading-bot/config.json) y coloca la URL de tu página web en GitHub:

```json
{
  "target_url": "https://TU_USUARIO.github.io/TU_WEB/",
  "default_symbol": "BTCUSDT",
  "default_amount_usd": 500.0,
  "simulated_fee_rate": 0.001,
  "anti_duplicate": true,
  "html_custom_selector": "signal"
}
```

> **Nota:** Puedes usar la URL de tu GitHub Pages (`https://usuario.github.io/repo/`) o la URL `raw` de cualquier archivo de tu repo (`https://raw.githubusercontent.com/.../signal.json`).

---

## 🔍 ¿Qué formatos detecta el lector en tu web?

El motor [reader.py](file:///C:/Users/eloyg/.gemini/antigravity/scratch/github-trading-bot/reader.py) es completamente flexible:

### Opción A: Elemento HTML con ID o Clase (Recomendado para webs visuales)
Tu web puede tener cualquier etiqueta con `id="signal"` o `class="signal"`:
```html
<span id="signal">COMPRA</span>
<!-- o también: <div class="signal">VENTA</div> -->
<!-- o también: <span id="signal">BUY</span> -->
```

### Opción B: Texto libre en el HTML
Si tu web imprime frases como:
* `"SEÑAL DE COMPRA"` o `"BUY SIGNAL"` -> Ejecuta COMPRA.
* `"SEÑAL DE VENTA"` o `"SELL SIGNAL"` -> Ejecuta VENTA.
* `"NEUTRAL"` o `"EN ESPERA"` -> No hace nada (espera en liquidez).

### Opción C: Formato JSON
Si tu web o repositorio genera un JSON:
```json
{
  "signal": "BUY",
  "symbol": "BTCUSDT",
  "price": 0,
  "amount_usd": 500
}
```

---

## 🛡️ Filtro Antiduplicados Inteligente

Cuando tu web marque `COMPRA`, el bot ejecutará la orden de inmediato.
En las siguientes comprobaciones (a los 5, 10, 15 minutos...), si tu web sigue mostrando `COMPRA`, el bot **NO volverá a comprar** para no saturar tu capital. Guardará el estado en [data/last_signal.json](file:///C:/Users/eloyg/.gemini/antigravity/scratch/github-trading-bot/data/last_signal.json) y esperará pacientemente hasta que tu web cambie a `VENTA` o cambie de activo.

---

## 🚀 Subir a GitHub en 3 pasos

### 1. Subir la carpeta a tu repositorio
Crea un repositorio en GitHub y sube estos archivos a la rama principal (`main`).

### 2. Dar permiso de escritura a GitHub Actions (¡Imprescindible!)
Para que el bot pueda auto-guardar las operaciones en `data/trades.csv` cada 5 minutos:
1. En tu repo de GitHub, ve a **Settings** > **Actions** > **General**.
2. Baja hasta **Workflow permissions**.
3. Marca **Read and write permissions** y pulsa **Save**.

### 3. ¡Listo!
El flujo `.github/workflows/scheduled_monitor.yml` se activará solo cada 5 minutos. También puedes forzar una comprobación inmediata cuando quieras entrando en la pestaña **Actions** > **Autonomous 24/7 Web Monitor** > **Run workflow**.

---

## 📊 Análisis y Resultados

* **En GitHub:** Entra en `data/trades.csv` para ver todas las filas, o en `data/SUMMARY.md` para ver el informe con tablas de rendimiento.
* **Descarga para Excel:** Puedes descargar `trades.csv` en cualquier momento para analizarlo en Microsoft Excel o Google Sheets.
* **Métricas estadísticas en terminal:**
  ```powershell
  python scripts/analyze_trades.py
  ```
  Calcula automáticamente:
  - Tasa de acierto (**Win Rate %**)
  - Ganancia neta cerrada (**PnL**)
  - Comisiones totales pagadas
  - **Profit Factor**
  - Posiciones abiertas actuales
