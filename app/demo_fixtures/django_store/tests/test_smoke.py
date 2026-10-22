"""Smoke tests for the demo storefront.

These tests fail while django_filters is imported unconditionally and the
package is unavailable, and pass once the repair makes the import resilient.
"""

from app import health, list_products


def test_health_endpoint():
    assert health() == {"status": "ok", "service": "demo-store"}


def test_settings_expose_filter_backend():
    import store.settings as settings

    assert settings.FILTER_BACKEND == "store.filters.ProductFilter"


def test_products_filter_by_price():
    rows = list_products(min_price=40)
    assert [row["sku"] for row in rows] == ["B-2", "C-3"]


def test_products_filter_in_stock():
    rows = list_products(min_price=0, in_stock=True)
    assert {row["sku"] for row in rows} == {"A-1", "C-3"}
