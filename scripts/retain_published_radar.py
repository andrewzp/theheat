#!/usr/bin/env python3
"""Retain already acquired local radar bytes. No fetch, review or publication."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.postgres_published_media import private_bytes, retain
from src.commands.preview_ingress import strict_json, safe_environment
from src.media.published_radar import MAX_INPUT, MAX_ORIGINAL


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "socket-directory",
        "database",
        "user",
        "input",
        "original",
        "receipt",
        "product-reference",
        "reuse-reference",
    ):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--database-port", type=int, default=55473)
    args = parser.parse_args()
    safe_environment()
    authority = PostgresCommandAuthority(
        socket_directory=args.socket_directory,
        database=args.database,
        user=args.user,
        port=args.database_port,
        environment="local",
    )
    result = retain(
        authority,
        strict_json(private_bytes(args.input, MAX_INPUT)),
        private_bytes(args.original, MAX_ORIGINAL),
        {
            "product": private_bytes(args.product_reference, MAX_INPUT),
            "reuse": private_bytes(args.reuse_reference, MAX_INPUT),
        },
        private_bytes(args.receipt, MAX_INPUT),
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
