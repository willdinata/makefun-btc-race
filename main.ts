import { runBars, type BarsState } from './vendor/makefun-bars.ts';

const FAST = 15;
const SLOW = 50;
const TREND = 150;
const MOMENTUM_BARS = 60;
const MOMENTUM_MIN = 0.0035;
const TRAIL = 0.02;
const HARD_STOP = 0.02;
const COOLDOWN = 120;
const MAX_ENTRIES = 2;
const LOSS_LOCKOUT = 1;
const SIZE_NUM = 97;
const SIZE_DEN = 100;
const SLIP = 300;
const LAST_ENTRY_SEQ = 1380;

const closes: number[] = [];
const slowEmaHistory: number[] = [];
let emaFast: number | null = null;
let emaSlow: number | null = null;
let emaTrend: number | null = null;
let entryRef: number | null = null;
let peak: number | null = null;
let cooldownBarsLeft = 0;
let entries = 0;
let losingExits = 0;

function updateEma(previous: number | null, close: number, period: number): number {
  if (previous === null) return close;
  const k = 2 / (period + 1);
  return k * close + (1 - k) * previous;
}

runBars({
  onBatch(state: BarsState) {
    try {
      if (cooldownBarsLeft > 0) cooldownBarsLeft -= 1;

      const symbol = state.symbols.keys().next().value;
      if (symbol === undefined) return [];

      const closeUnits = state.close(symbol);
      if (closeUnits === null) return [];

      const close = Number(closeUnits);
      closes.push(close);
      emaFast = updateEma(emaFast, close, FAST);
      emaSlow = updateEma(emaSlow, close, SLOW);
      emaTrend = updateEma(emaTrend, close, TREND);
      slowEmaHistory.push(emaSlow);

      const position = state.positions.get(symbol);
      if (position !== undefined && position.qty > 0n) {
        peak = peak === null ? close : Math.max(peak, close);
        entryRef ??= close;

        if (
          close < peak * (1 - TRAIL) ||
          emaFast < emaSlow ||
          close < entryRef * (1 - HARD_STOP)
        ) {
          cooldownBarsLeft = COOLDOWN;
          if (close < entryRef) losingExits += 1;
          return [{
            side: 'sell',
            symbol,
            qty: position.qty,
            max_slippage_bps: SLIP,
          }];
        }
        return [];
      }

      entryRef = null;
      peak = null;

      if (
        state.warmingUp ||
        entries >= MAX_ENTRIES ||
        losingExits >= LOSS_LOCKOUT ||
        closes.length < TREND ||
        cooldownBarsLeft !== 0 ||
        state.seq > LAST_ENTRY_SEQ ||
        closes.length <= MOMENTUM_BARS ||
        slowEmaHistory.length <= 10
      ) {
        return [];
      }

      const momentum = close / closes[closes.length - MOMENTUM_BARS - 1] - 1;
      if (
        emaFast > emaSlow &&
        close > emaTrend &&
        momentum > MOMENTUM_MIN &&
        emaSlow > slowEmaHistory[slowEmaHistory.length - 11]
      ) {
        const notional = (state.cash * BigInt(SIZE_NUM)) / BigInt(SIZE_DEN);
        if (notional >= 1_000_000n) {
          entryRef = close;
          peak = close;
          entries += 1;
          return [{
            side: 'buy',
            symbol,
            notional_quote_units: notional,
            max_slippage_bps: SLIP,
          }];
        }
      }

      return [];
    } catch {
      return [];
    }
  },
});
