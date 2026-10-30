# eth-moving-average-trend: research notes (2026-10-30)

## Data and method

- Bitget USDT-M perpetual 4-hour candles from `/api/v2/mix/market/history-candles`, common window 2021-07-23 to 2026-10-30 (`fetch.py`).
- Fees 0.06% taker on every resize. Bitget only serves about three months of funding history (`fund.py`), so funding is modelled at the base 0.01% per 8 hours, paid by longs and received by shorts.
- Designs were chosen on 2021-10 to 2023 and checked on 2024 to 2026-10, which played no part in the choice. A short list of reasoned variants was tested, not a parameter grid.
- `sim.py` reproduced the original platform run (2026-04-01 to 06-30): +20.5% and −15.6% max drawdown locally against +20.1% and −15.2% on the platform. That run's 11.9% "ending balance" return leaves out unrealized profit on positions still open at the end; the 20.1% includes it.

## Variants (CAGR / max drawdown / Sharpe, with funding)

| variant | 2021-10–2023 | 2024–2026-10 |
|---|---|---|
| original 50/200 long+short | 6.4% / −70.6% / 0.40 | 27.2% / −45.8% / 0.73 |
| long-only 50/200 | 11.4% / −63.1% / 0.47 | 48.7% / −46.0% / 1.06 |
| 20/100 long+short | 16.7% / −65.8% / 0.56 | −4.8% / −55.5% / 0.16 |
| 100/400 long+short | −19.6% / −83.4% / −0.10 | 2.8% / −58.3% / 0.31 |
| three-pair ensemble long+short | 0.7% / −77.9% / 0.32 | 19.9% / −47.6% / 0.61 |
| 50/200 with 2% band | 2.8% / −66.9% / 0.35 | 10.2% / −52.4% / 0.45 |
| **long-only 50/200, 40% vol target (chosen)** | **20.9% / −48.6% / 0.65** | **36.8% / −41.8% / 0.95** |
| equal-weight buy and hold | −2.5% / −82.8% / 0.31 | 18.2% / −64.4% / 0.58 |

The best design on the selection years (20/100) collapsed on the held-out years, which is why the split matters.

## Stress tests on the chosen design (`stress.py`)

- Double fees: Sharpe 0.65 → 0.59 (selection) and 0.95 → 0.89 (held out).
- Funding at 0.03% per 8 hours: 0.38 and 0.63. Still above the original, which is half short and pays no net funding in this model.
- Moving-average lengths: 60/240 holds up (0.55 / 0.85), but 40/160 (0.22 / 0.66) and 30/150 (0.06 / 0.60) are much worse. The edge depends on the conventional 50/200.
- 2022: −34.6%, where the original long/short made +10%. Long-only is a bet that crypto majors rise over time.

## Platform evidence

GetAgent backtest `pbrun-67d4d125d63d`, 2025-04-01 to 2026-10-29, margin budget 10,000 USDT, no funding:
+40.7% return, 40.6% max drawdown, Sharpe 0.98, 4,408 fills. The local simulator gives +40.7% and −40.4% for the same window. The original long/short design makes +7.1% with −46.4% there.

The platform's win rate and profit factor count every resize as a trade, so they do not describe the trend calls.

The platform's data source returned no 4-hour futures candles for a window starting 2023-11-26, so the platform evidence covers only the last 18 months.

## Cross-venue check (`kraken_check.py`)

The same simulator run on Kraken spot 4-hour candles (`XBTUSD`, `ETHUSD`, `SOLUSD`, `XRPUSD`, 2024-01-01 to
2025-12-31, supplied by the user) and on Bitget perps over the identical span, 200-bar warm-up, no funding:

| | Bitget perps | Kraken spot |
|---|---|---|
| this version | +188.1%, −33.2% max DD, Sharpe 1.45 | +186.0%, −32.7%, 1.44 |
| original long/short | +94.5%, −44.7%, 0.92 | +94.0%, −44.8%, 0.91 |

The result is not an artifact of Bitget's data. This span is inside the period already tested, so it adds no
new market history: the Kraken files that would cover the 2014–15 and 2018 bear markets were not supplied.

Run: `python3 kraken_check.py <folder with *_240.csv>` from a directory holding the `fetch.py` output.

## Package fixes

- `src/main.py` asked for 900 bars per page, which is 150 days at 4 hours; the data API silently clamps any request to 90 days. Pages are now at most 90 days, and the loader refuses a backtest when more than 1% of the expected bars are missing.
