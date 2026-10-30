"""Studio-owned OHLCV replay and evidence adapter.

The package owns its decision core.  Studio owns the mechanical data-frame,
single-engine-run, and report serialization boundary so Cloud evidence has the
same provenance shape for every ordinary OHLCV Playbook.
"""

from decimal import Decimal
from pathlib import Path
import json

import pandas as pd
from getagent import backtest, data, runtime


_INTERVAL_MILLISECONDS = {
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}
_PAGE_LIMIT = 900
# The data API silently clamps any kline request to a 90-day window.
_MAX_WINDOW_MS = 90 * 24 * 60 * 60 * 1000
_MAX_PAGES = 512


def _plain(value):
    if isinstance(value, pd.DataFrame):
        return value.reset_index().to_dict("records")
    if isinstance(value, pd.Series):
        return value.reset_index().to_dict("records")
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    return value


def _report_rows(value):
    normalized = _plain(value)
    if normalized is None:
        return []
    if isinstance(normalized, list):
        return [row for row in normalized if isinstance(row, dict)]
    if isinstance(normalized, dict):
        return [normalized]
    return []


def _timestamp_series(frame):
    for name in ("timestamp", "time", "date", "datetime", "index"):
        if name not in frame.columns:
            continue
        values = frame[name]
        numeric = pd.to_numeric(values, errors="coerce")
        if numeric.notna().any():
            magnitude = float(numeric.dropna().abs().median())
            unit = "ns" if magnitude >= 1e17 else "us" if magnitude >= 1e14 else "ms" if magnitude >= 1e11 else "s"
            parsed = pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
        else:
            parsed = pd.to_datetime(values, utc=True, errors="coerce")
        if parsed.notna().any():
            return parsed
    raise RuntimeError("DataSDK OHLCV response has no parseable timestamp column")


def _frame(response):
    frame = data.to_dataframe(response)
    if frame.empty:
        raise RuntimeError("DataSDK returned no closed OHLCV bars")
    frame = frame.reset_index()
    frame["studio_timestamp"] = _timestamp_series(frame)
    required = ["open", "high", "low", "close", "volume"]
    missing = [name for name in required if name not in frame.columns]
    if missing:
        raise RuntimeError(f"DataSDK OHLCV response is missing: {', '.join(missing)}")
    for name in required:
        frame[name] = pd.to_numeric(frame[name], errors="coerce")
    frame = frame.dropna(subset=["studio_timestamp", *required])
    frame = frame.sort_values("studio_timestamp").drop_duplicates(
        subset=["studio_timestamp"], keep="last"
    )
    if frame.empty:
        raise RuntimeError("DataSDK returned no valid closed OHLCV bars")
    prepared = backtest.prepare_frame(frame, datetime_index="studio_timestamp")
    return prepared[required].copy()


def _spec_instruments(spec):
    rows = spec.get("instruments")
    if rows:
        return list(rows)
    single = spec.get("instrument")
    return [single] if single else []


def _execution_window(spec):
    execution = spec.get("execution") or {}
    raw_start = execution.get("start")
    raw_end = execution.get("end")
    if not raw_start or not raw_end:
        raise RuntimeError(
            "backtest.yaml must declare execution.start and execution.end"
        )
    start = pd.to_datetime(raw_start, utc=True, errors="raise")
    end = pd.to_datetime(raw_end, utc=True, errors="raise")
    if start is None or end is None or pd.isna(start) or pd.isna(end):
        raise RuntimeError(
            "backtest.yaml execution.start and execution.end must be valid timestamps"
        )
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    if start_ms >= end_ms:
        raise RuntimeError("backtest execution.start must be before execution.end")
    return start_ms, end_ms


