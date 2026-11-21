"""Validate nonsecret route configuration before workflow credential delivery.

GitHub expression equality ignores case. Only this exact enum's fixed output
selects credential names; it is configuration containment, not an identity fence.
Legacy is supported for the existing authenticated route deactivation consumer.
"""

from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.commands.gist_route import RouteRefused, configured_mode


def main() -> int:
    try:
        mode = configured_mode()
    except RouteRefused as exc:
        print(f"[gist-route-mode] {exc.code}", file=sys.stderr)
        return 1
    target = os.environ.get("GITHUB_OUTPUT", "")
    if not target:
        print("[gist-route-mode] step_output_missing", file=sys.stderr)
        return 1
    try:
        with open(target, "a", encoding="utf-8") as stream:
            stream.write(f"mode={mode}\n")
    except OSError:
        print("[gist-route-mode] step_output_unavailable", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
