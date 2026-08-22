"""CLI: send the dose_reminder template to one number. Built in Phase 1.

    python scripts/send_test.py 923001234567

This is the Phase 1 gate - the script sends the template, it arrives on a real
phone, and tapping a button writes a message_log row with the right payload.
"""

from __future__ import annotations

import sys

_PHASE = "Phase 1 - WhatsApp transport"


def main(argv: list[str]) -> int:
    raise NotImplementedError(_PHASE)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
