"""Product filtering helpers for the demo storefront."""

from __future__ import annotations


class ProductFilter:
    """A tiny, dependency-free stand-in for a django-filter FilterSet."""

    def filter(self, rows, *, min_price: float = 0.0, in_stock: bool = False):
        result = [row for row in rows if row["price"] >= min_price]
        if in_stock:
            result = [row for row in result if row.get("stock", 0) > 0]
        return result
