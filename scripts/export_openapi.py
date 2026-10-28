"""Write the FastAPI OpenAPI spec to schemas/openapi.json.

Usage: just codegen-api   (then openapi-typescript turns it into web/src/generated/api.ts)
"""

import json
import sys

from compliance.config import REPO_ROOT
from compliance.main import create_app


def main() -> int:
    app = create_app(":memory:")
    spec = app.openapi()
    out = REPO_ROOT / "schemas" / "openapi.json"
    out.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(REPO_ROOT).as_posix()} ({len(spec['paths'])} paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
