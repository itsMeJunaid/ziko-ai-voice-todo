"""The only operations the model can perform (PRD §5.4, §9.1, §11.5).

Model output is untrusted: every call is looked up by name, its arguments validated by a Pydantic model, and
run through the same services as the HTTP API inside one transaction. The result is returned only after the
commit, so the model can never be told something succeeded when it did not (PRD §4.3). Errors come back as
data (`{"ok": false, "error": …}`) for the model to explain or ask about; nothing here raises.
"""

from __future__ import annotations

import logging
import types as pytypes
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel, ValidationError

from app.api.deps import Ctx, build_ctx
from app.core.clock import Clock
from app.core.errors import ZikoError
from app.database.engine import session_scope

log = logging.getLogger(__name__)

Handler = Callable[[Ctx, Any], dict[str, Any]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    handler: Handler


def _json_type(annotation: Any) -> dict[str, Any]:
    if get_origin(annotation) in (Union, pytypes.UnionType):  # Optional[X] → X
        annotation = next(a for a in get_args(annotation) if a is not type(None))
    if get_origin(annotation) is Literal:
        return {"type": "string", "enum": [str(v) for v in get_args(annotation)]}
    return {
        "type": {str: "string", int: "integer", bool: "boolean", float: "number"}.get(annotation, "string")
    }


def parameters_schema(model: type[BaseModel]) -> dict[str, Any]:
    """A flat JSON schema (no $defs / anyOf): the subset Live models handle reliably."""
    props: dict[str, Any] = {}
    required: list[str] = []
    for name, f in model.model_fields.items():
        props[name] = _json_type(f.annotation) | ({"description": f.description} if f.description else {})
        if f.is_required():
            required.append(name)
    return {"type": "object", "properties": props} | ({"required": required} if required else {})


def error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message, **extra}}


class ToolRegistry:
    def __init__(self, clock: Clock, tools: list[Tool]) -> None:
        self.clock = clock
        self.tools = {t.name: t for t in tools}

    def declarations(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters_json_schema": parameters_schema(t.args),
            }
            for t in self.tools.values()
        ]

    def execute(self, name: str, args: dict[str, Any] | None) -> dict[str, Any]:
        tool = self.tools.get(name)
        if tool is None:
            return error("unknown_tool", f"There is no tool named {name!r}")
        try:
            parsed = tool.args.model_validate(args or {})
            with session_scope() as s:
                result = tool.handler(build_ctx(s, self.clock), parsed)
            return result  # reached only after the commit succeeded
        except ValidationError as e:
            problems = "; ".join(
                f"{'.'.join(map(str, x['loc'])) or 'arguments'}: {x['msg']}" for x in e.errors()
            )
            return error("invalid_arguments", problems)
        except ZikoError as e:
            details = e.details if isinstance(e.details, dict) else {}
            return error(e.code, e.message, **details)
        except Exception:
            log.exception("tool %s failed", name)
            return error("internal", "That didn't work because of an internal error. Nothing was changed.")
