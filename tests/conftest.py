"""Pytest configuration for code-review-env tests."""

import sys
import os

# Add the project root to sys.path so server.* and models can be imported
# without triggering the root __init__.py relative import chain.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
