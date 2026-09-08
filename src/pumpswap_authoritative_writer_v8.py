from __future__ import annotations

from functools import wraps

from src.sqlite_write_admission import CAUSAL_PRIORITY, sqlite_write_admission


def causal_authoritative_stage(stage):
    """Gate the one authoritative PumpSwap DB stage as causal SQLite work.

    Resolution/mapping writes already use the shared ``RESOLUTION`` admission class. The active
    V5/V6/V7 path left the authoritative observation writer outside that gate, allowing two SQLite
    write paths to contend behind an apparently single writer queue. This wrapper changes only
    admission order: the physical PumpSwap writer thread, transaction, result and commit semantics
    remain unchanged.
    """

    @wraps(stage)
    def wrapped(prepared_items):
        with sqlite_write_admission(CAUSAL_PRIORITY):
            return stage(prepared_items)

    return wrapped
