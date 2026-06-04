"""Per-contract-year history for Belgium Energy Costs.

Design notes
------------
This module is **purely additive**. It never modifies the existing
"since contract start" sensors, never rolls baselines, and is wrapped in a
try/except at the platform-setup call site so that any failure here leaves the
core sensors fully functional.

Model
-----
The existing sensors are cumulative *since contract start* (lifetime). To derive
per-contract-year figures we store an **anniversary snapshot** each time a
contract year completes: the lifetime values at that moment. Then:

* current-year value   = lifetime_now − snapshot_at_start_of_current_year
* closed-year N value  = snapshot[N] − snapshot[N-1]   (snapshot[-1] ≡ 0)

Electricity and gas can have different contract start dates, so each utility is
tracked independently.

Storage
-------
One ``homeassistant.helpers.storage.Store`` per config entry, keyed by entry_id.
Schema (version 1)::

    {
      "version": 1,
      "snapshots": {
        "elec": [ {snapshot}, ... ],   # ordered, one per completed year
        "gas":  [ {snapshot}, ... ]
      }
    }

Each snapshot::

    {
      "year_index": 1,                 # 1 = first contract year that just closed
      "period_start": "2025-06-02",
      "period_end":   "2026-06-02",
      "closed_on":    "2026-06-02",    # date the snapshot was actually taken
      "values": { "<metric>": <float lifetime value at close>, ... }
    }
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY_FMT = "belgium_energy_costs_year_history_{entry_id}"

UTILITY_ELEC = "elec"
UTILITY_GAS = "gas"


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _safe_anniversary(start: date, year: int) -> date:
    """Return *start* moved to the given calendar *year*, Feb-29 safe."""
    try:
        return start.replace(year=year)
    except ValueError:
        # start is Feb 29 and target year is not a leap year → use Feb 28
        return start.replace(year=year, month=2, day=28)


def completed_contract_years(start: date, today: date) -> int:
    """Number of *fully completed* contract years between start and today.

    0 while still inside the first contract year; 1 on/after the first
    anniversary; etc. Returns 0 for any today before the start date.
    """
    if today < start:
        return 0
    years = today.year - start.year
    anniv = _safe_anniversary(start, start.year + years)
    if anniv > today:
        years -= 1
    return max(0, years)


def contract_year_label(start: date, year_index: int) -> str:
    """Human label for the *year_index*-th contract year (1-based).

    year_index=1 → the first contract year, e.g. "2025–2026".
    """
    begin = _safe_anniversary(start, start.year + year_index - 1)
    end = _safe_anniversary(start, start.year + year_index)
    return f"{begin.year}–{end.year}"


def due_year_index(start: date, today: date, already_closed: int) -> int | None:
    """Year index that auto-rollover should close today, or None.

    Compares the number of calendar-anniversary years completed against the
    number already stored. If a manual early-close already advanced the stored
    count past the calendar (e.g. the meter was read before the anniversary),
    this returns None and no automatic snapshot is taken.
    """
    completed = completed_contract_years(start, today)
    if completed > already_closed:
        return already_closed + 1
    return None


# ---------------------------------------------------------------------------
# Store wrapper
# ---------------------------------------------------------------------------

class ContractYearHistory:
    """Loads / persists per-utility anniversary snapshots for one config entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_FMT.format(entry_id=entry_id)
        )
        self._data: dict[str, Any] = {"version": STORAGE_VERSION, "snapshots": {UTILITY_ELEC: [], UTILITY_GAS: []}}
        self._loaded = False

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        if stored and isinstance(stored, dict):
            snaps = stored.get("snapshots", {})
            self._data = {
                "version": STORAGE_VERSION,
                "snapshots": {
                    UTILITY_ELEC: list(snaps.get(UTILITY_ELEC, [])),
                    UTILITY_GAS: list(snaps.get(UTILITY_GAS, [])),
                },
            }
        self._loaded = True

    async def async_save(self) -> None:
        await self._store.async_save(self._data)

    # -- read helpers ----------------------------------------------------

    def snapshots(self, utility: str) -> list[dict[str, Any]]:
        return self._data["snapshots"].get(utility, [])

    def completed_year_count(self, utility: str) -> int:
        return len(self.snapshots(utility))

    def last_cumulative(self, utility: str) -> dict[str, float]:
        """Lifetime cumulative values at the start of the *current* year.

        Equals the most recent snapshot's ``cumulative``, or an empty dict
        (→ treated as 0) when no year has closed yet (still in year 1).
        Used to derive current-year consumption deltas.
        """
        snaps = self.snapshots(utility)
        return dict(snaps[-1].get("cumulative", {})) if snaps else {}

    def last_period_end(self, utility: str) -> date | None:
        """period_end of the most recent close, or None if none yet.

        Used to anchor the current period's elapsed-month calculation so an
        early close (period_end before the anniversary) leaves no unbilled gap.
        """
        snaps = self.snapshots(utility)
        if not snaps:
            return None
        raw = snaps[-1].get("period_end")
        if not raw:
            return None
        try:
            return date.fromisoformat(raw)
        except (ValueError, TypeError):
            return None

    def closed_years(self, utility: str) -> list[dict[str, Any]]:
        """Closed contract years for the history sensor.

        Consumption (kWh, m³) is the delta between consecutive cumulative
        snapshots; cost is the FROZEN ``year_cost`` stored at close (never
        recomputed), so closed-year cost stays correct despite price changes.
        """
        out: list[dict[str, Any]] = []
        prev: dict[str, float] = {}
        for snap in self.snapshots(utility):
            cur = snap.get("cumulative", {})
            totals = {k: round(cur.get(k, 0.0) - prev.get(k, 0.0), 3) for k in cur}
            # Default to 0.0 (not None) so a pre-frozen-cost-schema snapshot, if
            # one ever existed, renders a number rather than "none" in the UI.
            totals["cost"] = snap.get("year_cost") or 0.0
            out.append({
                "year": snap.get("year_index"),
                "label": snap.get("label"),
                "period_start": snap.get("period_start"),
                "period_end": snap.get("period_end"),
                "totals": totals,
            })
            prev = cur
        return out

    # -- mutate ----------------------------------------------------------

    async def async_append_snapshot(
        self, utility: str, year_index: int, start: date,
        period_end: date, closed_on: date,
        cumulative: dict[str, float], year_cost: float,
    ) -> None:
        """Record a completed contract year.

        ``cumulative`` holds the *lifetime* (since-contract-start) values at the
        moment of close — used only to derive the NEXT year's deltas. ``year_cost``
        is the FROZEN cost for the year being closed, computed from this year's own
        consumption × the price at close; it is never recomputed afterwards (this
        is what makes closed-year cost stable despite later price changes).
        """
        # Always derive the index from current length so it stays contiguous,
        # regardless of what the caller passed (defends the undo/re-close path).
        year_index = len(self._data["snapshots"].setdefault(utility, [])) + 1
        snap = {
            "year_index": year_index,
            "label": contract_year_label(start, year_index),
            "period_start": _safe_anniversary(start, start.year + year_index - 1).isoformat(),
            "period_end": period_end.isoformat(),
            "closed_on": closed_on.isoformat(),
            "cumulative": {k: round(float(v), 3) for k, v in cumulative.items()},
            "year_cost": round(float(year_cost), 2),
        }
        self._data["snapshots"].setdefault(utility, []).append(snap)
        await self.async_save()
        _LOGGER.info(
            "Belgium Energy Costs: closed %s contract year %s (%s) for utility '%s' — frozen cost €%.2f",
            snap["label"], year_index, snap["period_end"], utility, snap["year_cost"],
        )

    async def async_remove_last_snapshot(self, utility: str) -> bool:
        """Remove the most recent snapshot for *utility* (undo a close).

        Returns True if one was removed, False if there were none.
        """
        snaps = self._data["snapshots"].get(utility, [])
        if not snaps:
            return False
        removed = snaps.pop()
        await self.async_save()
        _LOGGER.info(
            "Belgium Energy Costs: removed last snapshot (%s) for utility '%s'",
            removed.get("label"), utility,
        )
        return True
