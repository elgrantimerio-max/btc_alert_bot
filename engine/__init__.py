"""
BTC Quant Terminal V6.5 - Quantitative Engine Package
Single Source of Truth for Trend Detection, Risk Sizing, and Volatility Targeting.
"""

from .quant_core import (
    Kline,
    calculate_atr,
    calculate_true_range,
    calculate_ema,
    calculate_vwap,
    calculate_choppiness,
    calculate_adx,
    calculate_ttm_squeeze,
    calculate_ichimoku,
    calculate_real_order_flow,
    calculate_orthogonal_factors,
    calculate_probabilistic_score,
    calculate_dynamic_targets,
    calculate_fixed_fractional_size,
    evaluate_signal,
    QUANT_CONFIG
)

__all__ = [
    'Kline',
    'calculate_atr',
    'calculate_true_range',
    'calculate_ema',
    'calculate_vwap',
    'calculate_choppiness',
    'calculate_adx',
    'calculate_ttm_squeeze',
    'calculate_ichimoku',
    'calculate_real_order_flow',
    'calculate_orthogonal_factors',
    'calculate_probabilistic_score',
    'calculate_dynamic_targets',
    'calculate_fixed_fractional_size',
    'evaluate_signal',
    'QUANT_CONFIG'
]
