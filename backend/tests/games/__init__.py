"""Test package marker.

Without these, pytest derives a module name from the basename alone and two
suites cannot both have a `test_api.py` -- which games and eligibility now do.
"""
