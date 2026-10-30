# Crypto Majors Moving-Average Trend

## 策略 / Strategy

这是一个运行在 Bitget BTCUSDT、ETHUSDT、SOLUSDT 和 XRPUSDT USDT 永续合约上的 4 小时趋势跟随策略。策略对每个合约独立计算已完成 K 线的 50 根与 200 根收盘价简单移动平均线。短周期平均线高于长周期平均线时持有多头；低于时该合约空仓。策略不开空单。

A 4-hour trend-following strategy on the Bitget BTCUSDT, ETHUSDT, SOLUSDT and XRPUSDT USDT perpetuals. For each market independently it compares the 50-bar and 200-bar simple moving averages of completed closes. Above: hold long. Below: hold nothing. It never shorts.

## 开仓 / Entry

当 50 根均线上穿 200 根均线时开多。每个合约的仓位权重 = 目标敞口 × min(1, 40% / 该合约过去 180 根 K 线的年化波动率)，只缩小、不放大。多个合约同时持仓时，组合总敞口上限为 1 倍 margin budget，在各合约之间分配。每个 4 小时决策点按最新价格和波动率调整仓位。

A long opens when the 50-bar average is above the 200-bar average. Each market's weight is target exposure × min(1, 40% ÷ its annualized realized volatility over the last 180 bars), so volatile markets are sized down and none is levered up. When several markets are long, the 1× gross cap on the margin budget is shared between them. Positions are resized at each 4-hour decision.

## 平仓 / Exit

没有独立止盈或止损。当 50 根均线跌破 200 根均线时平掉该合约多头并保持空仓，直到趋势重新向上。

There is no separate take-profit or stop-loss. A long closes when the 50-bar average falls below the 200-bar average, and the market stays flat until the trend turns up again.

可调配置为目标敞口（0.1–1.0）和 margin budget。降低目标敞口会按比例降低收益和回撤。均线周期、波动率目标、4 小时粒度和这四个市场是策略定义。

Configurable: target exposure (0.1–1.0) and margin budget. Lowering target exposure scales returns and drawdowns down proportionally. The moving-average lengths, volatility target, 4-hour granularity and the four markets are part of the strategy definition.

## 指标与结果 / Metrics

研究使用 Bitget 4 小时 K 线（2021-07 至 2026-10），手续费 0.06%，资金费按每 8 小时 0.01%（多头支付）估算。参数在 2021-10 至 2023 年数据上选择，并在未参与选择的 2024 至 2026-10 数据上检验。

Research used Bitget 4-hour candles from 2021-07 to 2026-10, 0.06% taker fees and funding modelled at 0.01% per 8 hours paid by longs. The design was chosen on 2021-10 to 2023 data and checked on 2024 to 2026-10 data that played no part in choosing it. Figures at full (1.0) target exposure:

| | Selection 2021-10–2023 | Held-out 2024–2026-10 |
|---|---|---|
| This version: CAGR / max drawdown / Sharpe | 20.9% / −48.6% / 0.65 | 36.8% / −41.8% / 0.95 |
| Previous long/short version | 6.4% / −70.6% / 0.40 | 27.2% / −45.8% / 0.73 |
| Equal-weight buy and hold | −2.5% / −82.8% / 0.31 | 18.2% / −64.4% / 0.58 |

请以平台卡片中的真实 Bitget/GetAgent 回测证据为准。策略收益率以 margin budget 为分母；账户收益率以起始余额为分母，并且应包含未平仓持仓的浮动盈亏。

The platform's own Bitget/GetAgent backtest evidence takes precedence over these research figures. Strategy return uses the margin budget as its denominator; account return uses the starting balance and should include unrealized profit on open positions.

## 风险 / Risk

- 只做多：依赖主流币长期上涨，下跌市场不能获利。2022 年研究回撤约 −35%（原多空版本当年为 +10%）。Long-only: it relies on crypto majors rising over time and cannot profit in falling markets. In 2022 the research run lost about 35%, where the old long/short version made about 10%.
- 资金费：牛市资金费偏高时成本显著；按每 8 小时 0.03% 估算，夏普比率降至约 0.5。Funding: costly in heated bull markets; at 0.03% per 8 hours the research Sharpe falls to about 0.5.
- 参数敏感：较短的 30/150 或 40/160 均线历史表现明显更差。Parameter sensitivity: shorter pairs such as 30/150 and 40/160 did much worse historically.
- 均线滞后、震荡行情反复进出、四个合约高度相关、跳空、滑点和清算机制都可能使实盘不同于回测。历史结果不代表未来表现。Lagging averages, whipsaw in sideways markets, high correlation between the four markets, gaps, slippage and liquidation mechanics can all make live results differ from backtests. Past results do not predict future returns.
