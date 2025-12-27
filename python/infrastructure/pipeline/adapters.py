"""Backward-compatible shim for pipeline adapters.

The real implementation (concrete adapters + composition root) lives in
`pipeline_adapters.py`.

Keep this module temporarily so existing imports keep working while we migrate
call sites.
"""

from __future__ import annotations

# Re-export public API from the new module.
from .pipeline_adapters import *  # noqa: F401,F403
from .pipeline_adapters import __all__  # noqa: F401
