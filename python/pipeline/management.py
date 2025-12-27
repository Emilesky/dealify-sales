"""
Shim module.

Temporary backward-compatible import layer.
Domain logic lives in python.domain.pipeline_intel.management.
Do not add logic here.
"""

from python.domain.pipeline_intel.management import *  # noqa: F401,F403