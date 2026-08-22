"""Seed a demo-worthy database. Built in Phase 8.

Creates one caretaker, one patient, three real medicines, and 14 days of
backdated dose events with a believable mix of taken, taken-late and missed -
so the dashboard and both PDFs have something worth showing.

    make seed   (or seed.ps1 on Windows)
"""

from __future__ import annotations

import sys

_PHASE = "Phase 8 - deploy"


def main() -> int:
    print(f"seed_demo.py is not implemented yet - it lands in {_PHASE}.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
