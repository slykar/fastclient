"""
This module is just a proxy to `fastapi` module, so I have an easy way to intercept calls later if needed.
"""

from fastapi.param_functions import Body, Header, Path, Query

__all__ = ["Query", "Path", "Header", "Body"]
