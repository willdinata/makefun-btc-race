import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [SCRIPT_DIR, os.path.join(SCRIPT_DIR, "vendor")]

import makefun_bars


FAST = 15
SLOW = 50
TREND = 200
MOMENTUM_BARS = 60
MOMENTUM_MIN = 0.0035
TRAIL = 0.009
HARD_STOP = 0.02
COOLDOWN = 45
SIZE = 0.97
SLIP = 300


class StrategyState:
    def __init__(self):
        self.closes = []
        self.ema_fast = None
        self.ema_slow = None
        self.ema_trend = None
        self.slow_history = []
        self.entry_ref = None
        self.peak = None
        self.last_exit_seq = None

    @staticmethod
    def _update_ema(previous, close, period):
        if previous is None:
            return float(close)
        k = 2 / (period + 1)
        return k * close + (1 - k) * previous

    def record(self, close):
        self.closes.append(close)
        self.ema_fast = self._update_ema(self.ema_fast, close, FAST)
        self.ema_slow = self._update_ema(self.ema_slow, close, SLOW)
        self.ema_trend = self._update_ema(self.ema_trend, close, TREND)
        self.slow_history.append(self.ema_slow)


STRATEGY = StrategyState()


def _validated_order(state, order):
    try:
        state.to_orders([dict(order, client_id="validation")])
    except makefun_bars.OrderError:
        return []
    return [order]


def on_batch(state, batch):
    symbol = next(iter(state.symbols))
    close = state.close(symbol)
    if close is None:
        return []

    STRATEGY.record(close)

    holding = state.positions.get(symbol)
    qty = int(holding.qty) if holding is not None else 0
    if qty:
        STRATEGY.peak = close if STRATEGY.peak is None else max(STRATEGY.peak, close)
        if STRATEGY.entry_ref is None:
            STRATEGY.entry_ref = close
    else:
        STRATEGY.entry_ref = None
        STRATEGY.peak = None

    if state.warming_up:
        return []

    if qty:
        should_exit = (
            close < STRATEGY.peak * (1 - TRAIL)
            or STRATEGY.ema_fast < STRATEGY.ema_slow
            or close < STRATEGY.entry_ref * (1 - HARD_STOP)
        )
        if should_exit:
            order = {
                "side": "sell",
                "symbol": symbol,
                "qty": qty,
                "max_slippage_bps": SLIP,
            }
            orders = _validated_order(state, order)
            if orders:
                STRATEGY.last_exit_seq = state.seq
            return orders
        return []

    if (
        len(STRATEGY.closes) < TREND
        or state.seq > 1380
        or (
            STRATEGY.last_exit_seq is not None
            and state.seq <= STRATEGY.last_exit_seq + COOLDOWN
        )
        or len(STRATEGY.closes) <= MOMENTUM_BARS
        or len(STRATEGY.slow_history) <= 10
    ):
        return []

    prior_close = STRATEGY.closes[-(MOMENTUM_BARS + 1)]
    momentum_ok = close / prior_close - 1 > MOMENTUM_MIN
    if (
        STRATEGY.ema_fast > STRATEGY.ema_slow
        and close > STRATEGY.ema_trend
        and momentum_ok
        and STRATEGY.ema_slow > STRATEGY.slow_history[-11]
    ):
        order = {
            "side": "buy",
            "symbol": symbol,
            "notional_quote_units": int(state.cash * SIZE),
            "max_slippage_bps": SLIP,
        }
        orders = _validated_order(state, order)
        if orders:
            STRATEGY.entry_ref = close
            STRATEGY.peak = close
        return orders

    return []


makefun_bars.run(on_batch)
