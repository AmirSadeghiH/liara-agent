"""Application entry point for the demo storefront."""

from __future__ import annotations

from store.filters import ProductFilter
from store.settings import FILTER_BACKEND  # noqa: F401  (validated at startup)

PRODUCTS = [
    {"sku": "A-1", "name": "Espresso Cup", "price": 12.0, "stock": 40},
    {"sku": "B-2", "name": "Pour-over Kettle", "price": 48.0, "stock": 0},
    {"sku": "C-3", "name": "Burr Grinder", "price": 95.0, "stock": 7},
]


def health() -> dict:
    return {"status": "ok", "service": "demo-store"}


def list_products(min_price: float = 0.0, in_stock: bool = False):
    return ProductFilter().filter(PRODUCTS, min_price=min_price, in_stock=in_stock)
