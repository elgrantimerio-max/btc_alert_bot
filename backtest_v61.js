/**
 * BTC Quant Terminal V6.1 — Backtest Engine (JavaScript/Node)
 * ============================================================
 * Replica exacta de quant_bot_24_7.py con la configuración final:
 *   SL=700 | TP1=1000 (75%) | TP2=1500 (25%) | BE=400pts
 *   Score threshold: 68 | Max hold: 5 velas (20h) | Fee: 35 pts
 *   Bankroll: $5,000 | Notional: $20,000 | Leverage: 20x
 */

const https = require('https');
const fs = require('fs');
const path = require('path');

// ─── CONFIGURACIÓN V6.1 ─────────────────────────────────────────────────────
const CFG = {
    symbol: 'BTCUSDT', timeframe: '4h', limit: 600,
    min_score_threshold: 68,
    tp1_pts: 1000, tp2_pts: 1500, sl_pts: 700,
    tp1_partial_pct: 0.75,
    tp2_runner_pct: 0.25,
    break_even_lock_pts: 300,
    max_hold_candles: 5,
    friction_fee_pts: 35,
    bankroll_usdt: 5000.0,
    trade_notional_usdt: 20000.0,
    leverage: 20
};

// ─── FETCH DATA ────────────────────────────────────────────────────────────
function fetchKlines(symbol, interval, limit) {
    return new Promise((resolve, reject) => {
        const url = `https://data-api.binance.vision/api/v3/klines?symbol=${symbol}&interval=${interval}&limit=${limit}`;
        https.get(url, { headers: { 'User-Agent': 'BTCQuantBacktest/6.1' } }, (res) => {
            let data = '';
            res.on('data', d => data += d);
            res.on('end', () => {
                try {
                    const raw = JSON.parse(data);
                    if (Array.isArray(raw) && raw.length > 50) {
                        resolve(raw.map(k => ({
                            t: parseInt(k[0]), o: parseFloat(k[1]),
                            h: parseFloat(k[2]), l: parseFloat(k[3]),
                            c: parseFloat(k[4]), v: parseFloat(k[5])
                        })));
                    } else {
                        reject(new Error('Data inválida: ' + data.slice(0, 200)));
                    }
                } catch(e) { reject(e); }
            });
        }).on('error', reject);
    });
}

// ─── INDICADORES ─────────────────────────────────────────────────────────────
function calcTR(h, l, prevC) {
    if (prevC === null) return h - l;
    return Math.max(h - l, Math.abs(h - prevC), Math.abs(l - prevC));
}

function calcATR(klines, period = 14) {
    if (klines.length < period + 1) return 500.0;
    let atr = 0;
    for (let i = 1; i <= period; i++) atr += calcTR(klines[i].h, klines[i].l, klines[i-1].c);
    atr /= period;
    for (let i = period + 1; i < klines.length; i++) {
        atr = (atr * (period - 1) + calcTR(klines[i].h, klines[i].l, klines[i-1].c)) / period;
    }
    return atr;
}

function calcEMA(values, period) {
    if (!values.length) return [];
    const k = 2.0 / (period + 1);
    const ema = new Array(values.length).fill(0);
    const n = Math.min(period, values.length);
    ema[n-1] = values.slice(0, n).reduce((a,b) => a+b, 0) / n;
    for (let i = n; i < values.length; i++) ema[i] = values[i] * k + ema[i-1] * (1 - k);
    return ema;
}

function calcChoppiness(klines, period = 14) {
    if (klines.length <= period) return 50.0;
    let trSum = 0, maxH = -Infinity, minL = Infinity;
    for (let i = klines.length - period; i < klines.length; i++) {
        const prevC = i > 0 ? klines[i-1].c : klines[i].o;
        trSum += calcTR(klines[i].h, klines[i].l, prevC);
        if (klines[i].h > maxH) maxH = klines[i].h;
        if (klines[i].l < minL) minL = klines[i].l;
    }
    const rng = maxH - minL;
    if (rng <= 0) return 50.0;
    return Math.min(100, Math.max(0, 100.0 * (Math.log10(trSum / rng) / Math.log10(period))));
}

