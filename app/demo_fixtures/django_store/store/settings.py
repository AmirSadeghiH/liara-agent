"""Minimal Django-style settings module used by the LiaraPilot demo.

The storefront filters products with django-filter.  In the simulated incident
the package is missing from the runtime image, so importing this module raises
ModuleNotFoundError during boot and every request turns into HTTP 500.
"""

import os

import django_filters  # noqa: F401  <-- boot-time import (fails in the demo incident)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

INSTALLED_APPS = [
    "store",
]

FILTER_BACKEND = "store.filters.ProductFilter"
DEFAULT_PAGE_SIZE = 24
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "store"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
    }
}
ALLOWED_HOSTS = ["*"]