def _fetch_pages(*, market_type, symbol, interval, start_ms, end_ms):
    step_ms = _INTERVAL_MILLISECONDS.get(interval)
    if step_ms is None:
        raise RuntimeError(f"Unsupported Studio granularity: {interval}")
    frames = []
    cursor = start_ms
    page_count = 0
    while cursor <= end_ms:
        page_count += 1
        if page_count > _MAX_PAGES:
            raise RuntimeError("Historical OHLCV window exceeds the bounded page budget")
        page_bars = min(_PAGE_LIMIT, _MAX_WINDOW_MS // step_ms)
        page_end = min(end_ms, cursor + (page_bars - 1) * step_ms)
        if "spot" in market_type:
            response = data.crypto.spot.kline(
                symbol=symbol,
                interval=interval,
                exchange="bitget",
                limit=_PAGE_LIMIT,
                start_time=cursor,
                end_time=page_end,
                closed_only=True,
            )
        else:
            response = data.crypto.futures.kline(
                symbol=symbol,
                interval=interval,
                exchange="bitget",
                limit=_PAGE_LIMIT,
                start_time=cursor,
                end_time=page_end,
                closed_only=True,
            )
        page = _frame(response)
        epoch_ms = (
            page.index - pd.Timestamp("1970-01-01", tz="UTC")
        ) // pd.Timedelta(milliseconds=1)
        page = page[
            (epoch_ms >= cursor)
            & (epoch_ms <= page_end)
        ]
        if not page.empty:
            frames.append(page)
        next_cursor = page_end + step_ms
        if next_cursor <= cursor:
            raise RuntimeError("Historical OHLCV pagination did not advance")
        cursor = next_cursor
    if not frames:
        raise RuntimeError("DataSDK returned no OHLCV bars in the execution window")
    combined = pd.concat(frames).sort_index()
    combined = combined[~combined.index.duplicated(keep="last")]
    if len(combined) < 2:
        raise RuntimeError("DataSDK returned fewer than two valid closed OHLCV bars")
    epochs = (
        combined.index - pd.Timestamp("1970-01-01", tz="UTC")
    ) // pd.Timedelta(milliseconds=1)
    expected = (int(epochs[-1]) - int(epochs[0])) // step_ms + 1
    if len(combined) < expected * 0.99:
        raise RuntimeError(
            f"DataSDK returned {len(combined)} of {expected} {interval} bars for {symbol}; refusing a backtest with missing history"
        )
    return combined


def _equity_points(value, data_start, data_end):
    rows = _report_rows(value)
    points = []
    for row in rows:
        timestamp = row.get("timestamp", row.get("index", row.get("time")))
        amount = row.get("value", row.get("equity", row.get("total")))
        if timestamp is not None and amount is not None:
            points.append([timestamp, amount])
    if len(points) == 2 and {
        str(points[0][0]).strip().lower(),
        str(points[1][0]).strip().lower(),
    } == {"start", "end"}:
        for point in points:
            point[0] = data_start if str(point[0]).strip().lower() == "start" else data_end
    normalized = []
    for timestamp, amount in points:
        parsed = pd.to_datetime(timestamp, utc=True, errors="coerce")
        numeric = pd.to_numeric(pd.Series([amount]), errors="coerce").iloc[0]
        if pd.isna(parsed) or pd.isna(numeric):
            continue
        normalized.append(
            {"timestamp": parsed.isoformat(), "value": float(numeric)}
        )
    return normalized


def run():
    manifest = json.loads(
        Path(__file__).resolve().with_name("manifest.json").read_text(
            encoding="utf-8"
        )
    )
    spec = runtime.backtest_spec
    granularity = manifest["paper_entry"]["granularity"]
    market_type = str(manifest.get("market_type") or "perpetual").lower()
    start_ms, end_ms = _execution_window(spec)
    frames = {}
    for instrument in _spec_instruments(spec):
        instrument_id = str(instrument.get("id") or "")
        raw_symbol = str(
            instrument.get("raw_symbol")
            or instrument_id.split(".", 1)[0]
        )
        if not instrument_id or not raw_symbol:
            raise RuntimeError("backtest instrument id/raw_symbol is missing")
        frames[instrument_id] = _fetch_pages(
            market_type=market_type,
            symbol=raw_symbol,
            interval=granularity,
            start_ms=start_ms,
            end_ms=end_ms,
        )
    if not frames:
        raise RuntimeError("runtime.backtest_spec contains no instruments")

    common_index = None
    for frame in frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    if common_index is None or len(common_index) < 2:
        raise RuntimeError("Declared instruments have fewer than two aligned OHLCV bars")
    common_index = common_index.sort_values()
    frames = {key: frame.loc[common_index].copy() for key, frame in frames.items()}
    data_start = pd.Timestamp(common_index[0]).isoformat()
    data_end = pd.Timestamp(common_index[-1]).isoformat()

    result = backtest.run(ohlcv_data=frames, spec=spec)
    raw_result = getattr(result, "raw", {}) or {}
    reports_source = raw_result.get("reports", {}) if isinstance(raw_result, dict) else {}
    curve = _equity_points(
        reports_source.get("equity_curve") if isinstance(reports_source, dict) else None,
        data_start,
        data_end,
    )
    if len(curve) < 2 and isinstance(reports_source, dict):
        curve = _equity_points(reports_source.get("account"), data_start, data_end)
    if len(curve) < 2:
        raise RuntimeError("Engine returned fewer than two real timestamped equity observations")

    report = _plain(raw_result)
    if not isinstance(report, dict):
        report = {}
    reports = report.get("reports")
    reports = reports if isinstance(reports, dict) else {}
    reports.pop("equity_curve", None)
    for name in ("orders", "fills", "positions", "account"):
        if isinstance(reports_source, dict) and name in reports_source:
            reports[name] = _report_rows(reports_source[name])
    report["reports"] = reports
    report["data_start"] = data_start
    report["data_end"] = data_end

    output = Path("output")
    output.mkdir(exist_ok=True)
    with (output / "backtest_report.json").open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, default=str)
    pd.DataFrame(curve).to_csv(output / "equity_curve.csv", index=False)

    runtime.emit_signal(
        action="hold",
        symbol=manifest["paper_entry"]["symbols"][0],
        confidence=0.0,
        metrics={
            "total_trades": int(getattr(result, "total_trades", 0) or 0),
            "data_start": data_start,
            "data_end": data_end,
            "symbols": manifest["paper_entry"]["symbols"],
        },
    )


