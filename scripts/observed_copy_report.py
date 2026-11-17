#!/usr/bin/env python3
"""Private observed-copy report from explicit local exports; offline and read-only.

Usage: observed_copy_report.py --input EXPORT.json [--input ...] --out NEW_PRIVATE_DIR

Each input is a state snapshot (``drafts`` and optional ``suppressions``) or a list of drafts,
read without following symlinks. The output directory must not exist; it is created 0700 with
0600 report.json, report.md and review-sheet.md. Stdout carries counts only, never draft text.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.evaluation import file_boundary  # noqa: E402
from src.evaluation import observed_copy  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, help="explicit local export path (repeatable)")
    parser.add_argument("--out", required=True, help="new private output directory")
    args = parser.parse_args(argv)
    try:
        if len(args.input) > observed_copy.MAX_INPUTS:
            raise observed_copy.ReportError("input_count_out_of_range")
        exports = [observed_copy.parse_export(os.path.basename(path),
                                              file_boundary.read_regular(path, observed_copy.MAX_INPUT_BYTES))
                   for path in args.input]
        summary, markdown, sheet = observed_copy.build_report(exports)
        body = json.dumps(summary, indent=1, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
        file_boundary.write_private_directory(args.out, {
            "report.json": body.encode(), "report.md": markdown.encode(), "review-sheet.md": sheet.encode()})
    except observed_copy.ReportError as exc:
        print(json.dumps({"error": exc.code}))
        return 2
    except file_boundary.FileBoundaryError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    except FileExistsError:
        print(json.dumps({"error": "output_exists"}))
        return 2
    print(json.dumps({"identities": summary["identities"], "stages": summary["stages"],
                      "warnings": summary["warnings"], "sentences": summary["sentences"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
