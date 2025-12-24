"""CLI entrypoint wrapper.

This module exists to provide a stable entrypoint location under `python.entrypoints`.
It intentionally delegates to the existing implementation in `python.pipeline.pipeline_analyse`.

Both of these should work:
- python -m python.pipeline.pipeline_analyse
- python -m python.entrypoints.cli.pipeline_analyse
"""

from __future__ import annotations


def main() -> None:
    # Delegate to the existing CLI implementation.
    from python.pipeline.pipeline_analyse import main as pipeline_main

    pipeline_main()


if __name__ == "__main__":
    main()
