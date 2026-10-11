"""Consume at most one accepted local command. There is deliberately no sender."""
from __future__ import annotations

import argparse
import json

from src.commands.preview_ingress import adapter, arguments
from src.commands.reducer import AutomaticPolicy
from src.commands.schema import CommandError
from src.storage.postgres_projection import ProjectionError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    arguments(parser)
    parser.add_argument("--command-id")
    args = parser.parse_args()
    try:
        authority, operators = adapter(args)
        result = authority.consume(operators.resolve, command_id=args.command_id, policy=AutomaticPolicy())
        print(json.dumps({"result": result, "publication_enabled": False}))
    except (ValueError, OSError, CommandError, ProjectionError):
        print('{"error":"local_consumer_unavailable","retry_same_command":true}')
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
