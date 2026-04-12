"""Root conftest.py — prevent pytest from collecting __init__.py as a test module."""

import sys
import os

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(__file__))

collect_ignore = ["__init__.py"]
