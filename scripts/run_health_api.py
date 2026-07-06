"""Run the health check API server.

Invoked as `python scripts/run_health_api.py` (per CLAUDE.md/README), i.e. by
path rather than `python -m`. A by-path script only gets its own directory
(`scripts/`) on sys.path, not the repo root where `src/` lives -- unlike
`app.py` (at the repo root) or `python -m src.main`, both of which put the
repo root on sys.path implicitly. Without this insert, `import src` fails
with ModuleNotFoundError even on a totally fresh, correctly-set-up clone.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn  # noqa: E402

from src.utils.logger import logger  # noqa: E402

if __name__ == "__main__":
    logger.info("Starting DrRepo Health Check API...")

    uvicorn.run(
        "src.api.health:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
