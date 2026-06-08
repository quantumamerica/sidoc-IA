from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def to_jsonable(payload: Any, *, exclude_none: bool = False) -> Any:
    if isinstance(payload, BaseModel):
        return payload.model_dump(mode="json", exclude_none=exclude_none)
    if isinstance(payload, list):
        return [to_jsonable(item, exclude_none=exclude_none) for item in payload]
    if isinstance(payload, tuple):
        return [to_jsonable(item, exclude_none=exclude_none) for item in payload]
    if isinstance(payload, dict):
        return {key: to_jsonable(value, exclude_none=exclude_none) for key, value in payload.items()}
    return payload


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(payload), indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dumps_json(payload: Any, *, exclude_none: bool = False) -> str:
    return json.dumps(to_jsonable(payload, exclude_none=exclude_none), indent=2, ensure_ascii=False, default=str)
