"""Print the OpenAPI schema without starting a server: ``python -m shutong.api.export > openapi.json``.

The web UI generates its TypeScript types from this, so the output is stable (sorted keys).
"""
import json
from pathlib import Path
import sys
import tempfile

from shutong.api.app import create_app
from shutong.logs import shutdown_logging


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="shutong-export-") as data_dir:
        app = create_app(data_dir, inline_jobs=True)
        schema = app.openapi()
        app.state.jobs.stop()
        shutdown_logging(Path(data_dir))  # Windows cannot delete an open log file
    sys.stdout.write(json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
