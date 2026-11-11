# runeclaw-limit-scanner: 001's replay, reproduced and checked (2026-11-11)

Everything here was run on `metafrogmeme-droid/001` at `85a375210bd07fd5155f971bbd82ba7cd96d7622`, with its pinned `requirements-ci.txt`. Results are per trade, in basis points of notional. The 95% interval is 001's own (1.96 standard errors). Fees are 001's: maker 2 bp a side, unless a row says taker (6 bp on the entry). Funding is unpriced throughout, as in 001.

All of it is **post-hoc**. The development (to 2026-04-24) and hold-out (2026-04-24 to 2026-10-10) windows were read before. The forward rows below cover only 19.5 days and are an interim look; none of this can pass 001's pre-registered bar.

## 1. 001's measurement, reproduced

`scripts/limit_scanner_measure.py` on the frozen Bitget book (34 symbols, 2026-02-02 to 2026-10-10, no failed symbols):

| variant | development: n, mean (95% interval) | hold-out: n, mean (95% interval), PF |
|---|---|---|
| old scoring, touch fill, card fees (11 bp in, 6 bp out) | 114, −15.0 (−41.8 to +11.7) | 197, −11.9 (−29.3 to +5.6), 0.76 |
| fixed scoring, touch fill, maker fees | 231, +11.0 (−9.7 to +31.7) | 455, −9.5 (−21.7 to +2.7), 0.81 |
| **V0** realistic fill | 201, −3.2 (−25.9 to +19.5) | 396, −12.4 (−26.3 to +1.6), 0.78 |
| **V1** reclaim | 135, +40.3 (+15.2 to +65.3) | 243, +29.5 (+12.9 to +46.1), 1.85 |
| **V2** limit 0.25 ATR deeper | 154, +0.9 (−23.5 to +25.2) | 290, −16.7 (−32.0 to −1.3), 0.70 |
| **V3** reclaim, neutral on a 1–1 leader vote | 108, +42.6 (+13.2 to +72.1) | 191, +30.4 (+12.1 to +48.7), 1.90 |
| cancel on a 10 bp adverse close | 143, +32.5 (+7.1 to +57.9) | 253, +23.7 (+7.8 to +39.5), 1.68 |
| book imbalance filter | 0 | 0 (the frozen bars have no book) |

Only the variants that look at the fill bar's close are positive.

## 2. The reclaim edge is look-ahead

In `bot/backtest/limit_fill.py`, a reclaim fill needs the fill bar's low to pierce the limit by 5 bp **and the fill bar's close to be back above it** (for a long). `bot/core/limit_shadow.py::_open_position` then books the entry **at the limit price**. A live resting limit fills on the touch, before the close is known, so it cannot refuse the fills that pierce and keep falling. And a bot that waits for the close to confirm the reclaim cannot buy at the limit any more: by construction the close is above it.

`cancel on a 10 bp adverse close` has the same defect. It decides on the fill bar's close to cancel an order that, live, would already have filled.

`reclaim_check.py` reruns 001's simulator with one change: a reclaim entry is booked at the fill bar's close, the first price at which a bot that has seen the reclaim can trade.

| variant | development | hold-out | hold-out before fees |
|---|---|---|---|
| V1 as pre-registered | 135, +40.3 (+15.2 to +65.3) | 243, +29.5 (+12.9 to +46.1) | +33.5 |
| V1, enter at the close, taker | 136, −19.7 (−43.7 to +4.3) | 242, **−13.0** (−28.8 to +2.8) | −5.0 |
| V1, enter at the close, maker (optimistic) | 136, −15.7 (−39.7 to +8.3) | 242, −9.0 (−24.8 to +6.8) | −5.0 |
| V3 as pre-registered | 108, +42.6 (+13.2 to +72.1) | 191, +30.4 (+12.1 to +48.7) | +34.4 |
| V3, enter at the close, taker | 106, −19.5 (−48.7 to +9.7) | 189, **−12.4** (−29.9 to +5.1) | −4.4 |

The same trades lose about 5 bp before fees once the entry is a price a bot could get. V1 and V3's 33–34 bp before fees is the distance between the limit and the close, collected by knowing the close in advance.

## 3. Forward window, interim (fills after 2026-10-23, to 2026-11-11 12:00 UTC)

The frozen book was extended with `fetch_forward.py` (Bitget public candles; the overlap matches the frozen closes exactly).

| variant | n | mean (95% interval) | PF | verdict |
|---|---|---|---|---|
| V0 | 51 | −21.8 (−71.7 to +28.2) | 0.72 | inconclusive |
| V1 | 38 | +21.4 (−27.4 to +70.3) | 1.48 | inconclusive |
| V1, enter at the close, taker | 37 | −39.4 (−90.0 to +11.2) | 0.48 | (diagnostic) |
| V2 | 35 | −14.3 (−68.2 to +39.5) | 0.78 | inconclusive |
| V3 | 34 | +41.2 (−24.9 to +107.3) | 1.94 | inconclusive |
| V3, enter at the close, taker | 34 | −22.6 (−84.1 to +38.9) | 0.69 | (diagnostic) |

Every verdict is inconclusive: under 100 trades, and funding unpriced (001's trades record no exit time, so funding cannot be added to them as they stand).

At the trade rates seen so far, 100 forward trades exist around 2026-11-30 to 12-04 for V0, 12-13 to 12-31 for V1, 12-17 to 12-20 for V2, and 2026-12-19 to 2027-01-19 for V3.

## Conclusions

1. **No tradeable variant has a positive mean after costs on any window.** V0 and V2, the two that fill like a live resting limit, are negative on the hold-out, and V2's whole interval is below zero.
2. **V1 and V3 cannot be scored honestly by 001's simulator.** A forward pass for either would be produced by the fill model, not by the market. The pre-registration should drop them, or redefine them to enter at the reclaim close with taker fees, before the forward window is scored. That argument rests on the code, not on the numbers; but note that this amendment would now be made after the interim forward look above.
3. **The forward test still needs funding priced** before any verdict can be "survives". That needs exit times on trades in `limit_shadow.py`.
4. For the published Playbook: nothing here supports a 0.7.0. The recommendation in `PLAN.md` stands: stop offering 0.6.47 to 0.6.55, and do not change the signal.

## Reproduce

```bash
python3 -m venv venv001 && venv001/bin/pip install -r <001>/requirements-ci.txt
cd <001> && ../venv001/bin/python scripts/limit_scanner_measure.py > measure_frozen.json
python3 fetch_forward.py <001>/benchmark/limit_scanner_1h ./forward_1h
venv001/bin/python reclaim_check.py <001> ./forward_1h > reclaim_check.json   # about 7 minutes
```

Importing 001's skill registry writes `data/.exchange_secret.key` and `data/secrets_vault.enc` into the working directory. Delete them after a run.
