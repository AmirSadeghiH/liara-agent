# Demo storefront (LiaraPilot fixture)

This is a miniature Django-style application used exclusively by LiaraPilot's
Demo Mode. It is **sample data**, not part of the LiaraPilot server.

Simulated incident: `store/settings.py` imports `django_filters` at module
import time but the dependency is missing from `requirements.txt`, so the
application fails during boot and returns HTTP 500 for every request.