function calcADX(klines, period = 14) {
    if (klines.length <= period * 2) return 25.0;
    const tr = [], plusDM = [], minusDM = [];
    for (let i = 1; i < klines.length; i++) {
        const hd = klines[i].h - klines[i-1].h, ld = klines[i-1].l - klines[i].l;
        plusDM.push(hd > ld && hd > 0 ? hd : 0);
        minusDM.push(ld > hd && ld > 0 ? ld : 0);
        tr.push(calcTR(klines[i].h, klines[i].l, klines[i-1].c));
    }
    let trS = tr.slice(0, period).reduce((a,b)=>a+b,0);
    let pS  = plusDM.slice(0, period).reduce((a,b)=>a+b,0);
    let mS  = minusDM.slice(0, period).reduce((a,b)=>a+b,0);
    const dxArr = [];
    for (let i = period; i < tr.length; i++) {
        trS = trS - trS/period + tr[i];
        pS  = pS  - pS/period  + plusDM[i];
        mS  = mS  - mS/period  + minusDM[i];
        const pdi = trS > 0 ? pS/trS*100 : 0;
        const mdi = trS > 0 ? mS/trS*100 : 0;
        const dsum = pdi + mdi;
        dxArr.push(dsum > 0 ? Math.abs(pdi - mdi) / dsum * 100 : 0);
    }
    if (dxArr.length < period) return 25.0;
    let adx = dxArr.slice(0, period).reduce((a,b)=>a+b,0) / period;
    for (let i = period; i < dxArr.length; i++) adx = (adx * (period-1) + dxArr[i]) / period;
    return adx;
}

function calcVWAP(klines, lookback = 96) {
    const sub = klines.slice(-Math.min(klines.length, lookback));
    let cumPV = 0, cumV = 0;
    for (const k of sub) { const tp = (k.h+k.l+k.c)/3; cumPV += tp*k.v; cumV += k.v; }
    return cumV > 0 ? cumPV/cumV : klines[klines.length-1].c;
}

function calcRSI(klines, period = 14) {
    if (klines.length <= period) return 50.0;
    let ag = 0, al = 0;
    for (let i = 1; i <= period; i++) {
        const d = klines[i].c - klines[i-1].c;
        if (d >= 0) ag += d; else al -= d;
    }
    ag /= period; al /= period;
    for (let i = period + 1; i < klines.length; i++) {
        const d = klines[i].c - klines[i-1].c;
        if (d >= 0) { ag = (ag*(period-1)+d)/period; al = (al*(period-1))/period; }
        else         { ag = (ag*(period-1))/period;   al = (al*(period-1)-d)/period; }
    }
    if (al === 0) return 100.0;
    return 100.0 - (100.0 / (1.0 + ag/al));
}

function calcIchimoku(klines, tenkanP=9, kijunP=26, spanBP=52) {
    if (klines.length < spanBP) return null;
    const mid = sub => (Math.max(...sub.map(k=>k.h)) + Math.min(...sub.map(k=>k.l))) / 2.0;
    const n = klines.length;
    const refIdx = Math.max(spanBP, n - 26);
    const spanA = (mid(klines.slice(refIdx-tenkanP, refIdx)) + mid(klines.slice(refIdx-kijunP, refIdx))) / 2.0;
    const spanB = mid(klines.slice(refIdx-spanBP, refIdx));
    return {
        kumo_top: Math.max(spanA, spanB), kumo_bottom: Math.min(spanA, spanB),
        tenkan: mid(klines.slice(-tenkanP)), kijun: mid(klines.slice(-kijunP)),
        is_bullish_cloud: spanA >= spanB
    };
}

function calcTTMSqueeze(klines, period=20, bbMult=2.0, kcMult=1.5) {
    if (klines.length < period) return { is_squeeze: false, momentum: 0.0 };
    const sub = klines.slice(-period);
    const closes = sub.map(k=>k.c);
    const sma = closes.reduce((a,b)=>a+b,0) / period;
    const stdev = Math.sqrt(closes.reduce((a,c)=>a+(c-sma)**2,0) / period);
    const atr = calcATR(sub, period);
    const is_squeeze = (sma+bbMult*stdev < sma+kcMult*atr) && (sma-bbMult*stdev > sma-kcMult*atr);
    const midPt = ((Math.max(...sub.map(k=>k.h)) + Math.min(...sub.map(k=>k.l))) / 2.0 + sma) / 2.0;
    return { is_squeeze, momentum: sub[sub.length-1].c - midPt };
}

