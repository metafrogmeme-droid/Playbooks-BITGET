# runeclaw-limit-scanner: findings and optimization plan (2026-11-11)

## The Playbook

`8836b3b0-72ff-46de-bef0-dde80e38a9f6` is **RUNECLAW Limit Entry Scanner v0.6.47**, published, strategy `e977214c-86e5-405b-be0b-d5bad50b97c8`. It is not the latest version: 0.6.48 to 0.6.55 are also published, and three drafts exist (`4eb425d3` kept, `5072428d` and `7f89096d` already on the delete list in `docs/draft_cleanup_checklist.md`).

The package source is not in this repository. Everything below comes from the official evidence the platform publishes for each version (orders, fills, positions, equity curve), downloaded with `fetch.py` and broken down with `analyze.py`.

## Published evidence

All versions replay the same 6-week window, 2026-07-04 to 2026-08-15, on 1-hour bars, with a 1,000 USDT account and 28 crypto perpetuals.

| version | margin budget | return | max drawdown | trades | positions |
|---|---|---|---|---|---|
| 0.6.47 | 100 | −6.92% | 4.52% | 235 | 99 |
| 0.6.48 | 150 | −0.46% | 30.15% | 235 | 99 |
| 0.6.49 | 150 | +1.04% | 50.36% | 235 | 99 |
| 0.6.50–0.6.52 | 150 | +1.23% | 50.22% | 232 | 98 |
| 0.6.53 | 150 | +1.27% | 50.22% | 234 | 99 |
| 0.6.55 | 150 | +1.07% | 50.22% | 234 | 99 |

0.6.47 and 0.6.55 share 98 of their 99 positions. The later versions changed sizing and reporting, not the signal. 0.6.55 sizes the alts about 2.5 times larger than 0.6.47 but ETHUSDT only about 1.6 times, so weight moved towards the alts. Its +16.03 USDT net rests on 11 trades: HYPEUSDT, SHIBUSDT, ADAUSDT and NEARUSDT make +103.99 together, and the other 88 trades lose 87.96.

## Diagnosis (v0.6.47)

1. **Fees are larger than the edge.** Gross edge is 10.1 bp per trade and the taker round trip costs 12.0 bp. Gross PnL is +37.01 USDT, fees are 43.93, so net is −6.92.
2. **No order is a limit order.** All 235 orders are `MARKET` / `IOC` / `TAKER`, although the product is called a limit entry scanner and its description says it places pullback limit orders.
3. **The long side has no edge.** Longs make 0.7 bp gross over 39 trades (net −25.28). Shorts make 24.9 bp over 60 trades (net +18.35).
4. **Two symbols are 83% of the trades, and both lose.**
   - ETHUSDT: 30 trades at about 1,000 USDT notional each, 3.5 bp gross edge, 34.02 of the 43.93 USDT in fees.
   - LABUSDT: 52 trades, −48 bp gross. It produced the three worst trades (−50.7%, −19.0% and −17.1% price moves) and today trades about 0.3M USDT a day on Bitget, the least liquid of the 28 symbols along with MUSDT.
5. **Sizing ignores the margin budget.** Entry notional reaches 1,011 USDT against a 100 USDT margin budget (10.1×). The 46.77 USDT drawdown is 46.8% of the budget. 0.6.55 goes up to 1,520 USDT against 150.
6. **The headline metrics are wrong.**
   - 0.6.47 shows return on the margin-budget basis (−6.92%) but drawdown on the account basis (4.52%; it is 46.8% on the budget).
   - The profit factor of 1.77 and win rate of 56.6% are computed from unsized price returns before fees. On net PnL they are 0.97 and 55.6%.
7. **The universe does not match the description.** 20 of the 28 symbols never traded and at most 2 positions were open at once. The description promises RWA US-stock and precious-metal perpetuals gated by QQQ and gold, but every listed symbol is crypto. Those markets do exist on Bitget: QQQUSDT, SPYUSDT, XAUUSDT, XAGUSDT, NVDAUSDT, TSLAUSDT and AAPLUSDT are `normal` with `isRwa: YES`.
8. **Holds of 4 to 12 hours lose.** 14 trades, −43.9 bp gross (0.6.55: −43.0 bp). Holds of up to 4 hours make 11–16 bp gross.
9. **The evidence is thin and stale.** The window is 6 weeks long, ended three months ago, and contains 99 positions, most of them in two symbols. No conclusion below should be acted on without a longer replay.
10. **Live and backtest may differ.** The tags say `orderbook` and `vwap`. Order-book features cannot be replayed from 1-hour bars, and `data_requirements.required_bar_fields` is empty. If the live code uses the book, the backtest is not testing the live strategy.

