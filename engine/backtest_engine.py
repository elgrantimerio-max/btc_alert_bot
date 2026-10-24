"""
BTC Quant Terminal V6.5 - Unified Backtesting Engine (engine/backtest_engine.py)
Features:
- Single Source of Truth: Uses exact engine.quant_core functions.
- Dynamic ATR Volatility Targets (1.5x SL / 2.0x TP1 / 3.5x TP2).
- Fixed Fractional Risk Sizing (2% standard / 3% Tier A+).
- Intrabar Microstructure Trajectory Resolution (Eliminates TP-before-SL favorable bias).
- Realistic Commission & Friction Modeling (0.06% combined taker + slippage).
"""

import json
import math
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from .quant_core import (
    Kline,
    calculate_atr,
    evaluate_signal,
    calculate_dynamic_targets,
    calculate_fixed_fractional_size,
    QUANT_CONFIG
)


def resolve_intrabar_exit(
    trade: Dict[str, Any],
    cur_k: Kline,
    is_long: bool
) -> Tuple[bool, float, str]:
    """
    Intrabar Execution Resolution without Favorable Bias:
    Determines whether Stop-Loss or Take-Profit occurred first when both price extremes
    are touched within the same candle.
    Microstructure Trajectory Model:
      - Bullish Candle (Close >= Open): Open -> Low -> High -> Close.
        * For Longs: If Low <= SL, SL was touched during the initial downward dip before High!
      - Bearish Candle (Close < Open): Open -> High -> Low -> Close.
        * For Shorts: If High >= SL, SL was touched during the initial upward retrace before Low!
    """
    hit_sl = (cur_k.l <= trade['sl']) if is_long else (cur_k.h >= trade['sl'])
    hit_tp1 = (cur_k.h >= trade['tp1']) if is_long else (cur_k.l <= trade['tp1'])
    hit_tp2 = (cur_k.h >= trade['tp2']) if is_long else (cur_k.l <= trade['tp2'])

    is_bullish_bar = cur_k.c >= cur_k.o

    # Case A: TP1 not yet hit and both SL and TP1 reached in this candle
    if not trade['tp1_hit'] and hit_sl and hit_tp1:
        if is_long:
            if is_bullish_bar:
                # Open -> Low -> High: Low hit first -> STOPPED OUT FIRST
                return True, trade['sl'], f"SL (-{trade['targets']['sl_dist']} pts) [Intrabar dip]"
            else:
                # Open -> High -> Low: High hit first -> TP1 HIT FIRST
                trade['tp1_hit'] = True
                trade['remaining_fraction'] = 1.0 - QUANT_CONFIG['tp1_partial_pct']
                trade['realized_usd'] += trade['targets']['tp1_dist'] * (trade['btc_size'] * QUANT_CONFIG['tp1_partial_pct'])
                # Stop moved to Break-Even + lock pts
                trade['sl'] = trade['entry'] + trade['targets']['be_lock_pts']
                # Then Low hit BE stop
                if cur_k.l <= trade['sl']:
                    return True, trade['sl'], f"BE (+{trade['targets']['be_lock_pts']} pts) [Intrabar]"
                return False, 0.0, ""
        else:
            # Short position
            if is_bullish_bar:
                # Open -> Low -> High: Low (TP1) hit first
                trade['tp1_hit'] = True
                trade['remaining_fraction'] = 1.0 - QUANT_CONFIG['tp1_partial_pct']
                trade['realized_usd'] += trade['targets']['tp1_dist'] * (trade['btc_size'] * QUANT_CONFIG['tp1_partial_pct'])
                trade['sl'] = trade['entry'] - trade['targets']['be_lock_pts']
                if cur_k.h >= trade['sl']:
                    return True, trade['sl'], f"BE (+{trade['targets']['be_lock_pts']} pts) [Intrabar]"
                return False, 0.0, ""
            else:
                # Open -> High -> Low: High (SL) hit first -> STOPPED OUT FIRST
                return True, trade['sl'], f"SL (-{trade['targets']['sl_dist']} pts) [Intrabar peak]"

    # Case B: Standard evaluation if no conflicting collision
    # 1. TP2 Check (Runner exit)
    if hit_tp2:
        return True, trade['tp2'], f"TP2 (+{trade['targets']['tp2_dist']} pts Hit)"

    # 2. TP1 First Time Check
    if not trade['tp1_hit'] and hit_tp1:
        trade['tp1_hit'] = True
        trade['tp1_hit_candle'] = cur_k.t
        trade['remaining_fraction'] = 1.0 - QUANT_CONFIG['tp1_partial_pct']
        trade['realized_usd'] += trade['targets']['tp1_dist'] * (trade['btc_size'] * QUANT_CONFIG['tp1_partial_pct'])
        trade['sl'] = (trade['entry'] + trade['targets']['be_lock_pts']) if is_long else (trade['entry'] - trade['targets']['be_lock_pts'])

    # 3. Stop-Loss Check (Only check BE stop on subsequent candles to avoid retroactively comparing to pre-rally low)
    allow_sl_check = (not trade['tp1_hit'] or trade.get('tp1_hit_candle') != cur_k.t)
    if allow_sl_check and hit_sl:
        reason = f"BE (+{trade['targets']['be_lock_pts']} pts)" if trade['tp1_hit'] else f"SL (-{trade['targets']['sl_dist']} pts)"
        return True, trade['sl'], reason

    return False, 0.0, ""


