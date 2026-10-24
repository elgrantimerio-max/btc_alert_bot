/**
 * Módulo de integración para emitir señales de compra/venta desde tu web hacia GitHub.
 *
 * ¿Cómo funciona?
 * Cuando tu web detecta una señal (RSI, cruce de medias, botón de usuario, etc.),
 * esta función llama a la API REST de GitHub para disparar el evento `repository_dispatch`.
 * GitHub Actions se enciende en la nube, ejecuta el bot en modo Paper Trading,
 * actualiza el archivo `data/trades.csv` y guarda los cambios automáticamente.
 */

const GITHUB_CONFIG = {
  // Reemplaza con tu usuario y nombre del repositorio donde subas el bot
  owner: "TU_USUARIO_GITHUB",
  repo: "github-trading-bot",
  
  // Token de Acceso Personal (PAT) con permisos de: Actions (Read and Write) o Contents (Read and Write).
  // RECOMENDACIÓN: Usa un 'Fine-grained Personal Access Token' limitado únicamente a este repo.
  token: "TU_GITHUB_PERSONAL_ACCESS_TOKEN"
};

/**
 * Envía una señal de COMPRA al bot en GitHub.
 * 
 * @param {Object} options
 * @param {string} options.symbol - Par o activo (ej: "BTCUSDT", "ETHUSDT")
 * @param {number} [options.amountUsd=500] - Capital en USD a invertir
 * @param {number} [options.price=0] - Precio fijado (0 para que el bot tome precio actual en vivo)
 * @param {string} [options.notes=""] - Motivo de la señal (ej: "RSI < 30 Cruce alcista")
 */
async function sendBuySignal({ symbol = "BTCUSDT", amountUsd = 500, price = 0, notes = "Señal Web" } = {}) {
  const url = `https://api.github.com/repos/${GITHUB_CONFIG.owner}/${GITHUB_CONFIG.repo}/dispatches`;

  const payload = {
    event_type: "buy_signal",
    client_payload: {
      action: "BUY",
      symbol: symbol.toUpperCase(),
      amount_usd: amountUsd,
      price: price,
      source: "Web Frontend Signal",
      notes: notes,
      timestamp: new Date().toISOString()
    }
  };

  try {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Accept": "application/vnd.github+json",
        "Authorization": `Bearer ${GITHUB_CONFIG.token}`,
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });

    if (response.status === 204) {
      console.log(`[EXITO] Senal de COMPRA enviada a GitHub para ${symbol}.`);
      return { success: true, message: `Señal enviada a GitHub para ${symbol}` };
    } else {
      const errorText = await response.text();
      console.error(`[ERROR] Codigo: ${response.status}`, errorText);
      return { success: false, status: response.status, error: errorText };
    }
  } catch (err) {
    console.error("[ERROR RED/FETCH]", err);
    return { success: false, error: err.message };
  }
}

/**
 * Envía una señal de VENTA al bot en GitHub.
 * 
 * @param {Object} options
 * @param {string} options.symbol - Par o activo (ej: "BTCUSDT")
 * @param {number} [options.quantity=0] - Cantidad a vender (0 para vender el 100% de la posición)
 * @param {number} [options.price=0] - Precio fijado (0 para precio actual)
 * @param {string} [options.notes=""] - Motivo de salida
 */
async function sendSellSignal({ symbol = "BTCUSDT", quantity = 0, price = 0, notes = "Take Profit Web" } = {}) {
  const url = `https://api.github.com/repos/${GITHUB_CONFIG.owner}/${GITHUB_CONFIG.repo}/dispatches`;

  const payload = {
    event_type: "sell_signal",
    client_payload: {
      action: "SELL",
      symbol: symbol.toUpperCase(),
      quantity: quantity,
      price: price,
      source: "Web Frontend Signal",
      notes: notes,
      timestamp: new Date().toISOString()
    }
  };

  try {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Accept": "application/vnd.github+json",
        "Authorization": `Bearer ${GITHUB_CONFIG.token}`,
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });

    if (response.status === 204) {
      console.log(`[EXITO] Senal de VENTA enviada a GitHub para ${symbol}.`);
      return { success: true, message: `Señal de venta enviada a GitHub para ${symbol}` };
    } else {
      const errorText = await response.text();
      console.error(`[ERROR] Codigo: ${response.status}`, errorText);
      return { success: false, status: response.status, error: errorText };
    }
  } catch (err) {
    console.error("[ERROR RED/FETCH]", err);
    return { success: false, error: err.message };
  }
}

// Exportar para uso en módulos o navegador global
if (typeof module !== "undefined" && module.exports) {
  module.exports = { sendBuySignal, sendSellSignal, GITHUB_CONFIG };
} else {
  window.sendBuySignal = sendBuySignal;
  window.sendSellSignal = sendSellSignal;
  window.GITHUB_CONFIG = GITHUB_CONFIG;
}
