"""Infrastructure adapters for the pipeline.

NOTE
- This module is the long-term home for concrete adapters (file IO, pandas transforms, LLM calls, mapping).
- For now, it re-exports the existing implementations from `python.application.adapters` to keep the
  system working while we migrate in small, safe commits.

Next refactor step
- Move the concrete adapter implementations into this module (or submodules) and update
  `python.application.adapters` to become a thin wrapper that imports from here.
"""

from __future__ import annotations

# Temporary bridge: keep behavior stable while we migrate.
from python.application.adapters import (  # noqa: F401
    PipelineAdapters,
    create_default_pipeline_adapters,
)

__all__ = [
    "PipelineAdapters",
    "create_default_pipeline_adapters",
]