def _live_rows(frame):
    rows = []
    for timestamp, row in frame.iterrows():
        item = row.to_dict()
        stamp = pd.Timestamp(timestamp).tz_convert("UTC")
        item["timestamp"] = stamp.isoformat()
        item["t"] = item["timestamp"]
        rows.append(item)
    return rows


def _live_position(trade, symbol):
    result = trade.contract.current_position(symbol=symbol)
    if not trade.is_success(result):
        raise RuntimeError(f"current_position failed for {symbol}: {result}")
    records = trade.helpers.contract_position_records(result, symbol=symbol)
    open_records = []
    for record in records:
        raw_size = (
            record.get("total")
            or record.get("size")
            or record.get("qty")
            or record.get("available")
            or "0"
        )
        if Decimal(str(raw_size)) != 0:
            open_records.append(record)
    if len(open_records) > 1:
        raise RuntimeError(f"ambiguous open position for {symbol}")
    if not open_records:
        return None
    record = open_records[0]
    side = str(
        record.get("hold_side")
        or record.get("holdSide")
        or record.get("pos_side")
        or record.get("posSide")
        or ""
    ).lower()
    if side not in {"long", "short"}:
        raise RuntimeError(f"unsupported position side for {symbol}: {side!r}")
    return {
        "symbol": symbol,
        "side": side,
        "qty": Decimal(str(raw_size)),
        "weight": 0.0,
    }


def _live_equity(trade):
    result = trade.account.total_value()
    if not trade.is_success(result):
        raise RuntimeError(f"account total_value failed: {result}")
    value = ((result.get("data") or {}).get("total_value_usd") or "").strip()
    if not value:
        raise RuntimeError("account total_value returned no total_value_usd")
    equity = Decimal(value)
    if equity <= 0:
        raise RuntimeError("account total_value is not positive")
    return equity


def _effective_live_weight(targets, max_gross):
    gross = sum(Decimal(str(target["weight"])) for target in targets)
    if gross <= Decimal(str(max_gross)) or gross <= 0:
        return {target["symbol"]: float(target["weight"]) for target in targets}
    scale = Decimal(str(max_gross)) / gross
    return {
        target["symbol"]: float(Decimal(str(target["weight"])) * scale)
        for target in targets
    }