function calcOrderFlow(klines) {
    const deltas = klines.map(k => {
        const rng = k.h - k.l;
        const buy = rng > 0 ? (k.c-k.l)/rng : 0.5;
        const sell = rng > 0 ? (k.h-k.c)/rng : 0.5;
        return k.v * (buy - sell);
    });
    const last3 = deltas.slice(-3).reduce((a,b)=>a+b,0);
    let rvol = 1.0;
    if (klines.length >= 20) {
        const avg20 = klines.slice(-20).reduce((a,k)=>a+k.v,0) / 20.0;
        rvol = avg20 > 0 ? klines[klines.length-1].v / avg20 : 1.0;
    }
    return { last3, rvol };
}

// ─── EVALUATE SIGNAL ─────────────────────────────────────────────────────────
function evaluateSignal(klines) {
    if (klines.length < 50) return null;
    const cur = klines[klines.length-1];
    const curPrice = cur.c;

    // Session Filter (Wall Street / London / Overlap / Weekend)
    const dt = new Date(cur.t);
    const dayOfWeek = dt.getUTCDay(); // 0=Sun, 6=Sat
    const utcH = dt.getUTCHours() + dt.getUTCMinutes() / 60.0;
    const isSaturday = (dayOfWeek === 6);
    const isSunday = (dayOfWeek === 0);

    let session = 'ASIAN', ss = 5;
    if (isSaturday || (isSunday && utcH < 22.0)) {
        session = 'WEEKEND';
        ss = 0;
    } else if (isSunday && utcH >= 22.0) {
        session = 'CME_OPEN';
        ss = 6;
    } else {
        const isLondon = utcH >= 8.0 && utcH < 16.5;
        const isNY = utcH >= 13.0 && utcH < 21.0;
        const isOverlap = utcH >= 13.5 && utcH < 16.5;
        if (isOverlap) { session = 'OVERLAP'; ss = 15; }
        else if (isNY) { session = 'NEWYORK'; ss = 12; }
        else if (isLondon) { session = 'LONDON'; ss = 12; }
        else if (utcH >= 0.0 && utcH < 8.0) { session = 'ASIAN'; ss = 5; }
        else { session = 'INTERSESSION'; ss = 3; }
    }
    ss = Math.min(15, Math.max(0, ss));

    const chop = calcChoppiness(klines, 14);
    const adx  = calcADX(klines, 14);
    const ttm  = calcTTMSqueeze(klines, 20);
    const atr  = calcATR(klines, 14);

    if (chop > 61.8 && adx < 22.0) return { score: 0, direction: 'HIBERNATION', session };

    let grayZone = false, acs;
    if (ttm.is_squeeze)              acs = 4;
    else if (adx > 25.0 && chop < 48.0) acs = 15;
    else if (chop < 52.0)            acs = 12;
    else if (chop >= 55.0 && chop <= 61.8 && adx < 20.0) { acs = 4; grayZone = true; }
    else                             acs = 7;
    acs = Math.min(15, acs);

    // ORB simplified (30-candle rolling)
    const rec30 = klines.slice(-31, -1);
    const orbHigh = rec30.length ? Math.max(...rec30.map(k=>k.h)) : curPrice;
    const orbLow  = rec30.length ? Math.min(...rec30.map(k=>k.l)) : curPrice;
    const lkb96 = klines.slice(-97, -1);
    const h24 = lkb96.length ? Math.max(...lkb96.map(k=>k.h)) : curPrice;
    const l24 = lkb96.length ? Math.min(...lkb96.map(k=>k.l)) : curPrice;
    const adrRem = Math.max(0, 2500.0 - (h24 - l24));
    let orbScore = 0, longOrb = false, shortOrb = false;
    if (adrRem > 700) {
        orbScore += 7;
        if (curPrice > orbHigh) { longOrb = true; orbScore += 8; }
        else if (curPrice < orbLow) { shortOrb = true; orbScore += 8; }
    } else orbScore = 2;
    orbScore = Math.min(15, orbScore);

    const vwap  = calcVWAP(klines, 96);
    const closes = klines.map(k=>k.c);
    const ema20  = calcEMA(closes, 20).at(-1);
    const ema50  = calcEMA(closes, 50).at(-1);
    const ema100 = calcEMA(closes, 100).at(-1);
    const ema200 = calcEMA(closes, 200).at(-1);
    const rsi    = calcRSI(klines, 14);

    let slL = 0, slS = 0;
    if (curPrice > vwap && ema20 > ema50) slL += 10;
    else if (curPrice < vwap && ema20 < ema50) slS += 10;
    const macroBull = curPrice > ema200 && ema100 > ema200;
    const macroBear = curPrice < ema200 && ema100 < ema200;
    if (macroBull) slL += 8; else if (macroBear) slS += 8;

    const ichi = calcIchimoku(klines);
    let ibL = false, ibS = false;
    if (ichi) {
        if (curPrice > ichi.kumo_top)    { slL += 7; slS = Math.max(0, slS-18); ibS = true; }
        else if (curPrice < ichi.kumo_bottom) { slS += 7; slL = Math.max(0, slL-18); ibL = true; }
        else { slL = Math.max(0, slL-6); slS = Math.max(0, slS-6); }
    }

    if (rsi < 35.0)     slL += 5; else if (rsi >= 40 && rsi <= 68) slL += 3; else if (rsi > 80) slL -= 8;
    if (rsi > 75.0)     slS += 5; else if (rsi >= 32 && rsi <= 60) slS += 3; else if (rsi < 20) slS -= 8;

    const last3c = klines.slice(-4, -1);
    if (last3c.length >= 2) {
        if (last3c.filter(k=>k.c>k.o).length >= 2) slL += 5;
        if (last3c.filter(k=>k.c<k.o).length >= 2) slS += 5;
    }

    const dist20 = curPrice - ema20;
    if (dist20 > 1.1*atr || rsi > 70) slL = Math.max(0, slL-10);
    if (dist20 < -1.1*atr || rsi < 30) slS = Math.max(0, slS-10);
    slL = Math.min(30, Math.max(0, slL));
    slS = Math.min(30, Math.max(0, slS));

    const { last3: cvd, rvol } = calcOrderFlow(klines);
    let ofL = (rvol >= 1.2 ? (cvd > 0 ? 9 : 0) : (cvd > 0 ? 5 : 0));
    let ofS = (rvol >= 1.2 ? (cvd < 0 ? 9 : 0) : (cvd < 0 ? 5 : 0));
    ofL = Math.min(15, Math.max(0, ofL));
    ofS = Math.min(15, Math.max(0, ofS));

    let liqL = 0, liqS = 0;
    if (rec30.length > 5) {
        const rh = Math.max(...rec30.map(k=>k.h)), rl = Math.min(...rec30.map(k=>k.l));
        if (cur.l < rl && cur.c > rl) liqL = (macroBull || curPrice > ema50) ? 6 : 2;
        if (cur.h > rh && cur.c < rh) liqS = (macroBear || curPrice < ema50) ? 6 : 2;
    }
    liqL = Math.min(6, liqL); liqS = Math.min(6, liqS);

    const totalL = ss + acs + orbScore + slL + ofL + liqL;
    const totalS = ss + acs + orbScore + slS + ofS + liqS;
    const isLongDom = totalL >= totalS;
    let score = Math.min(100, Math.round(isLongDom ? totalL : totalS));
    const thresh = CFG.min_score_threshold;

    let direction = 'NEUTRAL';
    if (score >= thresh) direction = isLongDom ? 'LONG' : 'SHORT';
    else if (score >= 45) direction = isLongDom ? 'BIAS_LONG' : 'BIAS_SHORT';

    if (direction === 'LONG'  && ibL) { direction = 'NEUTRAL'; score = Math.min(score, 40); }
    if (direction === 'SHORT' && ibS) { direction = 'NEUTRAL'; score = Math.min(score, 40); }
    if (direction === 'SHORT' && curPrice > ema200) { direction = 'NEUTRAL'; score = Math.min(score, 40); }
    if (direction === 'LONG'  && curPrice < ema200) { direction = 'NEUTRAL'; score = Math.min(score, 40); }
    if (ttm.is_squeeze && score >= thresh) { direction = isLongDom ? 'BIAS_LONG' : 'BIAS_SHORT'; score = thresh-5; }
    if (Math.abs(totalL-totalS) < 8 && (direction==='LONG'||direction==='SHORT')) {
        direction = isLongDom ? 'BIAS_LONG' : 'BIAS_SHORT'; score = Math.min(score, thresh-3);
    }
    if (grayZone && score < thresh+3 && (direction==='LONG'||direction==='SHORT')) {
        direction = isLongDom ? 'BIAS_LONG' : 'BIAS_SHORT'; score = thresh-4;
    }

    return { score, direction, session, cur_price: curPrice, rsi, chop, adx, atr, ema20, ema50, ema200, vwap };
}

