#!/usr/bin/env node
/**
 * BTC Quant Terminal V6.5 - Node.js Cloud Guardian
 * Can be run in Node 18+ locally or in cloud runners
 */

const https = require('https');
const fs = require('fs');
const path = require('path');

const TELEGRAM_CONFIG = {
  token: process.env.TELEGRAM_BOT_TOKEN || '8635759809:AAF8YTMVkbVizhe2V7ciw_QtOktDqapJWo4',
  chatId: process.env.TELEGRAM_CHAT_ID || '159239770'
};

const QUANT_CONFIG = {
  symbol: 'BTCUSDT',
  timeframe: '15m',
  limit: 500,
  minScoreThreshold: 75,
  atrMultiplier: 1.55,
  minStopLossPts: 450,
  maxStopLossPts: 750,
  tp1Pts: 750,
  tp2Pts: 1350,
  breakEvenLockPts: 50
};

const LAST_ALERT_FILE = path.join(__dirname, 'last_alert.json');

function httpGet(url) {
  return new Promise((resolve, reject) => {
    https.get(url, { headers: { 'User-Agent': 'BTCQuantGuardian/6.5' } }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          reject(e);
        }
      });
    }).on('error', reject);
  });
}

function sendTelegram(text) {
  return new Promise((resolve) => {
    const postData = JSON.stringify({
      chat_id: TELEGRAM_CONFIG.chatId,
      text: text,
      parse_mode: 'HTML'
    });

    const req = https.request(`https://api.telegram.org/bot${TELEGRAM_CONFIG.token}/sendMessage`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(postData)
      }
    }, (res) => {
      let resp = '';
      res.on('data', chunk => resp += chunk);
      res.on('end', () => {
        console.log('[TELEGRAM] Respuesta:', resp);
        resolve(true);
      });
    });

    req.on('error', (err) => {
      console.error('[TELEGRAM ERROR]', err);
      resolve(false);
    });

    req.write(postData);
    req.end();
  });
}

async function main() {
  console.log(`[${new Date().toISOString()}] Ejecutando Node Quant Guardian...`);
  const url = `https://data-api.binance.vision/api/v3/klines?symbol=${QUANT_CONFIG.symbol}&interval=${QUANT_CONFIG.timeframe}&limit=${QUANT_CONFIG.limit}`;
  const raw = await httpGet(url);

  if (!Array.isArray(raw) || raw.length === 0) {
    console.error('Error obteniendo datos.');
    return;
  }

  const klines = raw.map(k => ({
    t: k[0],
    o: parseFloat(k[1]),
    h: parseFloat(k[2]),
    l: parseFloat(k[3]),
    c: parseFloat(k[4]),
    v: parseFloat(k[5])
  }));

  const cur = klines[klines.length - 1];
  console.log(`[PRECIO BTC] $${cur.c.toLocaleString()}`);

  // Require python logic for full 6-indicator evaluation in GitHub Actions
  console.log('[NODE GUARDIAN] Comprobación de estado finalizada.');
}

if (require.main === module) {
  main();
}
