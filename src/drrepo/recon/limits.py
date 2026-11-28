"""Resource limits for the subprocesses that parse hostile input (scanners, `git log`).

Every scanner already runs with a wall-clock timeout. On Linux, `prlimit`
(util-linux, in the Docker image) also caps each process:

- **file size** (`SCANNER_FILE_SIZE_MB`, default 512): a scanner can't fill the
  disk, whatever the repository makes it write;
- **address space** (`SCANNER_MEMORY_MB`, default 0 = off): opt-in, because
  some tools reserve far more virtual memory than they use (hadolint's GHC
  runtime reserves a terabyte) and fail under a low cap.

Limits are applied by prefixing the command, not with `preexec_fn`, which is
unsafe in a threaded program like the collector fan-out. Where `prlimit` is
missing (macOS, Windows) commands run unchanged.
"""

from __future__ import annotations

import shutil
import sys
from functools import lru_cache

from drrepo.config import Config


@lru_cache(maxsize=1)
def _prlimit() -> str | None:
    return shutil.which("prlimit") if sys.platform.startswith("linux") else None


def limited(argv: list[str], config: Config) -> list[str]:
    """`argv` wrapped in `prlimit` with the configured caps, or unchanged."""
    if not config.enable_scanner_limits:
        return argv
    prlimit = _prlimit()
    if prlimit is None:
        return argv
    caps = []
    if config.scanner_file_size_mb > 0:
        caps.append(f"--fsize={config.scanner_file_size_mb * 1024 * 1024}")
    if config.scanner_memory_mb > 0:
        caps.append(f"--as={config.scanner_memory_mb * 1024 * 1024}")
    return [prlimit, *caps, "--", *argv] if caps else argv