def _execute_live_target(
    trade,
    symbol,
    side,
    target_qty,
    leverage,
    phase,
):
    current = _live_position(trade, symbol)
    target_qty = Decimal(str(target_qty))
    if target_qty <= 0:
        raise RuntimeError(f"target quantity is not positive for {symbol}")

    if phase == "reduce":
        if current is None:
            return
        if current["side"] != side:
            close_result = trade.contract.close_position(
                symbol=symbol,
                hold_side=current["side"],
            )
            if not trade.is_success(close_result):
                raise RuntimeError(
                    f"close_position failed for {symbol}: {close_result}"
                )
            if _live_position(trade, symbol) is not None:
                raise RuntimeError(f"close_position was not reconciled for {symbol}")
            return
        if current["qty"] <= target_qty:
            return
        reduction_qty = current["qty"] - target_qty
        close_result = trade.contract.place_order(
            symbol=symbol,
            side="sell" if side == "long" else "buy",
            order_type="market",
            qty=str(reduction_qty),
            pos_side=side,
            trade_side="close",
        )
        if not trade.is_success(close_result):
            raise RuntimeError(
                f"partial close failed for {symbol}: {close_result}"
            )
        reduced = _live_position(trade, symbol)
        if (
            reduced is None
            or reduced["side"] != side
            or reduced["qty"] != target_qty
        ):
            raise RuntimeError(
                f"partial close was not reconciled for {symbol}: "
                f"expected_qty={target_qty}, actual={reduced}"
            )
        return

    if phase != "open":
        raise ValueError(f"unsupported live target phase: {phase}")

    if current is not None and current["side"] != side:
        close_result = trade.contract.close_position(
            symbol=symbol,
            hold_side=current["side"],
        )
        if not trade.is_success(close_result):
            raise RuntimeError(f"close_position failed for {symbol}: {close_result}")
        if _live_position(trade, symbol) is not None:
            raise RuntimeError(f"close_position was not reconciled for {symbol}")

    current = _live_position(trade, symbol)
    if current is not None and current["qty"] > target_qty:
        raise RuntimeError(
            f"live position remains above target for {symbol}: "
            f"current_qty={current['qty']}, target_qty={target_qty}"
        )
    if current is not None and current["qty"] == target_qty:
        return
    open_qty = target_qty if current is None else target_qty - current["qty"]
    if side == "long":
        result = trade.contract.open_long_market(
            symbol=symbol,
            qty=str(open_qty),
            leverage=leverage,
        )
    else:
        result = trade.contract.open_short_market(
            symbol=symbol,
            qty=str(open_qty),
            leverage=leverage,
        )
    if not trade.is_success(result):
        raise RuntimeError(f"open_{side}_market failed for {symbol}: {result}")
    opened = _live_position(trade, symbol)
    if (
        opened is None
        or opened["side"] != side
        or opened["qty"] != target_qty
    ):
        raise RuntimeError(
            f"open_{side}_market was not reconciled for {symbol}: "
            f"expected_qty={target_qty}, actual={opened}"
        )


