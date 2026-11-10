"""NEXORA — Economic Opportunity Discovery (v1.0).

Read-only research package. Discovery only; no training, no production writes.

Modules:
    moves      — forward-move statistics (percentiles, pos/neg, MFE/MAE).
    granularity— detect intraday-vs-daily granularity break in a bar series.
    horizon    — horizon discovery: move-to-cost, break-even, net expectancy,
                 regime/period stability, multiple-comparison ledger.
"""

from . import moves, granularity, horizon, tick_spread, bar_quality, cost_model, availability, information, scoring, walkforward  # noqa: F401
