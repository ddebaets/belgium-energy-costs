"""Continuous cost accumulator for Belgium Energy Costs.

Why this exists
---------------
The existing "total cost since contract start" sensors compute
``total_kWh × CURRENT_price + fixed``. That re-prices the *entire* history at
today's price, so the figure drifts every time the ENGIE price moves. It is a
documented approximation, not what you were actually billed.

This module accumulates cost the correct way — the same way Home Assistant's own
Energy dashboard does it: on every consumption tick, add
``Δconsumption × price_at_that_moment`` to a persisted running total. Each kWh is
therefore costed at the price in force when it was actually consumed.

Hard limitation (by design): the accumulator is only accurate **from the moment
it starts running**. It cannot retroactively reconstruct historical prices, so it
seeds its baseline from the current meter reading and counts from zero forward.

This module is **purely additive and fail-safe**: it owns its own Store and
entities; any failure is caught at the call site so core sensors are unaffected.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY_FMT = "belgium_energy_costs_cost_accum_{entry_id}"

# Ignore implausibly large single-tick deltas (kWh) — guards against a meter
# swap or glitch dumping a huge jump into the total. Tunable.
_MAX_PLAUSIBLE_TICK_KWH = 1000.0


class CostAccumulator:
    """Persists per-stream running cost totals for one config entry.

    A "stream" is a named cost channel, e.g. "gas", "elec_peak", "elec_offpeak".
    Each stream tracks:
      - running_cost: accumulated EUR
      - last_kwh:     last consumption reading seen (to compute deltas)
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._store: Store = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_FMT.format(entry_id=entry_id)
        )
        self._data: dict[str, Any] = {"version": STORAGE_VERSION, "streams": {}}
        self._loaded = False
        # Serialises ticks so concurrent state-change callbacks can't interleave
        # the read-modify-write of a stream's running total (which would lose or
        # double-count consumption).
        self._lock = asyncio.Lock()

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        if stored and isinstance(stored, dict) and "streams" in stored:
            self._data = {
                "version": STORAGE_VERSION,
                "streams": dict(stored.get("streams", {})),
            }
        self._loaded = True

    async def async_save(self) -> None:
        await self._store.async_save(self._data)

    def running_cost(self, stream: str) -> float:
        return float(self._data["streams"].get(stream, {}).get("running_cost", 0.0))

    def _stream(self, stream: str) -> dict[str, Any]:
        return self._data["streams"].setdefault(
            stream, {"running_cost": 0.0, "last_kwh": None}
        )

    async def async_tick(self, stream: str, current_kwh: float, price: float) -> None:
        """Record a consumption reading for *stream* at the given *price*.

        Adds ``(current_kwh - last_kwh) * price`` to the running total. On first
        sight of a stream it only seeds ``last_kwh`` (no cost added). Negative or
        implausible deltas (meter reset/swap) re-seed without adding cost.
        """
        async with self._lock:
            st = self._stream(stream)
            last = st.get("last_kwh")

            if last is None:
                st["last_kwh"] = current_kwh
                await self.async_save()
                _LOGGER.debug("Cost accumulator '%s' seeded at %.3f kWh", stream, current_kwh)
                return

            delta = current_kwh - last
            if current_kwh <= 0 and last > 0:
                # Transient drop to 0 — almost always an unavailable/unready
                # source sensor at startup, not a real meter reset. Ignore the
                # reading entirely (keep last_kwh) so we don't lose the baseline
                # or spam warnings. A genuine meter swap will read a real value.
                _LOGGER.debug(
                    "Cost accumulator '%s': ignoring transient 0 reading (last=%.3f).",
                    stream, last,
                )
                return
            if delta < 0 or delta > _MAX_PLAUSIBLE_TICK_KWH:
                # Real meter reset / swap / glitch — re-seed, do not add bogus cost.
                _LOGGER.warning(
                    "Cost accumulator '%s': implausible delta %.3f kWh (last=%.3f, "
                    "now=%.3f); re-seeding without adding cost.",
                    stream, delta, last, current_kwh,
                )
                st["last_kwh"] = current_kwh
                await self.async_save()
                return

            st["running_cost"] = round(st["running_cost"] + delta * price, 6)
            st["last_kwh"] = current_kwh
            await self.async_save()
            _LOGGER.debug(
                "Cost accumulator '%s': +%.3f kWh × %.5f = +€%.4f → €%.2f",
                stream, delta, price, delta * price, st["running_cost"],
            )
