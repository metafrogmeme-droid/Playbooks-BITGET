from copy import deepcopy
from math import sqrt
from statistics import mean, pstdev

# 4-hour bars: six per day.
_BARS_PER_YEAR = 6 * 365


def _annualized_volatility(closes, window):
    returns = [closes[i] / closes[i - 1] - 1.0 for i in range(len(closes) - window, len(closes))]
    return pstdev(returns) * sqrt(_BARS_PER_YEAR)


def decide(ctx):
    bars_by_symbol = ctx.get("bars") or {}
    config = ctx.get("config") or {}
    symbols = list(
        ctx.get("symbols")
        or config.get("trading_symbols")
        or ["BTCUSDT"]
    )
    fast_period = int(config.get("fast_period", 50))
    slow_period = int(config.get("slow_period", 200))
    target_weight = float(config.get("target_weight", 1.0))
    max_gross = float(config.get("max_gross_leverage", 1.0))
    allow_short = bool(config.get("allow_short", False))
    vol_target = float(config.get("vol_target", 0.40))
    vol_window = int(config.get("vol_window", 180))
    if fast_period <= 0 or slow_period <= fast_period:
        raise ValueError("fast_period must be positive and below slow_period")
    if target_weight <= 0 or target_weight > max_gross:
        raise ValueError("target_weight exceeds configured gross exposure")
    if vol_target <= 0 or vol_window <= 1:
        raise ValueError("vol_target must be positive and vol_window above one bar")
    needed = max(slow_period, vol_window + 1)

    positions = []
    state = deepcopy(ctx.get("state") or {})
    symbol_state = state.setdefault("symbols", {})
    for symbol in symbols:
        rows = list(bars_by_symbol.get(symbol) or [])
        if len(rows) < needed:
            return {
                "positions": [],
                "note": "Waiting for the closed-bar moving-average and volatility windows.",
                "state": state,
            }
        closes = [float(row["close"]) for row in rows]
        fast = mean(closes[-fast_period:])
        slow = mean(closes[-slow_period:])
        volatility = _annualized_volatility(closes, vol_window)
        # Scale each symbol down when it is more volatile than the target; never lever up.
        weight = target_weight * min(1.0, vol_target / volatility) if volatility > 0 else target_weight
        if fast > slow:
            side = "long"
        elif fast < slow and allow_short:
            side = "short"
        elif fast < slow:
            side = "flat"
        else:
            prior = next((p for p in (ctx.get("positions") or []) if p.get("symbol") == symbol), None)
            side = prior["side"] if prior else "flat"
        if side != "flat":
            positions.append({"symbol": symbol, "side": side, "weight": weight})
        symbol_state[symbol] = {
            "last_signal": side,
            "fast_average": fast,
            "slow_average": slow,
            "annualized_volatility": volatility,
            "weight": weight if side != "flat" else 0.0,
        }
    return {
        "positions": positions,
        "note": "Closed-bar 50/200 trend, long or flat, sized to a volatility target.",
        "state": state,
    }