def run_backtest_simulation(
    klines: List[Kline],
    initial_bankroll: float = 5000.0,
    timeframe: str = '4h',
    max_hold_hours: int = 20,
    cooldown_candles: int = 2
) -> Dict[str, Any]:
    """
    Executes a high-fidelity quantitative backtest across historical klines.
    """
    if len(klines) < 100:
        raise ValueError(f"Datos insuficientes para backtest: {len(klines)} velas (mínimo 100)")

    hours_per_candle = 4 if timeframe == '4h' else (1 if timeframe == '1h' else 24)
    max_hold_candles = max(1, round(max_hold_hours / hours_per_candle))

    balance = initial_bankroll
    equity_curve = [{
        'candle': 50,
        'time': klines[50].t,
        'balance': round(balance, 2),
        'trade_id': 0
    }]

    wins = 0
    losses = 0
    total_trades = 0
    total_pts = 0
    gross_profit_usd = 0.0
    gross_loss_usd = 0.0
    peak_balance = balance
    max_dd_usd = 0.0
    max_dd_pct = 0.0

    in_trade = False
    trade: Optional[Dict[str, Any]] = None
    last_close_candle = -999
    trades_list: List[Dict[str, Any]] = []

    for i in range(50, len(klines)):
        cur_k = klines[i]

        # 1. If FLAT, evaluate potential new entry signal
        if not in_trade and (i - last_close_candle) >= cooldown_candles:
            sub = klines[:i + 1]
            sig = evaluate_signal(sub)

            if sig and sig['direction'] in ('LONG', 'SHORT'):
                is_long = sig['direction'] == 'LONG'
                targets = sig['targets']
                sizing = calculate_fixed_fractional_size(
                    bankroll=balance,
                    sl_distance_usd=targets['sl_dist'],
                    cur_price=cur_k.c,
                    is_tier_a_plus=sig['is_tier_a_plus']
                )

                if sizing['size_btc'] > 0:
                    in_trade = True
                    trade = {
                        'id': total_trades + 1,
                        'direction': sig['direction'],
                        'entry': cur_k.c,
                        'btc_size': sizing['size_btc'],
                        'notional': sizing['notional_usd'],
                        'risk_usd': sizing['risk_usd'],
                        'is_tier_a_plus': sig['is_tier_a_plus'],
                        'tier': sig['tier'],
                        'score': sig['score'],
                        'sl': targets['sl'],
                        'tp1': targets['tp1'],
                        'tp2': targets['tp2'],
                        'targets': targets,
                        'tp1_hit': False,
                        'remaining_fraction': 1.0,
                        'realized_usd': 0.0,
                        'peak_price': cur_k.c,
                        'open_candle': i,
                        'open_time': cur_k.t,
                        'max_hold_candles': max_hold_candles
                    }

        # 2. If IN TRADE, manage position & check exits
        elif in_trade and trade is not None:
            is_long = trade['direction'] == 'LONG'
            bars_held = i - trade['open_candle']

            # Update peak price for trailing
            if is_long and cur_k.h > trade['peak_price']:
                trade['peak_price'] = cur_k.h
            elif not is_long and cur_k.l < trade['peak_price']:
                trade['peak_price'] = cur_k.l

            # Dynamic Trailing SL after TP1
            if trade['tp1_hit']:
                fav_dist = (trade['peak_price'] - trade['entry']) if is_long else (trade['entry'] - trade['peak_price'])
                if fav_dist >= trade['targets']['trailing_trigger']:
                    trail_sl = (trade['peak_price'] - trade['targets']['trailing_distance']) if is_long else (trade['peak_price'] + trade['targets']['trailing_distance'])
                    if is_long and trail_sl > trade['sl']:
                        trade['sl'] = trail_sl
                    elif not is_long and trail_sl < trade['sl']:
                        trade['sl'] = trail_sl

            # Evaluate Intrabar Exit (SL / BE / TP1 / TP2)
            closed, exit_price, exit_reason = resolve_intrabar_exit(trade, cur_k, is_long)

            # Check Time Decay Exit (Max Hold Candles reached)
            if not closed and bars_held >= trade['max_hold_candles']:
                closed = True
                exit_price = cur_k.c
                exit_reason = f"Timeout {bars_held * hours_per_candle}h ({bars_held} velas)"

            # If closed, finalize trade accounting
            if closed:
                in_trade = False
                last_close_candle = i

                # Remaining profit calculation
                pts_rem = (exit_price - trade['entry']) if is_long else (trade['entry'] - exit_price)
                rem_usd = pts_rem * (trade['btc_size'] * trade['remaining_fraction'])

                # Realistic Friction & Commission: 35 pts / 0.04% blended VIP0 rate
                friction_usd = max(trade['btc_size'] * 35.0, (trade['notional'] + trade['btc_size'] * exit_price) * 0.0002)

                net_trade_usd = (trade['realized_usd'] + rem_usd) - friction_usd
                net_trade_pts = round(net_trade_usd / trade['btc_size']) if trade['btc_size'] > 0 else 0

                balance += net_trade_usd
                total_trades += 1
                total_pts += net_trade_pts

                is_win = net_trade_usd > 0
                if is_win:
                    wins += 1
                    gross_profit_usd += net_trade_usd
                else:
                    losses += 1
                    gross_loss_usd += abs(net_trade_usd)

                # Drawdown tracking
                if balance > peak_balance:
                    peak_balance = balance
                dd_usd = peak_balance - balance
                dd_pct = (dd_usd / peak_balance * 100.0) if peak_balance > 0 else 0.0
                if dd_usd > max_dd_usd:
                    max_dd_usd = dd_usd
                if dd_pct > max_dd_pct:
                    max_dd_pct = dd_pct

                hours_held = bars_held * hours_per_candle
                trade_roi = (net_trade_usd / (trade['notional'] / QUANT_CONFIG['max_effective_leverage'])) * 100.0

                open_dt = datetime.fromtimestamp(trade['open_time'] / 1000.0, tz=timezone.utc)
                close_dt = datetime.fromtimestamp(cur_k.t / 1000.0, tz=timezone.utc)
                fmt = "%d/%m/%Y %H:%M"

                record = {
                    'id': total_trades,
                    'open_time': open_dt.strftime(fmt),
                    'close_time': close_dt.strftime(fmt),
                    'open_timestamp': trade['open_time'],
                    'close_timestamp': cur_k.t,
                    'direction': trade['direction'],
                    'entry': round(trade['entry'], 1),
                    'exit': round(exit_price, 1),
                    'tier': f"💎 A+ $40k" if trade['is_tier_a_plus'] else f"⚡ EST $20k",
                    'is_a_plus': trade['is_tier_a_plus'],
                    'notional': round(trade['notional'], 2),
                    'btc_size': round(trade['btc_size'], 4),
                    'bars_held': bars_held,
                    'hours_held': hours_held,
                    'net_pts': net_trade_pts,
                    'net_usd': round(net_trade_usd, 2),
                    'trade_roi': round(trade_roi, 1),
                    'balance': round(balance, 2),
                    'is_win': is_win,
                    'reason': exit_reason,
                    'score': trade['score']
                }
                trades_list.append(record)

                equity_curve.append({
                    'candle': i,
                    'time': cur_k.t,
                    'balance': round(balance, 2),
                    'trade_id': total_trades
                })

    # Summary Statistics
    win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0
    profit_factor = (gross_profit_usd / gross_loss_usd) if gross_loss_usd > 0 else (99.0 if gross_profit_usd > 0 else 0.0)
    net_profit_usd = balance - initial_bankroll
    roi_pct = (net_profit_usd / initial_bankroll * 100.0) if initial_bankroll > 0 else 0.0
    expectancy = (net_profit_usd / total_trades) if total_trades > 0 else 0.0
    avg_hold_hours = (sum(t['hours_held'] for t in trades_list) / len(trades_list)) if trades_list else 0.0

    return {
        'total_trades': total_trades,
        'wins': wins,
        'losses': losses,
        'win_rate': round(win_rate, 1),
        'roi_pct': round(roi_pct, 1),
        'net_profit_usd': round(net_profit_usd, 2),
        'initial_bankroll': initial_bankroll,
        'final_balance': round(balance, 2),
        'total_pts': total_pts,
        'profit_factor': round(profit_factor, 2),
        'max_dd_usd': round(max_dd_usd, 2),
        'max_dd_pct': round(max_dd_pct, 1),
        'expectancy_usd': round(expectancy, 2),
        'avg_hours_held': round(avg_hold_hours, 1),
        'timeframe': timeframe,
        'max_hold_hours': max_hold_hours,
        'days_tested': round((klines[-1].t - klines[0].t) / (86400.0 * 1000.0), 1),
        'candles_tested': len(klines),
        'equity_curve': equity_curve,
        'trades': trades_list
    }