// ─── BACKTEST ENGINE ──────────────────────────────────────────────────────────
function runBacktest(klines) {
    const { tp1_pts, tp2_pts, sl_pts, tp1_partial_pct, tp2_runner_pct,
            break_even_lock_pts, max_hold_candles, friction_fee_pts,
            bankroll_usdt, trade_notional_usdt } = CFG;

    const trades = [];
    let equity = bankroll_usdt;
    const equityCurve = [equity];
    let inTrade = false, entrySig = null, entryIdx = null, beTriggered = false, partialDone = false;
    const WARMUP = 210;

    for (let i = WARMUP; i < klines.length; i++) {
        const window = klines.slice(0, i+1);
        const sig = evaluateSignal(window);
        if (!sig) { equityCurve.push(equity); continue; }

        if (inTrade) {
            const cur = klines[i];
            const isLong = entrySig.direction === 'LONG';
            const ep = entrySig.cur_price;
            const tp1 = isLong ? ep + tp1_pts : ep - tp1_pts;
            const tp2 = isLong ? ep + tp2_pts : ep - tp2_pts;
            let sl = entrySig.sl_price;
            const hold = i - entryIdx;

            let outcome = null, pnlPts = null;

            if (isLong) {
                if (!partialDone && cur.h >= tp1) {
                    const tp1Pnl = (tp1 - ep - friction_fee_pts) * tp1_partial_pct;
                    const runnerSL = ep + break_even_lock_pts;
                    if (cur.h >= tp2) {
                        const tp2Pnl = (tp2 - ep - friction_fee_pts) * tp2_runner_pct;
                        outcome = 'TP2'; pnlPts = tp1Pnl + tp2Pnl;
                    } else if (cur.l <= runnerSL) {
                        const tp2Pnl = (runnerSL - ep - friction_fee_pts) * tp2_runner_pct;
                        outcome = 'TP1+BE'; pnlPts = tp1Pnl + tp2Pnl;
                    } else {
                        // Partial done, runner open
                        partialDone = true; beTriggered = true;
                        entrySig.sl_price = runnerSL;
                        equityCurve.push(equity); continue;
                    }
                } else if (partialDone) {
                    // Runner position
                    if (cur.h >= tp2) {
                        const tp2Pnl = (tp2 - ep - friction_fee_pts) * tp2_runner_pct;
                        outcome = 'TP2_RUNNER'; pnlPts = tp2Pnl;
                    } else if (cur.l <= entrySig.sl_price) {
                        const tp2Pnl = (entrySig.sl_price - ep - friction_fee_pts) * tp2_runner_pct;
                        outcome = 'TP1+BE'; pnlPts = tp2Pnl;
                    } else if (hold >= max_hold_candles) {
                        const tp2Pnl = (cur.c - ep - friction_fee_pts) * tp2_runner_pct;
                        outcome = 'TIMEOUT_RUNNER'; pnlPts = tp2Pnl;
                    }
                } else if (cur.l <= sl) {
                    pnlPts = -(sl_pts + friction_fee_pts); outcome = 'SL';
                } else if (hold >= max_hold_candles) {
                    pnlPts = (cur.c - ep - friction_fee_pts); outcome = 'TIMEOUT';
                }
            } else { // SHORT
                if (!partialDone && cur.l <= tp1) {
                    const tp1Pnl = (ep - tp1 - friction_fee_pts) * tp1_partial_pct;
                    const runnerSL = ep - break_even_lock_pts;
                    if (cur.l <= tp2) {
                        const tp2Pnl = (ep - tp2 - friction_fee_pts) * tp2_runner_pct;
                        outcome = 'TP2'; pnlPts = tp1Pnl + tp2Pnl;
                    } else if (cur.h >= runnerSL) {
                        const tp2Pnl = (ep - runnerSL - friction_fee_pts) * tp2_runner_pct;
                        outcome = 'TP1+BE'; pnlPts = tp1Pnl + tp2Pnl;
                    } else {
                        partialDone = true; beTriggered = true;
                        entrySig.sl_price = runnerSL;
                        equityCurve.push(equity); continue;
                    }
                } else if (partialDone) {
                    if (cur.l <= tp2) {
                        const tp2Pnl = (ep - tp2 - friction_fee_pts) * tp2_runner_pct;
                        outcome = 'TP2_RUNNER'; pnlPts = tp2Pnl;
                    } else if (cur.h >= entrySig.sl_price) {
                        const tp2Pnl = (ep - entrySig.sl_price - friction_fee_pts) * tp2_runner_pct;
                        outcome = 'TP1+BE'; pnlPts = tp2Pnl;
                    } else if (hold >= max_hold_candles) {
                        const tp2Pnl = (ep - cur.c - friction_fee_pts) * tp2_runner_pct;
                        outcome = 'TIMEOUT_RUNNER'; pnlPts = tp2Pnl;
                    }
                } else if (cur.h >= sl) {
                    pnlPts = -(sl_pts + friction_fee_pts); outcome = 'SL';
                } else if (hold >= max_hold_candles) {
                    pnlPts = (ep - cur.c - friction_fee_pts); outcome = 'TIMEOUT';
                }
            }

            if (outcome && pnlPts !== null) {
                const pnlUSD = pnlPts * (trade_notional_usdt / ep);
                equity += pnlUSD;
                equityCurve.push(equity);
                const dt = new Date(klines[entryIdx].t);
                const dt2 = new Date(klines[i].t);
                trades.push({
                    entry_i: entryIdx, exit_i: i,
                    direction: entrySig.direction,
                    entry_price: ep, exit_price: klines[i].c,
                    outcome, pnl_pts: pnlPts, pnl_usd: pnlUSD, equity,
                    hold_candles: hold,
                    entry_date: dt.toISOString().slice(0,16).replace('T',' '),
                    exit_date:  dt2.toISOString().slice(0,16).replace('T',' '),
                    score: entrySig.score, rsi: entrySig.rsi, chop: entrySig.chop
                });
                inTrade = false; entrySig = null; entryIdx = null;
                beTriggered = false; partialDone = false;
            } else {
                equityCurve.push(equity);
            }
        }

        if (!inTrade && (sig.direction === 'LONG' || sig.direction === 'SHORT')) {
            inTrade = true;
            entrySig = { ...sig, sl_price: sig.direction === 'LONG' ? sig.cur_price - sl_pts : sig.cur_price + sl_pts };
            entryIdx = i;
            equityCurve.push(equity);
        } else if (!inTrade) {
            equityCurve.push(equity);
        }
    }
    return { trades, equityCurve };
}

