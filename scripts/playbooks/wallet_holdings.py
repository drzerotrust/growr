"""Run the packaged wallet_holdings playbook."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from growr_cli.playbooks.wallet_holdings import main

if __name__ == "__main__":
    raise SystemExit(main())
