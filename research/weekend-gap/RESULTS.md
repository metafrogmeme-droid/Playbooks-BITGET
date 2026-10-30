# Weekend Event Agent, Step 0: does weekend information get priced late?

Date: 2026-10-30. Thesis tested (from the RUNECLAW Bitget hackathon kit): Bitget US-stock USDT-M perps trade
through the weekend while NYSE is closed; weekend information is only partly priced before the Monday cash
open, so an agent can trade it and be flat before 09:30 ET.

## Data

- Universe: the 30 most liquid US stock/ETF perps by 24-hour volume on 2026-10-30 (`universe_top30.txt`),
  from `/api/v2/mix/market/contracts` (`isRwa = YES`). All charge 0.06% taker / 0.02% maker and fund every 8 h.
- 15-minute candles from `/api/v2/mix/market/history-candles` (`fetch15.py`). The oldest series start
  2025-08-19; many start in 2026. Up to 52 regular weekends; weekends touching an NYSE holiday are dropped.
- Weekend trading is real but thin: 10–16% of volume, and about a third of weekend 15-minute bars do not change price.
- Costs: 12 bp round-trip taker fees, plus spread scenarios of 2, 10 and 20 bp. Spreads were sampled once,
  on a weekday off-hours (0.1–5 bp for most names); weekend spreads were not observed and may be wider.
  Funding paid by longs: 0.4–1.3 bp per 8 h on NVDA, QQQ, TSLA and MSTR over Aug–Oct 2026.
- Every statistic averages across symbols within a weekend first, then across weekends, because the
  symbols move together. `t` is over weekends, not over symbol-weekends.

## Results

**Continuation (the thesis) fails.** Signal = the perp's move since Friday's close; trade in that direction;
flat by 09:15 Monday (kit rule) or held through the open (`weekend_gap.py`):

| test | slope | gross / trade | t |
|---|---|---|---|
| A  Fri close→Sat noon, trade Sat noon→Mon 09:15 | −0.75 | −30.7 bp | −1.9 |
| B  Fri close→Sun 20:00, trade Sun 20:00→Mon 09:15 | −0.20 | −16.5 bp | −1.3 |
| C  Fri close→Mon 09:15, trade through the open to 10:30 | −0.09 | −15.9 bp | −1.2 |
| D  Fri close→Mon 09:15, trade to Monday 16:00 | −0.08 | −10.9 bp | −0.6 |

QQQ-hedged versions are no better. Weekend moves do not continue; if anything they partly reverse.

**The reversal is not a usable edge either** (`fade_check.py`). Fading the Saturday move from Sat 13:00
(one hour after the signal, so one noisy print cannot cause it) to Mon 09:15 grosses +30.5 bp, t = 1.9, but:

- first half of weekends +2.7 bp, second half +58.2 bp;
- all of it comes from buying Saturday dips (+55.8 bp); shorting Saturday rallies loses (−32.4 bp);
- simply being long every weekend from Sat 13:00 earns +52.4 bp with no signal at all;
- without the 3 best weekends it is +13 bp gross, below costs.

**What the data does show is a weekend drift up** (`segments.py`):

| segment | mean | t |
|---|---|---|
| weekend Fri 16:00→Mon 09:15 (66 h) | +46 bp | 2.2 |
| of which Sun 20:00→Mon 09:15 | +37 bp | 2.0 |
| weekday night 16:00→09:15 | +11 bp | 1.2 |
| weekday cash session 09:30→16:00 | −5 bp | −0.5 |

Per hour, weekends and weekday nights drift about the same (~0.7 bp/h) while the cash session does not:
this looks like the documented overnight-return effect in US equities, not a weekend-news effect.

`sunday_drift.py`, always long Sun 20:00→Mon 09:15, net of fees and about 2 funding stamps:

| | weekends | gross | t | net @ 2 / 10 / 20 bp spread |
|---|---|---|---|---|
| all | 51 | +36.6 bp | 2.0 | +21 / +13 / +3 bp |
| first half | 25 | +47.1 bp | 2.0 | +32 / +24 / +14 bp |
| second half | 26 | +26.6 bp | 0.9 | +11 / +3 / −7 bp |

It is full market beta (worst weekend −224 bp), from one mostly rising 14-month period, and t ≈ 2 after
looking at several segments is not significant once that search is accounted for.

## Verdict

1. **The weekend-news continuation thesis is not supported by price data.** Kit rule 4 applies: say so.
2. **No price-only weekend signal survives costs.** The one positive candidate, a Sunday-night long, is weak,
   unhedged beta, and survives costs only if weekend spreads are tight.
3. **This test cannot measure news skill.** It uses no news. And an LLM cannot be backtested on 2025–2026
   headlines: a model whose training data includes those events already knows how they ended. The only
   clean test of the LLM's judgement is forward paper trading.

## Next-best design to test forward

Make the mechanical Sunday-night long the **baseline**, and let the LLM decide per name and per weekend
whether to take it, skip it, or reverse it on the weekend's news. Paper-trade both side by side on Bitget
Demo for the kit's 14+ days. The LLM earns its place only if it beats the baseline net of costs, which is
a claim judges can check from the logs. Before that, measure actual weekend spreads on Demo to settle
whether even the baseline covers costs.

## Reproduce

```bash
python3 fetch15.py NVDAUSDT   # once per symbol in universe_top30.txt
python3 weekend_gap.py 0.0002
python3 fade_check.py
python3 segments.py
python3 sunday_drift.py
```