// ─── ANÁLISIS ────────────────────────────────────────────────────────────────
function analyze(trades, equityCurve, klines) {
    if (!trades.length) { console.log('\n[!] Sin trades. Score threshold demasiado alto.\n'); return null; }

    const initEq = CFG.bankroll_usdt;
    const finalEq = equityCurve[equityCurve.length-1];
    const totalPnL = finalEq - initEq;
    const roi = (totalPnL / initEq) * 100.0;

    const wins  = trades.filter(t => t.pnl_usd > 0);
    const loses = trades.filter(t => t.pnl_usd <= 0);
    const tp2s  = trades.filter(t => t.outcome.startsWith('TP2'));
    const tp1be = trades.filter(t => t.outcome.startsWith('TP1+BE'));
    const sls   = trades.filter(t => t.outcome === 'SL');
    const touts  = trades.filter(t => t.outcome.includes('TIMEOUT'));
    const longs = trades.filter(t => t.direction === 'LONG');
    const shrts = trades.filter(t => t.direction === 'SHORT');

    const winRate = wins.length / trades.length * 100;
    const avgWin  = wins.length  ? wins.reduce((a,t)=>a+t.pnl_usd,0)  / wins.length  : 0;
    const avgLoss = loses.length ? loses.reduce((a,t)=>a+t.pnl_usd,0) / loses.length : 0;
    const rrRatio = avgLoss !== 0 ? Math.abs(avgWin/avgLoss) : Infinity;

    let peak = initEq, maxDD = 0;
    for (const eq of equityCurve) {
        if (eq > peak) peak = eq;
        const dd = (peak - eq) / peak * 100;
        if (dd > maxDD) maxDD = dd;
    }

    const grossProfit = wins.reduce((a,t)=>a+t.pnl_usd,0);
    const grossLoss   = Math.abs(loses.reduce((a,t)=>a+t.pnl_usd,0));
    const pf = grossLoss > 0 ? grossProfit / grossLoss : Infinity;
    const avgHold = trades.reduce((a,t)=>a+t.hold_candles,0) / trades.length;

    const nDays = (klines[klines.length-1].t - klines[0].t) / (1000*3600*24);
    const startDate = new Date(klines[0].t).toISOString().slice(0,10);
    const endDate   = new Date(klines[klines.length-1].t).toISOString().slice(0,10);

    const sep = '═'.repeat(65);
    const dash = '─'.repeat(65);

    console.log('\n' + sep);
    console.log('  📊  BTC QUANT TERMINAL V6.1 — BACKTEST REPORT');
    console.log('  Últimas 500 velas 4H  |  SL=700 TP1=1000(75%) TP2=1500(25%)');
    console.log(sep);
    console.log(`  📅  Período: ${startDate} → ${endDate} (${nDays.toFixed(0)} días)`);
    console.log(`  💰  Bankroll Inicial:   $${initEq.toLocaleString('en-US', {minimumFractionDigits:2})}`);
    console.log(`  💰  Bankroll Final:     $${finalEq.toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2})}`);
    console.log(`  📈  ROI Total:          ${roi >= 0 ? '+' : ''}${roi.toFixed(2)}%  ($${totalPnL >= 0 ? '+' : ''}${totalPnL.toFixed(2)})`);
    console.log(`  📉  Max Drawdown:       ${maxDD.toFixed(2)}%`);
    console.log(`  ⚡  Profit Factor:      ${pf === Infinity ? '∞' : pf.toFixed(2)}x`);
    console.log(dash);
    console.log(`  🔢  Total de Trades:    ${trades.length}`);
    console.log(`  ✅  Win Rate:           ${winRate.toFixed(1)}%  (${wins.length}W / ${loses.length}L)`);
    console.log(`  🎯  TP2 Full:           ${tp2s.length}  (${(tp2s.length/trades.length*100).toFixed(1)}%)`);
    console.log(`  🛡️  TP1+Break-Even:    ${tp1be.length}  (${(tp1be.length/trades.length*100).toFixed(1)}%)`);
    console.log(`  🔴  Stop-Loss:          ${sls.length}   (${(sls.length/trades.length*100).toFixed(1)}%)`);
    console.log(`  ⏱️  Timeout:            ${touts.length}  (${(touts.length/trades.length*100).toFixed(1)}%)`);
    console.log(`  📊  Longs: ${longs.length}  |  Shorts: ${shrts.length}`);
    console.log(dash);
    console.log(`  💚  Avg Ganancia:       $${avgWin >= 0 ? '+' : ''}${avgWin.toFixed(2)}`);
    console.log(`  ❤️  Avg Pérdida:       $${avgLoss.toFixed(2)}`);
    console.log(`  ⚖️  Ratio R:R real:    ${rrRatio === Infinity ? '∞' : rrRatio.toFixed(2)}:1`);
    console.log(`  ⏳  Hold Promedio:      ${avgHold.toFixed(1)} velas (${(avgHold*4).toFixed(0)}h)`);
    console.log(dash);

    const best5 = [...trades].sort((a,b)=>b.pnl_usd-a.pnl_usd).slice(0,5);
    console.log('\n  🏆  TOP 5 MEJORES TRADES:');
    best5.forEach(t => console.log(`    ${t.entry_date} ${t.direction.padEnd(5)} → ${t.outcome.padEnd(12)}  PnL: $${t.pnl_usd >= 0 ? '+' : ''}${t.pnl_usd.toFixed(2).padStart(8)}  (Score: ${t.score})`));

    const worst5 = [...trades].sort((a,b)=>a.pnl_usd-b.pnl_usd).slice(0,5);
    console.log('\n  💀  TOP 5 PEORES TRADES:');
    worst5.forEach(t => console.log(`    ${t.entry_date} ${t.direction.padEnd(5)} → ${t.outcome.padEnd(12)}  PnL: $${t.pnl_usd >= 0 ? '+' : ''}${t.pnl_usd.toFixed(2).padStart(8)}  (Score: ${t.score})`));

    console.log('\n' + sep);
    console.log('  📋  ANÁLISIS ROI Y MEJORAS SUGERIDAS');
    console.log(sep);

    const suggestions = [];
    if (winRate < 50) suggestions.push(['🔧 Score Threshold', `Win rate ${winRate.toFixed(1)}% < 50%. Subir min_score_threshold de 68 → 72-75 para filtrar señales marginales.`]);
    if (rrRatio !== Infinity && rrRatio < 1.5) suggestions.push(['🔧 R:R Real Bajo', `R:R efectivo de ${rrRatio.toFixed(2)}:1. Considerar TP1=1200 pts o SL=600 pts para mejorar ratio.`]);
    if (sls.length/trades.length > 0.40) suggestions.push(['🔧 SL Frecuente', `${(sls.length/trades.length*100).toFixed(0)}% de trades tocan SL. SL de 700 pts estrecho en alta volatilidad. Evaluar SL dinámico basado en ATR.`]);
    if (avgHold > 3.5) suggestions.push(['🔧 Hold Promedio Alto', `Hold de ${avgHold.toFixed(1)} velas. Implementar early_exit si precio vuelve al VWAP con +300 pts de ganancia.`]);
    if (tp2s.length/trades.length < 0.15) suggestions.push(['🔧 TP2 Escaso', `Solo ${(tp2s.length/trades.length*100).toFixed(1)}% llegan a TP2. Reducir TP2: 1500→1200 pts para capturar más extensiones completas.`]);
    if (pf !== Infinity && pf < 1.5) suggestions.push(['🔧 Profit Factor Bajo', 'PF < 1.5x. Aplicar filtro de sesión estricto: solo operar OVERLAP+LONDON. Bloquear señales ASIÁTICAS con chop > 55.']);
    if (maxDD > 20) suggestions.push(['⚠️ Drawdown Alto', `Drawdown de ${maxDD.toFixed(1)}%. Reducir notional a $15,000 (x15) o pausar 24h tras 2 SL consecutivos.`]);
    if (winRate >= 55 && roi > 20 && maxDD < 15) suggestions.push(['✅ Sistema Sólido', `ROI ${roi.toFixed(1)}% con DD ${maxDD.toFixed(1)}%. Considerar escalar notional a $25,000 gradualmente.`]);

    if (!suggestions.length) suggestions.push(['✅ KPIs Normales', 'Sistema dentro de parámetros. Monitorear 2 semanas más antes de ajustar.']);

    suggestions.forEach(([title, desc]) => {
        console.log(`\n  ${title}:`);
        console.log(`    ${desc}`);
    });

    console.log('\n' + sep);

    return { roi, totalPnL, winRate, maxDD, profit_factor: pf, rr_ratio: rrRatio, total_trades: trades.length, tp2_count: tp2s.length, sl_count: sls.length, suggestions: suggestions.map(s=>s[0]) };
}

// ─── MAIN ─────────────────────────────────────────────────────────────────────
(async () => {
    console.log('[*] Descargando 600 velas 4H de BTCUSDT desde Binance...');
    let klines;
    try {
        klines = await fetchKlines('BTCUSDT', '4h', 600);
    } catch(e) {
        console.error('[ERROR] Fallo al obtener datos:', e.message);
        process.exit(1);
    }

    // Usar exactamente los últimos 500 periodos
    klines = klines.slice(-500);
    console.log(`[*] ${klines.length} velas cargadas. Ejecutando backtest V6.1...`);

    const { trades, equityCurve } = runBacktest(klines);
    console.log(`[*] Trades generados: ${trades.length}`);
    const results = analyze(trades, equityCurve, klines);

    const outFile = path.join(__dirname, 'backtest_results_v61.json');
    fs.writeFileSync(outFile, JSON.stringify({ config: CFG, results, trades, equity_curve: equityCurve }, null, 2));
    console.log(`\n[✓] Resultados guardados en: ${outFile}`);
})();
