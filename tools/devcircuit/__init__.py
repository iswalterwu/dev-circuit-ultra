"""devcircuit — command line wrapper around the dev-circuit-ultra guards.

The guards themselves stay plain single-file scripts under
`skills/dev-circuit-ultra/scripts/` so a project can copy them in and run them
with nothing installed. This package exposes the same code as a CLI:

    devcircuit doc-guard  [--root DIR] [--ignore GLOB] ... [--json]
    devcircuit spec-check [--root DIR] [--ignore GLOB] ... [--json] [--report]
    devcircuit check      [--root DIR]
    devcircuit hooks install --harness pi|claude [--project DIR] [--ledger DIR]
    devcircuit hooks status  [--project DIR]
"""

__all__ = ["__version__"]

__version__ = "0.6.1"
