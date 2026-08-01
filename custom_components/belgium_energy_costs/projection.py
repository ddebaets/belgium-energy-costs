"""Seasonal billing-year cost projection for Belgium Energy Costs.

Why this exists
---------------
The "estimated annual cost" sensors extrapolate the *lifetime average* month.
That is honest for a stable household, but structurally wrong the moment the
household changes regime — the motivating case being a solar + battery
installation: history over-predicts electricity forever after, while the
post-solar summer run-rate under-predicts winter (Belgian December PV yield is
roughly a fifth of July's).

This module instead projects the **current billing year** month by month:

    projected year cost = actual (frozen) cost so far this period
                        + Σ remaining months  modelled cost

where each remaining month's electricity import is::

    import(m) = max(0, load(m) − self_consumed_pv(m))
    load(m)   = annual_load × ELEC_LOAD_SHAPE(m)
    pv(m)     = annual_pv  × PV_YIELD_SHAPE(m)
    self_consumed_pv(m) = min(SELF_USE_CAP × load(m), BATTERY_EFF × pv(m))

and gas is the same idea without the PV term, using the strongly
heating-weighted GAS_LOAD_SHAPE.

The anchors come from data the integration already has:

* ``annual_load`` — the last *closed* billing year's consumption (pre-solar
  import ≈ true household load; for gas it is simply last year's usage).
* ``annual_pv`` — a user-supplied estimate of annual PV generation (kWh),
  configurable in the options flow. 0 disables the PV term entirely, which
  degrades this cleanly to a seasonal (non-solar) projection.

Every monthly figure is exposed in sensor attributes so the model is
inspectable, and all shape constants are module-level so they can be calibrated
as real post-solar winters accumulate.

Shape sources (approximate, normalised at use so exact sums don't matter):

* ``ELEC_LOAD_SHAPE`` — Synergrid residential synthetic load profile shape.
* ``GAS_LOAD_SHAPE`` — Belgian residential heating profile (degree-day like).
* ``PV_YIELD_SHAPE`` — PVGIS monthly yield for Brussels, ~35° south-facing.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any

# Fraction of ANNUAL total falling in each calendar month (index 1-12).
# Normalised at use — values are relative weights, not exact percentages.
ELEC_LOAD_SHAPE: dict[int, float] = {
    1: 0.105, 2: 0.092, 3: 0.092, 4: 0.081, 5: 0.075, 6: 0.068,
    7: 0.067, 8: 0.067, 9: 0.073, 10: 0.085, 11: 0.094, 12: 0.101,
}

GAS_LOAD_SHAPE: dict[int, float] = {
    1: 0.170, 2: 0.145, 3: 0.125, 4: 0.085, 5: 0.045, 6: 0.025,
    7: 0.020, 8: 0.020, 9: 0.035, 10: 0.080, 11: 0.115, 12: 0.135,
}

PV_YIELD_SHAPE: dict[int, float] = {
    1: 0.033, 2: 0.051, 3: 0.087, 4: 0.115, 5: 0.125, 6: 0.124,
    7: 0.123, 8: 0.108, 9: 0.088, 10: 0.062, 11: 0.036, 12: 0.026,
}

# Self-consumption model. SELF_USE_CAP is the fraction of a month's load that
# PV can realistically cover when generation is plentiful (a home battery gets
# this close to 1; night baseload and cloudy stretches keep it below it).
# BATTERY_EFF discounts PV routed through the battery for round-trip losses.
SELF_USE_CAP = 0.95
BATTERY_EFF = 0.90


def _share(shape: dict[int, float], month: int) -> float:
    """Normalised fraction of the annual total falling in *month*."""
    return shape[month] / sum(shape.values())


def month_weights_between(start: date, end: date) -> list[tuple[int, float]]:
    """(month_number, fraction_of_that_month) for each month overlapping [start, end).

    A month fully inside the window contributes weight 1.0; the months at the
    window edges contribute their day-fraction. Month numbers repeat if the
    window spans more than a year of the same calendar month (not expected for
    billing years, but harmless).
    """
    if end <= start:
        return []
    out: list[tuple[int, float]] = []
    cursor = start
    while cursor < end:
        days_in_month = calendar.monthrange(cursor.year, cursor.month)[1]
        month_start = cursor.replace(day=1)
        next_month = month_start + timedelta(days=days_in_month)
        overlap_end = min(end, next_month)
        weight = (overlap_end - cursor).days / days_in_month
        if weight > 0:
            out.append((cursor.month, weight))
        cursor = next_month
    return out


def project_electricity_year(
    *,
    today: date,
    period_start: date,
    period_end: date,
    annual_load_kwh: float,
    annual_pv_kwh: float,
    peak_share: float,
    peak_price: float,
    offpeak_price: float,
    fixed_monthly: float,
    injection_price: float,
    cost_so_far: float,
) -> dict[str, Any]:
    """Project the current electricity billing year.

    ``peak_share`` splits modelled import between peak and off-peak pricing
    (use 1.0 with the single-tariff price passed as ``peak_price``).
    Injection revenue is modelled over the FULL billing year (past months too):
    per-period export is not tracked separately, so the model is the best
    consistent estimate available for the revenue side.
    """
    blended_price = peak_share * peak_price + (1.0 - peak_share) * offpeak_price

    remaining_cost = 0.0
    remaining_import = 0.0
    months_detail: list[dict[str, Any]] = []
    for month, weight in month_weights_between(max(today, period_start), period_end):
        load = annual_load_kwh * _share(ELEC_LOAD_SHAPE, month) * weight
        pv = annual_pv_kwh * _share(PV_YIELD_SHAPE, month) * weight
        self_use = min(SELF_USE_CAP * load, BATTERY_EFF * pv)
        imported = max(0.0, load - self_use)
        cost = imported * blended_price + fixed_monthly * weight
        remaining_cost += cost
        remaining_import += imported
        months_detail.append({
            "month": month,
            "weight": round(weight, 3),
            "load_kwh": round(load, 1),
            "pv_kwh": round(pv, 1),
            "import_kwh": round(imported, 1),
            "cost_eur": round(cost, 2),
        })

    # Full-year export model for injection revenue.
    year_export = 0.0
    for month, weight in month_weights_between(period_start, period_end):
        load = annual_load_kwh * _share(ELEC_LOAD_SHAPE, month) * weight
        pv = annual_pv_kwh * _share(PV_YIELD_SHAPE, month) * weight
        self_use = min(SELF_USE_CAP * load, BATTERY_EFF * pv)
        year_export += max(0.0, pv - self_use)
    year_revenue = year_export * injection_price

    return {
        "projected_cost": round(cost_so_far + remaining_cost, 2),
        "cost_so_far": round(cost_so_far, 2),
        "remaining_modelled_cost": round(remaining_cost, 2),
        "remaining_modelled_import_kwh": round(remaining_import, 1),
        "projected_year_export_kwh": round(year_export, 1),
        "projected_year_injection_revenue": round(year_revenue, 2),
        "months": months_detail,
    }


def project_gas_year(
    *,
    today: date,
    period_start: date,
    period_end: date,
    annual_load_kwh: float,
    price_per_kwh: float,
    fixed_monthly: float,
    cost_so_far: float,
) -> dict[str, Any]:
    """Project the current gas billing year from last year's usage shape."""
    remaining_cost = 0.0
    remaining_kwh = 0.0
    months_detail: list[dict[str, Any]] = []
    for month, weight in month_weights_between(max(today, period_start), period_end):
        kwh = annual_load_kwh * _share(GAS_LOAD_SHAPE, month) * weight
        cost = kwh * price_per_kwh + fixed_monthly * weight
        remaining_cost += cost
        remaining_kwh += kwh
        months_detail.append({
            "month": month,
            "weight": round(weight, 3),
            "kwh": round(kwh, 1),
            "cost_eur": round(cost, 2),
        })

    return {
        "projected_cost": round(cost_so_far + remaining_cost, 2),
        "cost_so_far": round(cost_so_far, 2),
        "remaining_modelled_cost": round(remaining_cost, 2),
        "remaining_modelled_kwh": round(remaining_kwh, 1),
        "months": months_detail,
    }
