"""Run the minimal local Economy-guy GUI from finance_agent."""
from __future__ import annotations

import sys

from app.gui_delivery import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
