"""The report contract: `report.schema.json` (JSON Schema 2020-12), shipped in the package.

Consumers can load it with `load_schema()`; tests validate every synthesized
report against it, and the schema rejects unknown fields, so the contract can't
drift from the code silently.
"""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files
from typing import Any


@cache
def load_schema() -> dict[str, Any]:
    text = (files("drrepo.report") / "report.schema.json").read_text(encoding="utf-8")
    schema: dict[str, Any] = json.loads(text)
    return schema


def validate(report: dict[str, Any]) -> None:
    """Raise `jsonschema.ValidationError` if `report` breaks the contract.

    Needs the optional `jsonschema` package (a dev dependency).
    """
    import jsonschema

    jsonschema.validate(
        report, load_schema(), format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
    )
