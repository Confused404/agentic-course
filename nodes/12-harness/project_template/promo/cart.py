"""Carts. Money is always integer cents."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Line:
    sku: str
    unit_cents: int
    qty: int

    @property
    def total_cents(self) -> int:
        return self.unit_cents * self.qty


@dataclass(frozen=True)
class Cart:
    lines: tuple[Line, ...]

    @property
    def subtotal_cents(self) -> int:
        return sum(line.total_cents for line in self.lines)

    def qty_of(self, sku: str) -> int:
        return sum(line.qty for line in self.lines if line.sku == sku)

    def unit_of(self, sku: str) -> int | None:
        return next((line.unit_cents for line in self.lines if line.sku == sku), None)
