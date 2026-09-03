from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class AssetOrderReservation:
    tickets: tuple[tuple[str, int], ...]

    @property
    def assets(self) -> tuple[str, ...]:
        return tuple(asset for asset, _ in self.tickets)


class AssetOrderGate:
    """Preserve FIFO order per opportunity asset while allowing disjoint assets in parallel.

    Reservations must be created by a dispatcher in websocket ingress order. Workers can then run
    concurrently, but a reservation becomes runnable only when every asset it touches has completed
    all earlier reservations. The ticket relation is induced by one global ingress order, so
    multi-asset reservations cannot form a cyclic wait dependency.
    """

    def __init__(self) -> None:
        self._issued: dict[str, int] = {}
        self._completed: dict[str, int] = {}
        self._condition = asyncio.Condition()

    def reserve(self, assets: tuple[str, ...] | list[str]) -> AssetOrderReservation:
        unique_assets = tuple(sorted({str(asset).strip() for asset in assets if str(asset).strip()}))
        tickets: list[tuple[str, int]] = []
        for asset in unique_assets:
            ticket = self._issued.get(asset, 0)
            self._issued[asset] = ticket + 1
            tickets.append((asset, ticket))
        return AssetOrderReservation(tuple(tickets))

    async def wait_turn(self, reservation: AssetOrderReservation) -> None:
        async with self._condition:
            await self._condition.wait_for(
                lambda: all(
                    self._completed.get(asset, 0) == ticket
                    for asset, ticket in reservation.tickets
                )
            )

    async def complete(self, reservation: AssetOrderReservation) -> None:
        async with self._condition:
            for asset, ticket in reservation.tickets:
                current = self._completed.get(asset, 0)
                if current != ticket:
                    raise RuntimeError(
                        f"asset order completion mismatch for {asset}: expected {current}, got {ticket}"
                    )
            for asset, ticket in reservation.tickets:
                self._completed[asset] = ticket + 1
            self._condition.notify_all()
