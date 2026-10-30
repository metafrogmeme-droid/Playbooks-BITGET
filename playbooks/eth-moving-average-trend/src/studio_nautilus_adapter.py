"""Studio-owned Nautilus adapter for a package-owned decision core.

This file is installed deterministically immediately before the platform's
local validation and upload gates.  Strategy authors own ``decision_core``;
Studio owns the repetitive engine/context/order reconciliation boundary.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from pathlib import Path
from copy import deepcopy
import json
import math

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy

from decision_core import decide as _studio_decide


_STUDIO_DATA_BUCKET_SECONDS = {}


def _studio_parse_timestamp(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(
            tzinfo=timezone.utc
        )
    if isinstance(value, bool) or value is None:
        raise ValueError("enriched data timestamp is invalid")
    numeric = None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("enriched data timestamp is not finite")
        numeric = Decimal(str(value))
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("enriched data timestamp is invalid")
        try:
            numeric = Decimal(text)
        except InvalidOperation:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("enriched data timestamp is not ISO-8601") from exc
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(
                tzinfo=timezone.utc
            )
    else:
        raise ValueError("enriched data timestamp is invalid")
    if not numeric.is_finite():
        raise ValueError("enriched data timestamp is not finite")
    magnitude = abs(numeric)
    if magnitude >= Decimal("1e17"):
        numeric /= Decimal(1_000_000_000)
    elif magnitude >= Decimal("1e14"):
        numeric /= Decimal(1_000_000)
    elif magnitude >= Decimal("1e11"):
        numeric /= Decimal(1_000)
    try:
        return datetime.fromtimestamp(float(numeric), tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("enriched data timestamp is out of range") from exc


def _studio_canonical_json(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _studio_load_data_fixture(manifest, package_root):
    paper = manifest.get("paper_entry") or {}
    requirements = paper.get("data_requirements") or []
    if not requirements:
        return {}
    fixture_name = str(paper.get("data_fixture") or "").strip()
    if not fixture_name:
        raise ValueError("enriched full packages require paper_entry.data_fixture")
    root = package_root.resolve()
    fixture_path = (root / fixture_name).resolve()
    try:
        fixture_path.relative_to(root)
    except ValueError as exc:
        raise ValueError("paper_entry.data_fixture must stay inside the package") from exc
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("paper_entry.data_fixture must map aliases to row lists")
    expected = {
        str(requirement.get("alias") or "").strip()
        for requirement in requirements
        if isinstance(requirement, dict)
    }
    if set(payload) != expected:
        raise ValueError("data_fixture aliases must exactly match data_requirements")
    return payload


def _studio_enriched_snapshot(requirements, raw_by_alias, as_of):
    """Build the same finite point-in-time input visible to Studio paper."""
    if not requirements:
        return {"data": {}, "data_meta": {}}
    cutoff = _studio_parse_timestamp(as_of)
    data = {}
    data_meta = {}
    for requirement in requirements:
        alias = str(requirement["alias"])
        rows = raw_by_alias.get(alias)
        if not isinstance(rows, list):
            raise ValueError(f"data_fixture alias {alias!r} must be a row list")
        timestamp_field = str(requirement["timestamp_field"])
        bucket_seconds = int(_STUDIO_DATA_BUCKET_SECONDS.get(alias, 0))
        accepted_by_canonical = {}
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(
                    f"data_fixture alias {alias!r} row {index} must be an object"
                )
            if timestamp_field not in row:
                raise ValueError(
                    f"data_fixture alias {alias!r} row {index} is missing "
                    f"timestamp_field {timestamp_field!r}"
                )
            stamp = _studio_parse_timestamp(row[timestamp_field])
            available_at = stamp + timedelta(seconds=bucket_seconds)
            if available_at > cutoff:
                continue
            canonical = _studio_canonical_json(row)
            accepted_by_canonical.setdefault(
                canonical,
                (stamp, available_at, canonical, row),
            )
        accepted = list(accepted_by_canonical.values())
        accepted.sort(key=lambda item: (item[0], item[2]))
        row_limit = int(requirement["row_limit"])
        window = accepted[-row_limit:]
        required_fields = [str(field) for field in requirement["required_fields"]]
        window_rows = []
        for index, (_, _, _, row) in enumerate(window):
            missing = [
                field
                for field in required_fields
                if field not in row or row[field] is None
            ]
            if missing:
                raise ValueError(
                    f"data_fixture alias {alias!r} row {index} is missing required "
                    f"fields: {', '.join(missing)}"
                )
            window_rows.append({field: row[field] for field in required_fields})
        min_rows = int(requirement["min_rows"])
        if len(window_rows) < min_rows:
            raise ValueError(
                f"data_fixture alias {alias!r} has {len(window_rows)} rows at "
                f"{cutoff.isoformat()}; requires at least {min_rows}"
            )
        oldest = window[0][0] if window else None
        newest = window[-1][0] if window else None
        newest_available_at = window[-1][1] if window else None
        max_age_seconds = int(requirement["max_age_seconds"])
        if (
            newest_available_at is not None
            and max_age_seconds
            and (cutoff - newest_available_at).total_seconds() > max_age_seconds
        ):
            raise ValueError(
                f"data_fixture alias {alias!r} is stale at {cutoff.isoformat()}"
            )
        data[alias] = window_rows
        data_meta[alias] = {
            "alias": alias,
            "endpoint": str(requirement["endpoint"]),
            "row_count": len(window_rows),
            "future_rows_dropped": 0,
            "first_timestamp": oldest.isoformat() if oldest else "",
            "last_timestamp": newest.isoformat() if newest else "",
        }
    return {"data": data, "data_meta": data_meta}


class StudioDecisionStrategyConfig(StrategyConfig):
    instrument_ids: tuple = ()
    bar_types: tuple = ()
    instrument_id: object = None
    bar_type: object = None
    max_gross_leverage: float = 1.0


class StudioDecisionStrategy(Strategy):
    def __init__(self, config):
        super().__init__(config)
        self._bars = {}
        self._seen_callbacks = {}
        self._last_watermark = None
        self._state = {}
        self._positions = []
        self._target_quantities = {}
        self._initial_equity = None
        self._manifest = json.loads(
            Path(__file__).resolve().with_name("manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self._data_requirements = deepcopy(
            self._manifest["paper_entry"].get("data_requirements") or []
        )
        self._data_fixture = _studio_load_data_fixture(
            self._manifest,
            Path(__file__).resolve().parent.parent,
        )

    def on_start(self):
        for bar_type in self.config.bar_types:
            self.subscribe_bars(bar_type)

    @staticmethod
    def _number(value):
        converter = getattr(value, "as_double", None)
        if callable(converter):
            return float(converter())
        return float(value)

    @staticmethod
    def _interval_delta(granularity):
        seconds = {
            "5m": 5 * 60,
            "15m": 15 * 60,
            "1h": 60 * 60,
            "4h": 4 * 60 * 60,
            "1d": 24 * 60 * 60,
        }.get(str(granularity).strip().lower())
        if seconds is None:
            raise ValueError(f"Unsupported Studio granularity: {granularity}")
        return timedelta(seconds=seconds)

    def _symbols(self):
        return list(self._manifest["paper_entry"]["symbols"])

    def _lookback(self):
        return int(self._manifest["paper_entry"]["lookback_bars"])

    def _find_id(self, symbol):
        for instrument_id in self.config.instrument_ids:
            if str(instrument_id).split(".", 1)[0] == symbol:
                return instrument_id
        return None

    def _instrument(self, symbol):
        instrument_id = self._find_id(symbol)
        return self.cache.instrument(instrument_id) if instrument_id is not None else None

    def _equity_values(self, instrument):
        venue_equity = self.portfolio.equity(instrument.id.venue)
        raw_value = venue_equity[instrument.quote_currency]
        current_equity = Decimal(str(self._number(raw_value)))
        if self._initial_equity is None:
            self._initial_equity = current_equity
        if self._initial_equity <= 0:
            return current_equity, Decimal("0")
        normalized_nav = current_equity / self._initial_equity * Decimal("100")
        return current_equity, normalized_nav

    @staticmethod
    def _position_quantity(position):
        signed = getattr(position, "signed_qty", None)
        if signed is not None:
            quantity = Decimal(str(signed))
            side = str(getattr(position, "side", "")).lower()
            if ("short" in side or "sell" in side) and quantity > 0:
                return -quantity
            if ("long" in side or "buy" in side) and quantity < 0:
                return quantity.copy_abs()
            return quantity
        quantity = Decimal(str(position.quantity)).copy_abs()
        side = str(getattr(position, "side", "")).lower()
        return -quantity if "short" in side or "sell" in side else quantity

    def _actual_quantity(self, instrument):
        return sum(
            (
                self._position_quantity(position)
                for position in self.cache.positions_open(
                    instrument_id=instrument.id
                )
            ),
            Decimal("0"),
        )

    @staticmethod
    def _signed_target_quantity(side, absolute_quantity):
        magnitude = Decimal(absolute_quantity).copy_abs()
        if side == "long":
            return magnitude
        if side == "short":
            return -magnitude
        raise ValueError(f"Unsupported target side: {side}")

    @staticmethod
    def _canonical_targets(targets):
        """Match the shared Paper/forward target normalization boundary."""
        if not isinstance(targets, list):
            raise ValueError("Decision positions must be a list")
        normalized = []
        for index, target in enumerate(targets):
            if not isinstance(target, dict):
                raise ValueError(
                    f"Decision positions[{index}] must be an object"
                )
            normalized.append(
                {
                    **target,
                    "symbol": str(target.get("symbol") or "").strip().upper(),
                    "side": str(target.get("side") or "long").strip().lower(),
                }
            )
        return normalized

    @staticmethod
    def _quantized_delta(target, current, increment):
        step = Decimal(str(increment))
        return (target - current).quantize(step, rounding=ROUND_HALF_EVEN)

    @staticmethod
    def _order_side(delta):
        if delta > 0:
            return OrderSide.BUY
        if delta < 0:
            return OrderSide.SELL
        return None

    def _submit_delta(self, instrument, delta):
        order_side = self._order_side(delta)
        if order_side is None:
            return
        quantity = Quantity(delta.copy_abs(), instrument.size_precision)
        order = self.order_factory.market(
            instrument_id=instrument.id,
            order_side=order_side,
            quantity=quantity,
        )
        self.submit_order(order)

    def _reconciled_positions(
        self,
        targets,
        bars,
        prior_quantities,
        target_quantities,
    ):
        prior_by_symbol = {row["symbol"]: row for row in self._positions}
        rows = []
        for target in targets:
            symbol = target["symbol"]
            desired = Decimal(str(target_quantities.get(symbol, Decimal("0"))))
            if desired == 0:
                continue
            prior = prior_by_symbol.get(symbol)
            prior_quantity = Decimal(
                str(prior_quantities.get(symbol, Decimal("0")))
            )
            close = Decimal(str(bars[symbol][-1]["close"]))
            same_side = prior is not None and prior.get("side") == target.get("side")
            if not same_side or prior_quantity == 0:
                entry_price = close
                hold_ticks = 0
            elif abs(desired) > abs(prior_quantity):
                added = abs(desired) - abs(prior_quantity)
                prior_entry = Decimal(str(prior["entry_price"]))
                entry_price = (
                    abs(prior_quantity) * prior_entry + added * close
                ) / abs(desired)
                hold_ticks = int(prior.get("hold_ticks", 0)) + 1
            else:
                entry_price = Decimal(str(prior["entry_price"]))
                hold_ticks = int(prior.get("hold_ticks", 0)) + 1
            rows.append(
                {
                    "symbol": symbol,
                    "side": target["side"],
                    "weight": float(target["weight"]),
                    "entry_price": float(entry_price),
                    "hold_ticks": hold_ticks,
                }
            )
        return rows

    def _execute_targets(self, targets, current_equity, bars):
        targets = self._canonical_targets(targets)
        symbols = self._symbols()
        gross_weight = sum(Decimal(str(row["weight"])) for row in targets)
        max_gross = Decimal(str(self.config.max_gross_leverage))
        if gross_weight > max_gross and gross_weight > 0:
            scale = max_gross / gross_weight
            targets = [
                {**row, "weight": float(Decimal(str(row["weight"])) * scale)}
                for row in targets
            ]
        wanted = {row["symbol"]: row for row in targets}
        prior_by_symbol = {row["symbol"]: row for row in self._positions}
        prior_quantities = {}
        target_quantities = {}
        executable_targets = []

        for symbol in symbols:
            instrument = self._instrument(symbol)
            if instrument is None:
                continue
            current = Decimal(
                str(self._target_quantities.get(symbol, Decimal("0")))
            )
            prior_quantities[symbol] = current
            target = wanted.get(symbol)
            if target is None:
                desired = Decimal("0")
            else:
                close = Decimal(str(bars[symbol][-1]["close"]))
                absolute = (
                    current_equity * Decimal(str(target["weight"])) / close
                )
                requested = self._signed_target_quantity(target["side"], absolute)
                delta = self._quantized_delta(
                    requested,
                    current,
                    instrument.size_increment,
                )
                desired = current + delta
                if desired == 0:
                    prior = prior_by_symbol.get(symbol)
                    if prior is not None and current != 0:
                        executable_targets.append(
                            {
                                "symbol": symbol,
                                "side": prior["side"],
                                "weight": prior["weight"],
                            }
                        )
                        target_quantities[symbol] = current
                        self._target_quantities[symbol] = current
                    elif current == 0:
                        raise ValueError(
                            f"Target for {symbol} is smaller than one executable lot"
                        )
                    continue
            delta = self._quantized_delta(
                desired,
                current,
                instrument.size_increment,
            )
            self._submit_delta(instrument, delta)
            target_quantities[symbol] = desired
            self._target_quantities[symbol] = desired
            if target is not None:
                executable_targets.append(target)

        self._positions = self._reconciled_positions(
            executable_targets,
            bars,
            prior_quantities,
            target_quantities,
        )

    def on_bar(self, bar: Bar):
        instrument_id = bar.bar_type.instrument_id
        symbol = str(instrument_id).split(".", 1)[0]
        if symbol not in self._symbols():
            return
        watermark = int(bar.ts_event)
        if self._seen_callbacks.get(symbol) == watermark:
            return
        self._seen_callbacks[symbol] = watermark

        close_at = datetime.fromtimestamp(
            watermark / 1_000_000_000.0,
            tz=timezone.utc,
        )
        candle_at = close_at - self._interval_delta(
            self._manifest["paper_entry"]["granularity"]
        )
        row = {
            "t": candle_at.isoformat(),
            "timestamp": candle_at.isoformat(),
            "open": self._number(bar.open),
            "high": self._number(bar.high),
            "low": self._number(bar.low),
            "close": self._number(bar.close),
            "volume": self._number(bar.volume),
        }
        rows = self._bars.setdefault(symbol, [])
        rows.append(row)
        rows.sort(key=lambda item: item["timestamp"])
        lookback = self._lookback()
        self._bars[symbol] = rows[-lookback:]

        symbols = self._symbols()
        if any(len(self._bars.get(item, [])) < lookback for item in symbols):
            return
        if any(
            self._bars[item][-1]["timestamp"] != row["timestamp"]
            for item in symbols
        ):
            return
        if self._last_watermark == watermark:
            return
        self._last_watermark = watermark

        account_instrument = self._instrument(symbol)
        if account_instrument is None:
            return
        current_equity, normalized_nav = self._equity_values(account_instrument)
        if current_equity <= 0 or normalized_nav <= 0:
            raise RuntimeError("Nautilus account equity is unavailable")
        enriched = _studio_enriched_snapshot(
            self._data_requirements,
            self._data_fixture,
            close_at,
        )

        ctx = {
            "as_of": close_at.isoformat(),
            "granularity": self._manifest["paper_entry"]["granularity"],
            "bars": {
                item: deepcopy(self._bars[item][-lookback:]) for item in symbols
            },
            "data": enriched["data"],
            "data_meta": enriched["data_meta"],
            "positions": deepcopy(self._positions),
            "nav": float(normalized_nav),
            "state": deepcopy(self._state),
            "config": deepcopy(self._manifest["strategy_config"]),
            "manifest": deepcopy(self._manifest),
            "market_type": self._manifest["market_type"],
            "symbols": list(symbols),
            "runtime": {
                "mode": "decision",
                "evaluation_mode": "closed_bar",
                "market_type": self._manifest["market_type"],
            },
        }
        decision = _studio_decide(ctx)
        self._state = json.loads(json.dumps(decision["state"]))
        self._execute_targets(decision["positions"], current_equity, ctx["bars"])

    def on_stop(self):
        return None
