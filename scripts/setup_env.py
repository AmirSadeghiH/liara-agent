"""Create the local .env (non-destructively) and prepare data directories.

Usage::

    python scripts/setup_env.py            # create .env from .env.example
    python scripts/setup_env.py --check    # report what would be done

The script never overwrites an existing .env and never writes a real secret.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
EXAMPLE_FILE = ROOT / ".env.example"

DATA_DIRS = ["data", "data/workspaces", "data/artifacts"]
PLACEHOLDER_SECRET = "CHANGE_ME_GENERATE_A_RANDOM_SECRET"


def ensure_data_dirs(root: Path = ROOT) -> list[Path]:
    created: list[Path] = []
    for relative in DATA_DIRS:
        path = root / relative
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(path)
    return created


def rotate_secret(content: str) -> str:
    """Replace the placeholder APP_SECRET_KEY with a locally generated value.

    This is *not* a Liara token - it only signs local session cookies.
    """
    generated = secrets.token_urlsafe(48)
    return content.replace(f"APP_SECRET_KEY={PLACEHOLDER_SECRET}", f"APP_SECRET_KEY={generated}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare the LiaraPilot local environment")
    parser.add_argument("--check", action="store_true", help="only report, do not write")
    parser.add_argument("--rotate-secret", action="store_true",
                        help="generate a random APP_SECRET_KEY (only when creating .env)")
    args = parser.parse_args(argv)

    if not EXAMPLE_FILE.exists():
        print(f"[setup] missing {EXAMPLE_FILE.name}; run this from the repository root.",
              file=sys.stderr)
        return 1

    if ENV_FILE.exists():
        print("[setup] .env already exists - leaving it untouched.")
    elif args.check:
        print("[setup] .env does not exist (would be created from .env.example).")
    else:
        content = EXAMPLE_FILE.read_text(encoding="utf-8")
        content = rotate_secret(content)
        ENV_FILE.write_text(content, encoding="utf-8")
        try:  # best effort: keep the file private on POSIX systems
            ENV_FILE.chmod(0o600)
        except OSError:
            pass
        print("[setup] created .env from .env.example (DEMO_MODE=true).")

    if args.check:
        print("[setup] data directories:", ", ".join(DATA_DIRS))
    else:
        created = ensure_data_dirs()
        print(f"[setup] data directories ready ({len(created)} created).")

    print("[setup] next: python scripts/validate_config.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
