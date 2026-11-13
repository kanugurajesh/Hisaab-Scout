"""Write openapi.json, the contract Hisaab's frontend generates its types from.

  uv run python scripts/export_openapi.py          # write it
  uv run python scripts/export_openapi.py --check  # CI: fail if the code and the file disagree
"""

import json
import sys
from pathlib import Path

from scout.config import Settings
from scout.main import create_app

OUT = Path(__file__).resolve().parents[1] / "openapi.json"


def main() -> int:
    spec = create_app(Settings(_env_file=None)).openapi()
    text = json.dumps(spec, indent=2, ensure_ascii=False) + "\n"
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print("openapi.json is out of date. Run: uv run python scripts/export_openapi.py", file=sys.stderr)
            return 1
        print("openapi.json is up to date.")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