def run_live():
    from getagent import trade
    from .decision_core import decide

    manifest = runtime.manifest
    config = dict(manifest.get("strategy_config") or {})
    symbols = list(manifest.get("trading_symbols") or [])
    if not symbols:
        raise RuntimeError("manifest.trading_symbols is empty")
    support = trade.market.check_symbol_support(symbols)
    if not trade.is_success(support):
        raise RuntimeError(f"symbol support check failed: {support}")

    granularity = str((manifest.get("paper_entry") or {}).get("granularity") or "4h")
    slow_period = int(config.get("slow_period", 200))
    frames = {}
    bars = {}
    now = pd.Timestamp.now(tz="UTC")
    interval = pd.Timedelta(hours=4)
    for symbol in symbols:
        response = data.crypto.futures.kline(
            symbol=symbol,
            interval=granularity,
            exchange="bitget",
            limit=max(900, slow_period),
            closed_only=True,
        )
        frame = _frame(response)
        if len(frame) < slow_period:
            raise RuntimeError(f"insufficient closed bars for {symbol}")
        last_open = pd.Timestamp(frame.index[-1])
        if last_open.tzinfo is None:
            last_open = last_open.tz_localize("UTC")
        else:
            last_open = last_open.tz_convert("UTC")
        if now - (last_open + interval) > 2 * interval:
            raise RuntimeError(f"stale closed-bar data for {symbol}")
        frames[symbol] = frame
        bars[symbol] = _live_rows(frame.tail(slow_period))

    positions = []
    for symbol in symbols:
        position = _live_position(trade, symbol)
        if position is not None:
            positions.append(position)
    current_equity = _live_equity(trade)
    decision = decide(
        {
            "as_of": now.isoformat(),
            "granularity": granularity,
            "bars": bars,
            "positions": positions,
            "state": {},
            "config": config,
            "manifest": manifest,
            "market_type": manifest.get("market_type"),
            "symbols": symbols,
            "runtime": {
                "mode": "live",
                "evaluation_mode": runtime.evaluation_mode,
                "market_type": manifest.get("market_type"),
            },
        }
    )
    if not decision["positions"]:
        runtime.emit_signal(
            action="watch",
            symbol=symbols[0],
            confidence=0.0,
            metrics={"symbols": symbols, "reason": decision["note"]},
            meta={"execution_mode": "follow_trade"},
        )
        return

    weights = _effective_live_weight(
        decision["positions"],
        config.get("max_gross_leverage", 1.0),
    )
    desired = {target["symbol"]: target for target in decision["positions"]}
    leverage = int(config.get("leverage", 1))
    utilization = Decimal(str(config.get("utilization", 1.0)))
    target_plans = {}
    for symbol, target in desired.items():
        budget = (
            current_equity
            * Decimal(str(weights[symbol]))
            * utilization
        )
        try:
            target_plans[symbol] = trade.helpers.compute_qty(
                symbol=symbol,
                market="contract",
                budget_amount=budget,
                leverage=leverage,
            )
        except trade.TradeSDKValidationError as exc:
            runtime.emit_signal(
                action="watch",
                symbol=symbol,
                confidence=0.0,
                metrics={
                    "as_of": now.isoformat(),
                    "sizing_ok": False,
                    "notional_usdt": "0",
                    "min_open_notional_usdt": "",
                    "reason": str(exc),
                },
                meta={
                    "execution_mode": "follow_trade",
                    "entry_skipped": True,
                    "raw_error": str(exc),
                },
            )

    for symbol in symbols:
        target = desired.get(symbol)
        plan = target_plans.get(symbol)
        if target is None or plan is None:
            continue
        current = _live_position(trade, symbol)
        target_qty = Decimal(str(plan.qty))
        needs_reduction = (
            current is not None
            and (
                current["side"] != target["side"]
                or current["qty"] > target_qty
            )
        )
        if not needs_reduction:
            continue
        runtime.emit_signal_or_follow(
            action="close",
            symbol=symbol,
            confidence=0.7,
            metrics={
                "as_of": now.isoformat(),
                "target_weight": float(target["weight"]),
                "effective_weight": weights[symbol],
                "equity": str(current_equity),
                "target_qty": str(target_qty),
                "notional_usdt": str(plan.notional_value),
                "min_open_notional_usdt": str(plan.min_order_amount),
                "sizing_ok": True,
            },
            meta={
                "targets": [
                    {
                        "symbol": item["symbol"],
                        "side": item["side"],
                        "weight": weights[item["symbol"]],
                    }
                    for item in decision["positions"]
                ],
                "execution_mode": "follow_trade",
                "reconciliation_phase": "reduce_before_open",
            },
            execute_trade=lambda symbol=symbol, side=target["side"], target_qty=target_qty: _execute_live_target(
                trade,
                symbol,
                side,
                target_qty,
                leverage,
                "reduce",
            ),
        )

    for symbol in symbols:
        target = desired.get(symbol)
        plan = target_plans.get(symbol)
        if target is None or plan is None:
            continue
        current = _live_position(trade, symbol)
        target_qty = Decimal(str(plan.qty))
        action = (
            target["side"]
            if current is None
            or current["side"] != target["side"]
            or current["qty"] != target_qty
            else "hold"
        )
        runtime.emit_signal_or_follow(
            action=action,
            symbol=symbol,
            confidence=0.7 if action != "hold" else 0.0,
            metrics={
                "as_of": now.isoformat(),
                "target_weight": float(target["weight"]),
                "effective_weight": weights[symbol],
                "equity": str(current_equity),
                "target_qty": str(target_qty),
                "notional_usdt": str(plan.notional_value),
                "min_open_notional_usdt": str(plan.min_order_amount),
                "sizing_ok": True,
            },
            meta={
                "targets": [
                    {
                        "symbol": item["symbol"],
                        "side": item["side"],
                        "weight": weights[item["symbol"]],
                    }
                    for item in decision["positions"]
                ],
                "execution_mode": "follow_trade",
                "reconciliation_phase": "open_or_increase",
            },
            execute_trade=lambda symbol=symbol, side=target["side"], target_qty=target_qty: _execute_live_target(
                trade,
                symbol,
                side,
                target_qty,
                leverage,
                "open",
            ),
        )


if __name__ == "__main__":
    if runtime.is_historical():
        run()
    elif runtime.is_live():
        run_live()
    else:
        raise RuntimeError(
            f"unsupported evaluation_mode={runtime.evaluation_mode!r}"
        )
