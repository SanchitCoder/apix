"""Emit the OpenAPI 3.1 document.

``make openapi`` writes this to ``docs/openapi.json``. The front end and any generated
client build against that file, so it is regenerated whenever the contract changes.
"""

from __future__ import annotations

import json
import sys

from apix_api.main import create_app


def main() -> int:
    json.dump(create_app().openapi(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
