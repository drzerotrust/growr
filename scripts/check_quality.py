"""Run the same application quality checks locally and in CI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """Stop at the first failed check and preserve its exit status."""

    # The interactive client stays local and is absent in GitHub clones.
    local_sources = (
        ("client.py",) if (PROJECT_ROOT / "client.py").is_file() else ()
    )
    checks = (
        ("ruff", "check", ".", *local_sources),
        ("ruff", "format", "--check", ".", *local_sources),
        ("mypy", "growr_cli", "growr.py", "scripts", *local_sources),
        ("pytest", "-q"),
    )
    for arguments in checks:
        print("Running: %s" % " ".join(arguments), flush=True)
        result = subprocess.run(
            [sys.executable, "-m", *arguments],
            cwd=PROJECT_ROOT,
            check=False,
        )
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
