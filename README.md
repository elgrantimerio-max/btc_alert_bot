# ⚡ BTC Quant Terminal V6.5 — Pro Institutional Edition

> **Terminal Cuantitativa Autónoma de Bitcoin (BTC/USDT) con Motor Unificado de Grado Institucional, Flujo de Órdenes Nativo de Binance (True Taker CVD), Modelo de 3 Factores Ortogonales, Objetivos Dinámicos por Volatilidad (ATR), Dimensionamiento por Riesgo Fijo (Fixed Fractional), Daemon de WebSocket de Ultra Baja Latencia (<50ms), Vigilancia Cloud y Alertas en Tiempo Real por Telegram.**

[![BTC Quant Guardian 24/7](https://github.com/elgrantimerio-max/btctradingbot/actions/workflows/quant_guardian_24_7.yml/badge.svg)](https://github.com/elgrantimerio-max/btctradingbot/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-emerald.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](Dockerfile)

---

## 🎯 Objetivo y Filosofía Cuantitativa

Capturar expansiones de momentum intradía en Bitcoin (BTC/USDT) en **Largo (LONG)** o **Corto (SHORT)** con **esperanza matemática positiva auditada**, gestionando el riesgo de forma asimétrica:
* **Stop-Loss Dinámico:** Anclado a la volatilidad real del mercado ($1.5 \times \text{ATR}_{14}$).
* **Toma de Beneficios Dual:** Aseguramiento del 75% en TP1 ($2.0 \times \text{ATR}_{14}$), elevando el Stop a Break-Even ($+0.30 \times \text{ATR}_{14}$), y dejando correr el 25% restante a TP2 ($3.5 \times \text{ATR}_{14}$) con Trailing Stop automático.
* **Salida por Tiempo Estricta (Time Decay):** 5 velas (20 horas en 4H) para evitar quedar atrapado en contracciones de volatilidad.
* **Dimensionamiento de Capital (Fixed Fractional):** Arriesga exactamente el **2.0% del capital de la cuenta** por operación (o 3.0% en setups de alta convicción Tier A+), protegiendo el balance frente a rachas adversas.

---

## 🧠 Arquitectura Cuantitativa V6.5 (Mejoras Institucionales)

### 1. Flujo de Órdenes Real con Datos Nativos de Binance (True Taker CVD)
* **Antes:** El delta se estimaba mediante una aproximación sintética del cuerpo de la vela.
* **Ahora:** Se extrae directamente la **columna índice 9 de Binance (`taker_buy_base_asset_volume`)**:
  $$\text{Delta Real} = \text{Taker Buy} - (\text{Volumen Total} - \text{Taker Buy}) = 2 \times \text{Taker Buy} - \text{Volumen Total}$$
  $$\text{Taker Ratio} = \frac{\text{Delta Real}}{\text{Volumen Total}} \in [-1.0, +1.0]$$

### 2. Normalización Total por Volatilidad (ATR Dinámico)
* **Antes:** Puntos nominales fijos de USD ($700 pts SL, $1.500 pts TP).
* **Ahora:** Objetivos auto-calibrados por la volatilidad actual:
  $$\text{SL} = 1.5 \times \text{ATR}_{14}, \quad \text{TP1} = 2.0 \times \text{ATR}_{14}, \quad \text{TP2} = 3.5 \times \text{ATR}_{14}$$
  *(En temporalidad 4H con horizonte de 20h, se ajustan automáticamente a 0.55x / 0.75x / 1.25x ATR para garantizar compatibilidad temporal).*

### 3. Descorrelación de Factores (Modelo Ortogonal de 3 Dimensiones)
Elimina la multicolinealidad de sumar indicadores solapados mediante reducción a 3 factores independientes:
* **Factor 1 - Inercia / Tendencia ($Z_{\text{trend}}$):** $Z\text{-score}$ de distancia del precio al VWAP rodante normalizado por ATR + pendientes relativas de EMA 20/50 y macro EMA 200.
* **Factor 2 - Régimen de Volatilidad ($R_{\text{regime}}$):** Choppiness Index invertido + ADX(14) + compresión TTM Squeeze. Detecta si el mercado está en expansión limpia o rango sucio.
* **Factor 3 - Presión de Flujo ($P_{\text{flow}}$):** Ratio CVD Taker real de Binance amplificado por RVOL + variación del Open Interest de Futuros ($\Delta\text{OI}$).

**Probabilidad Calibrada mediante Regresión Logística Sigmoide:**
$$P(\text{Éxito}) = \frac{1}{1 + e^{-z}}$$
Solo se dispara señal si $P(\text{Éxito}) \ge 60\%$ (o $\ge 75\%$ para Tier A+).

### 4. Dimensionamiento por Riesgo Fijo (Fixed Fractional Sizing)
$$\text{Posición (BTC)} = \frac{\text{Capital en Cuenta} \times 0.02}{\text{Distancia al Stop-Loss (USD)}}$$
Garantiza que una racha de pérdidas consecutivas solo reduzca una fracción predecible del capital, sin riesgo de liquidación.

### 5. Resultados Auditados sobre 500 Días (Zero Lookahead Bias)
* **Dataset Auditado:** 500 días de Binance (2.998 velas de 4H) con resolución microestructural intrabarra.
* **Operaciones Totales:** **90 trades** (filtro de alta convicción sin overtrading)
* **Win Rate Real:** **56.7%** (51 ganadas / 39 perdidas)
* **Profit Factor:** **1.83**
* **Puntos Netos Capturados:** **+18,985 pts**
* **Crecimiento de Capital ($5,000 inicial):** **$10,040.09 USDT (+100.8% ROI)**
* **Drawdown Máximo:** **-9.9% (-$675.19 USDT)**
* **Esperanza Matemática:** **+$56.00 USDT por operación**
* **Permanencia Promedio:** **9.3 horas**

---

## 🏗️ Estructura del Código (Single Source of Truth - DRY)

```text
├── engine/
│   ├── __init__.py              # Exportaciones del motor cuantitativo
│   ├── quant_core.py            # ÚNICA FUENTE DE VERDAD (CVD nativo, 3 factores, SL/TP ATR, sizing)
│   └── backtest_engine.py       # Motor de backtesting institucional sin sesgo intrabarra
├── quant_bot_24_7.py            # Motor para GitHub Actions (Single Cycle / Polling)
├── daemon_ws_bot.py             # Daemon en tiempo real WebSocket Binance (<50ms latencia)
├── run_backtest.py              # CLI para auditoría histórica de 500 días
├── Dockerfile                   # Contenedor Docker optimizado (Python 3.11-slim)
├── docker-compose.yml           # Despliegue en 1 comando para VPS (Hetzner, AWS, etc.)
├── backtest_500d_summary.json   # Resumen de backtest auditado
├── backtest_500d_data.js        # Dataset sincronizado para la interfaz web
├── index.html                   # Terminal Web con TradingView canvas y journal
├── state.json                   # Estado persistente de la posición activa
├── journal.json                 # Diario histórico de operaciones
└── requirements.txt             # Dependencias Python
```

---

## 🚀 Opciones de Despliegue y Ejecución

### Opción 1: Despliegue VPS con Docker (Recomendado — <50ms Latencia)
Para eliminar los retrasos de cola de GitHub Actions y monitorear el mercado tick a tick por WebSocket:

```bash
# 1. Configurar tus claves en .env
cp .env.example .env
# Editar TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en .env

# 2. Levantar el daemon en segundo plano
docker compose up -d

# 3. Ver logs en tiempo real
docker compose logs -f
```

### Opción 2: En la Nube 24/7 sin Servidor (GitHub Actions)
1. Sube el repositorio a GitHub.
2. En tu repositorio, entra en **Settings > Secrets and variables > Actions** y añade:
   * `TELEGRAM_BOT_TOKEN`: Token de [@BotFather](https://t.me/BotFather).
   * `TELEGRAM_CHAT_ID`: Tu Chat ID numérico.
3. El workflow `.github/workflows/quant_guardian_24_7.yml` ejecutará [`quant_bot_24_7.py`](quant_bot_24_7.py) de forma periódica.

### Opción 3: Auditoría y Backtest Local en 1 Clic
```bash
python run_backtest.py
```
Ejecuta la simulación sobre las 3,000 velas de 4H (500 días), resuelve la trayectoria intrabarra (eliminando el sesgo de TP antes de SL) y actualiza automáticamente los datos de la interfaz web [`index.html`](index.html).

---

## 🌐 Activación de la Web Online (GitHub Pages)

1. En tu repositorio GitHub, ve a **Settings > Pages**.
2. En **Build and deployment > Source**, selecciona rama `main` y carpeta `/ (root)`.
3. Tu terminal estará disponible de inmediato con los gráficos y el backtest sincronizado.

---

*Arquitectura cuantitativa unificada de grado profesional.*
