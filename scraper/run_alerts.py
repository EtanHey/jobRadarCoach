"""Surface scheduled scraper/liveness failures without printing private receipts."""

import argparse
import json
import os
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("scrape", "liveness"), required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    message = None
    try:
        receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict) or receipt.get("status") not in {"success", "failure"}:
            raise ValueError("invalid receipt")
        if receipt["status"] == "failure":
            message = "run failed"
        else:
            if args.kind == "scrape":
                result = receipt.get("result")
                if not isinstance(result, dict):
                    raise ValueError("invalid scrape result")
                count = result.get("source_warning_count")
            else:
                count = receipt.get("alerts")
            if type(count) is not int or count < 0:
                raise ValueError("invalid alert count")
            if count:
                message = (f"{count} source failure(s)" if args.kind == "scrape"
                           else f"{count} new uncertainty or tenant list error(s)")
    except FileNotFoundError:
        message = "receipt missing"
    except (OSError, UnicodeError, ValueError, TypeError):
        message = "receipt invalid"
    if message:
        prefix = "::warning::" if os.environ.get("GITHUB_ACTIONS") == "true" else "WARNING: "
        print(f"{prefix}{args.kind}: {message}; inspect the preserved run log and receipt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