## What-ifs on the same trades

These re-price the 99 positions of 0.6.47. They are in-sample, assume every limit order fills, and only rank where to look first.

| scenario | trades | net USDT | cost | profit factor |
|---|---|---|---|---|
| A: as run (taker in, taker out) | 99 | −6.92 | 12.0 bp | 0.97 |
| B: maker entry, taker exit | 99 | +7.73 | 8.0 bp | 1.04 |
| C: maker entry and exit | 99 | +22.36 | 4.0 bp | 1.11 |
| D: shorts only | 60 | +18.35 | 12.0 bp | 1.21 |
| E: without ETHUSDT | 69 | +17.18 | 12.0 bp | 1.16 |
| F: without LABUSDT | 47 | +12.05 | 12.0 bp | 1.09 |
| G: B + shorts only | 60 | +24.03 | 8.0 bp | 1.29 |

## Plan

### Phase 0: prerequisites

- Put the package source in `playbooks/runeclaw-limit-scanner/`, so changes can be reviewed and versioned like `eth-moving-average-trend`.
- Extend the replay to at least 12 months, fetching 1-hour klines in 90-day chunks, for example 2025-08-01 to 2026-11-01. Choose changes on the first 8 months and check them on the last 4, which play no part in the choice.
- Rerun 0.6.55 unchanged on that window as the baseline every change is compared against.

### Phase 1: correct the reporting (no signal change)

- In `main_backtest.py`, compute profit factor and win rate from net realized PnL per position, after fees.
- Report return and drawdown on the same basis (margin budget), and overwrite `raw["net_pnl"]` and `raw["total_return_pct"]` as the backtest output contract requires.
- Add per-side and per-symbol breakdowns to `backtest_report.json`.

### Phase 2: cut costs (largest expected effect)

- **Real limit entries.** Place post-only limit orders at the pullback price, expire them after 1–2 bars and cancel unfilled ones. Take profit with a limit order. Stops stay stop-market. The target is 6–8 bp round trip instead of 12.
  - First confirm that the platform's Nautilus fill model fills `LIMIT` orders on bars as `MAKER`.
  - Report the fill rate, and compare the outcomes of filled and missed signals to measure adverse selection.
- **Minimum expected move.** Skip a signal when the expected move (for example a target based on ATR(14)) is less than 3× the round-trip cost. This mainly removes the ETH 1-hour scalps that make 3.5 bp gross.
- **No same-bar round trips.** One ETH position opened and closed in the same bar and only paid fees.

### Phase 3: risk and sizing

- **Size from risk, not from the account.** Risk 0.5–1% of the margin budget per trade, set qty as risk divided by stop distance, and cap notional per position and in total at margin budget × a leverage cap (for example 3×).
- **A hard stop on every position**, placed on the exchange at entry, not checked only on the hourly close. The −50.7% LABUSDT short shows that no effective stop exists today.
- **A per-trade loss cap in USDT** as a backstop.

### Phase 4: universe and signal

- **Liquidity and volatility filter.** Require a minimum 24-hour turnover (for example 20M USDT) and a maximum ATR%. This drops LABUSDT, MUSDT and SEIUSDT; until the filter exists, remove LABUSDT from the list.
- **Long side.** Require a stronger regime (for example BTC above its daily 200 moving average) or disable longs. Decide on the held-out months only: 39 longs in 6 weeks are not enough to prove that longs fail.
- **Time stop.** Test a 4-hour maximum hold against the current 12 hours.
- **Description.** For v0.7.0, remove the RWA and metals claim. Add QQQUSDT, XAUUSDT and the others as a separate experiment, after a kline replay probe for each and with their own regime leaders.
- **Never-traded symbols.** Remove those that still never trade on the 12-month window.

### Phase 5: release

- Publish one version, 0.7.0, only when the held-out window meets the acceptance criteria below.
- On the GetAgent page, deprecate 0.6.47 to 0.6.54 so that new subscribers do not land on a version showing −6.92%. The control-plane API has no deprecate or delete call for this.
- Delete drafts `5072428d` and `7f89096d`.

### Acceptance criteria (held-out months)

- Profit factor on net PnL of at least 1.2, from at least 150 positions.
- No single symbol contributes more than 40% of net PnL.
- Drawdown on the margin-budget basis of no more than 25%.
- Still profitable with fees doubled.
- Limit-entry fill rate reported, and filled trades not worse than missed ones by more than the fee saving.

## Reproduce

```bash
cd research/runeclaw-limit-scanner
BITGET_API_KEY=... python3 fetch.py      # writes pb_<version>.json (git-ignored)
python3 analyze.py pb_0.6.47.json
```
