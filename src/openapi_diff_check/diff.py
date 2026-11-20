"""Compare two OpenAPI documents and classify every difference."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from openapi_diff_check.loader import Spec

BREAKING = "breaking"
NON_BREAKING = "non-breaking"
INFO = "info"
SEVERITIES = (BREAKING, NON_BREAKING, INFO)
SEVERITY_RANK = {BREAKING: 0, NON_BREAKING: 1, INFO: 2}

METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
REQUEST = "request"
RESPONSE = "response"

# keyword -> "max" (smaller is narrower) or "min" (larger is narrower)
LIMITS = {
    "maxLength": "max",
    "minLength": "min",
    "maximum": "max",
    "minimum": "min",
    "maxItems": "max",
    "minItems": "min",
    "maxProperties": "max",
    "minProperties": "min",
}
# keywords where adding or changing the value narrows what is accepted
RESTRICTIONS = ("pattern", "multipleOf")


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    path: str = ""
    method: str = ""
    location: str = ""
    ignored: bool = False
    ignore_reason: str = ""

    @property
    def operation(self) -> str:
        return f"{self.method.upper()} {self.path}".strip()

    @property
    def fingerprint(self) -> str:
        return "|".join((self.rule, self.method.upper(), self.path, self.location))

    def sort_key(self) -> tuple[int, str, str, str, str]:
        return (SEVERITY_RANK[self.severity], self.path, self.method, self.location, self.rule)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
            "path": self.path,
            "method": self.method.upper(),
            "location": self.location,
            "fingerprint": self.fingerprint,
        }
        if self.ignored:
            out["ignored"] = True
            out["ignore_reason"] = self.ignore_reason
        return out


def _template(path: str) -> str:
    return re.sub(r"\{[^}/]*\}", "{}", path.rstrip("/") or "/")


def _param_names(path: str) -> list[str]:
    return re.findall(r"\{([^}/]*)\}", path)


def _dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _fmt(value: Any) -> str:
    if isinstance(value, str):
        return repr(value)
    return _dump(value)


def _types(schema: dict[str, Any]) -> set[str] | None:
    raw = schema.get("type")
    if raw is None:
        types = None
    elif isinstance(raw, list):
        types = {str(t) for t in raw}
    else:
        types = {str(raw)}
    if schema.get("nullable") is True:
        types = (types or set()) | {"null"} if types is not None else None
    return types


def _show_types(types: set[str] | None) -> str:
    return "any" if types is None else "|".join(sorted(types))


def _covers(wide: set[str], narrow: set[str]) -> bool:
    """True if every type in ``narrow`` is accepted by ``wide`` (integer is a number)."""
    return all(t in wide or (t == "integer" and "number" in wide) for t in narrow)


def _enum(schema: dict[str, Any]) -> dict[str, Any] | None:
    if "const" in schema:
        return {_dump(schema["const"]): schema["const"]}
    values = schema.get("enum")
    if not isinstance(values, list):
        return None
    out = {_dump(v): v for v in values}
    if schema.get("nullable") is True:
        out.setdefault(_dump(None), None)
    return out


def _media(name: str) -> str:
    return name.split(";")[0].strip().lower()


@dataclass
class Flat:
    """A schema with ``allOf`` merged and properties carrying their own base URI."""

    raw: dict[str, Any]
    base: str
    properties: dict[str, tuple[Any, str]] = field(default_factory=dict)
    required: set[str] = field(default_factory=set)
    items: tuple[Any, str] | None = None
    additional: Any = None  # None (not set) | bool | (node, base)
    variants: dict[str, list[tuple[Any, str]]] = field(default_factory=dict)


class Differ:
    def __init__(self, old: Spec, new: Spec):
        self.old = old
        self.new = new
        self.findings: list[Finding] = []
        self._path = ""
        self._method = ""
        self._seen: set[tuple[int, int, str]] = set()

    # -- reporting -------------------------------------------------------

    def add(self, rule: str, severity: str, message: str, location: str = "") -> None:
        self.findings.append(Finding(rule, severity, message, self._path, self._method, location))

    # -- entry point -----------------------------------------------------

    def run(self) -> list[Finding]:
        self._compare_paths()
        self._path, self._method = "", ""
        self._compare_security_schemes()
        unique: dict[str, Finding] = {}
        for f in self.findings:
            unique.setdefault(f.fingerprint + f.message, f)
        return sorted(unique.values(), key=Finding.sort_key)

    # -- paths and operations ----------------------------------------------

    def _paths(self, spec: Spec) -> dict[str, tuple[str, dict[str, Any], str]]:
        paths, _ = spec.resolve(spec.root.get("paths") or {})
        out = {}
        for raw_path, item in (paths or {}).items():
            if not isinstance(item, dict):
                continue
            resolved, base = spec.resolve(item)
            out[_template(str(raw_path))] = (str(raw_path), resolved, base)
        return out

    def _compare_paths(self) -> None:
        old_paths, new_paths = self._paths(self.old), self._paths(self.new)
        for key in sorted(set(old_paths) | set(new_paths)):
            if key not in new_paths:
                self._path, self._method = old_paths[key][0], ""
                self.add("path-removed", BREAKING, "path removed")
                continue
            if key not in old_paths:
                self._path, self._method = new_paths[key][0], ""
                self.add("path-added", NON_BREAKING, "path added")
                continue
            old_raw, old_item, old_base = old_paths[key]
            new_raw, new_item, new_base = new_paths[key]
            self._path = new_raw
            rename = dict(zip(_param_names(old_raw), _param_names(new_raw), strict=False))
            for method in METHODS:
                self._method = method
                old_op, new_op = old_item.get(method), new_item.get(method)
                if old_op is None and new_op is None:
                    continue
                if new_op is None:
                    self.add("operation-removed", BREAKING, "operation removed")
                elif old_op is None:
                    self.add("operation-added", NON_BREAKING, "operation added")
                else:
                    self._compare_operation(old_item, old_op, old_base, new_item, new_op, new_base, rename)

    def _compare_operation(
        self,
        old_item: dict[str, Any],
        old_op: dict[str, Any],
        old_base: str,
        new_item: dict[str, Any],
        new_op: dict[str, Any],
        new_base: str,
        rename: dict[str, str],
    ) -> None:
        old_op, old_base = self.old.resolve(old_op, old_base)
        new_op, new_base = self.new.resolve(new_op, new_base)
        if not old_op.get("deprecated") and new_op.get("deprecated"):
            self.add("operation-deprecated", INFO, "operation deprecated")
        if old_op.get("operationId") and new_op.get("operationId") and old_op["operationId"] != new_op["operationId"]:
            self.add(
                "operation-id-changed",
                INFO,
                f"operationId changed from {old_op['operationId']!r} to {new_op['operationId']!r}"
                " (generated client method names change)",
            )
        self._compare_parameters(old_item, old_op, old_base, new_item, new_op, new_base, rename)
        self._compare_request_body(old_op, old_base, new_op, new_base)
        self._compare_responses(old_op, old_base, new_op, new_base)
        self._compare_security(old_op, new_op)

    # -- parameters --------------------------------------------------------

    def _params(
        self, spec: Spec, item: dict[str, Any], op: dict[str, Any], base: str, rename: dict[str, str] | None
    ) -> dict[tuple[str, str], tuple[dict[str, Any], str]]:
        out: dict[tuple[str, str], tuple[dict[str, Any], str]] = {}
        for source in (item.get("parameters") or [], op.get("parameters") or []):
            for raw in source:
                param, pbase = spec.resolve(raw, base)
                if not isinstance(param, dict) or "name" not in param or "in" not in param:
                    continue
                where, name = str(param["in"]), str(param["name"])
                if where == "header":
                    name = name.lower()
                if where == "path" and rename is not None:
                    name = rename.get(name, name)
                out[(where, name)] = (param, pbase)
        return out

    def _compare_parameters(
        self,
        old_item: dict[str, Any],
        old_op: dict[str, Any],
        old_base: str,
        new_item: dict[str, Any],
        new_op: dict[str, Any],
        new_base: str,
        rename: dict[str, str],
    ) -> None:
        old = self._params(self.old, old_item, old_op, old_base, rename)
        new = self._params(self.new, new_item, new_op, new_base, None)
        for old_name, new_name in rename.items():
            if old_name != new_name:
                self.add(
                    "path-parameter-renamed",
                    INFO,
                    f"path parameter renamed from {old_name!r} to {new_name!r}",
                    f"parameter path.{new_name}",
                )

        removed = [k for k in old if k not in new]
        added = [k for k in new if k not in old]
        # A removed and an added parameter in the same place with the same schema is a rename.
        for key in list(removed):
            old_param, old_pbase = old[key]
            old_schema = _dump(self.old.resolve(old_param.get("schema", {}), old_pbase)[0])
            match = next(
                (
                    a
                    for a in added
                    if a[0] == key[0]
                    and _dump(self.new.resolve(new[a][0].get("schema", {}), new[a][1])[0]) == old_schema
                ),
                None,
            )
            if match is None:
                continue
            removed.remove(key)
            added.remove(match)
            self.add(
                "parameter-renamed",
                BREAKING,
                f"{key[0]} parameter renamed from {key[1]!r} to {match[1]!r}",
                f"parameter {match[0]}.{match[1]}",
            )
        for where, name in removed:
            self.add("parameter-removed", BREAKING, f"{where} parameter {name!r} removed", f"parameter {where}.{name}")
        for where, name in added:
            param = new[(where, name)][0]
            if param.get("required") or where == "path":
                self.add(
                    "parameter-required-added",
                    BREAKING,
                    f"new required {where} parameter {name!r}",
                    f"parameter {where}.{name}",
                )
            else:
                self.add(
                    "parameter-added",
                    NON_BREAKING,
                    f"new optional {where} parameter {name!r}",
                    f"parameter {where}.{name}",
                )

        for key in sorted(set(old) & set(new)):
            (old_param, old_pbase), (new_param, new_pbase) = old[key], new[key]
            loc = f"parameter {key[0]}.{new_param.get('name', key[1])}"
            was, now = bool(old_param.get("required")), bool(new_param.get("required"))
            if not was and now:
                self.add("parameter-became-required", BREAKING, "parameter became required", loc)
            elif was and not now:
                self.add("parameter-became-optional", NON_BREAKING, "parameter became optional", loc)
            if not old_param.get("deprecated") and new_param.get("deprecated"):
                self.add("parameter-deprecated", INFO, "parameter deprecated", loc)
            for attr in ("style", "explode"):
                if old_param.get(attr) != new_param.get(attr) and (attr in old_param or attr in new_param):
                    self.add(
                        "parameter-serialization-changed",
                        BREAKING,
                        f"{attr} changed from {_fmt(old_param.get(attr))} to {_fmt(new_param.get(attr))}",
                        loc,
                    )
            old_schema = self._param_schema(old_param)
            new_schema = self._param_schema(new_param)
            if old_schema is not None and new_schema is not None:
                self._schema(old_schema, old_pbase, new_schema, new_pbase, REQUEST, loc, "")

    @staticmethod
    def _param_schema(param: dict[str, Any]) -> Any:
        if "schema" in param:
            return param["schema"]
        for media in (param.get("content") or {}).values():
            if isinstance(media, dict) and "schema" in media:
                return media["schema"]
        return None

    # -- request bodies ------------------------------------------------------

    def _compare_request_body(
        self, old_op: dict[str, Any], old_base: str, new_op: dict[str, Any], new_base: str
    ) -> None:
        old_body = new_body = None
        if "requestBody" in old_op:
            old_body, old_base = self.old.resolve(old_op["requestBody"], old_base)
        if "requestBody" in new_op:
            new_body, new_base = self.new.resolve(new_op["requestBody"], new_base)
        if old_body is None and new_body is None:
            return
        if old_body is None:
            assert new_body is not None
            if new_body.get("required"):
                self.add("request-body-required-added", BREAKING, "new required request body", "request body")
            else:
                self.add("request-body-added", NON_BREAKING, "new optional request body", "request body")
            return
        if new_body is None:
            self.add("request-body-removed", INFO, "request body removed", "request body")
            return
        was, now = bool(old_body.get("required")), bool(new_body.get("required"))
        if not was and now:
            self.add("request-body-became-required", BREAKING, "request body became required", "request body")
        elif was and not now:
            self.add("request-body-became-optional", NON_BREAKING, "request body became optional", "request body")
        self._compare_content(
            old_body.get("content") or {}, old_base, new_body.get("content") or {}, new_base, REQUEST, "request body"
        )

    def _compare_content(
        self, old: dict[str, Any], old_base: str, new: dict[str, Any], new_base: str, direction: str, where: str
    ) -> None:
        old_media = {_media(k): v for k, v in old.items()}
        new_media = {_media(k): v for k, v in new.items()}
        for media in sorted(set(old_media) | set(new_media)):
            loc = f"{where} {media}"
            if media not in new_media:
                self.add(f"{direction}-media-type-removed", BREAKING, f"media type {media} removed", loc)
            elif media not in old_media:
                self.add(f"{direction}-media-type-added", NON_BREAKING, f"media type {media} added", loc)
            else:
                o, n = old_media[media] or {}, new_media[media] or {}
                if "schema" in o and "schema" in n:
                    self._schema(o["schema"], old_base, n["schema"], new_base, direction, loc, "")

    # -- responses -----------------------------------------------------------

    def _compare_responses(self, old_op: dict[str, Any], old_base: str, new_op: dict[str, Any], new_base: str) -> None:
        old = {str(k).upper(): v for k, v in (old_op.get("responses") or {}).items()}
        new = {str(k).upper(): v for k, v in (new_op.get("responses") or {}).items()}
        for code in sorted(set(old) | set(new)):
            label = code.lower() if code == "DEFAULT" else code
            loc = f"response {label}"
            if code not in new:
                self.add("response-status-removed", BREAKING, f"response {label} removed", loc)
                continue
            if code not in old:
                self.add("response-status-added", NON_BREAKING, f"response {label} added", loc)
                continue
            o, obase = self.old.resolve(old[code], old_base)
            n, nbase = self.new.resolve(new[code], new_base)
            self._compare_content(o.get("content") or {}, obase, n.get("content") or {}, nbase, RESPONSE, loc)
            old_headers = {str(k).lower(): v for k, v in (o.get("headers") or {}).items()}
            new_headers = {str(k).lower(): v for k, v in (n.get("headers") or {}).items()}
            for name in sorted(set(old_headers) - set(new_headers)):
                self.add(
                    "response-header-removed", BREAKING, f"response header {name!r} removed", f"{loc} header {name}"
                )
            for name in sorted(set(old_headers) & set(new_headers)):
                oh, ohb = self.old.resolve(old_headers[name], obase)
                nh, nhb = self.new.resolve(new_headers[name], nbase)
                if isinstance(oh, dict) and isinstance(nh, dict) and "schema" in oh and "schema" in nh:
                    self._schema(oh["schema"], ohb, nh["schema"], nhb, RESPONSE, f"{loc} header {name}", "")

    # -- security --------------------------------------------------------------

    @staticmethod
    def _requirements(spec: Spec, op: dict[str, Any]) -> list[dict[str, frozenset[str]]]:
        raw = op["security"] if "security" in op else spec.root.get("security")
        out = []
        for req in raw or []:
            if isinstance(req, dict):
                out.append({str(k): frozenset(map(str, v or [])) for k, v in req.items()})
        return out

    def _compare_security(self, old_op: dict[str, Any], new_op: dict[str, Any]) -> None:
        old = self._requirements(self.old, old_op)
        new = self._requirements(self.new, new_op)
        old_public = not old or any(not r for r in old)
        new_public = not new or any(not r for r in new)
        if old_public and not new_public:
            names = " or ".join("+".join(sorted(r)) for r in new)
            self.add("security-added", BREAKING, f"operation now requires authentication ({names})", "security")
            return
        if new_public:
            if not old_public:
                self.add("security-removed", INFO, "operation no longer requires authentication", "security")
            return
        new_by_schemes = {frozenset(r): r for r in new}
        old_by_schemes = {frozenset(r): r for r in old}
        for schemes, req in old_by_schemes.items():
            label = "+".join(sorted(schemes))
            match = new_by_schemes.get(schemes)
            if match is None:
                self.add(
                    "security-requirement-removed",
                    BREAKING,
                    f"security requirement {label} removed; clients using it can no longer authenticate",
                    "security",
                )
                continue
            for scheme in sorted(schemes):
                more = sorted(match[scheme] - req[scheme])
                less = sorted(req[scheme] - match[scheme])
                if more:
                    self.add(
                        "security-scope-added", BREAKING, f"{scheme} now requires scopes {', '.join(more)}", "security"
                    )
                if less:
                    self.add(
                        "security-scope-removed",
                        NON_BREAKING,
                        f"{scheme} no longer requires scopes {', '.join(less)}",
                        "security",
                    )
        for schemes in new_by_schemes:
            if schemes not in old_by_schemes:
                label = "+".join(sorted(schemes))
                self.add("security-requirement-added", NON_BREAKING, f"alternative security {label} added", "security")

    def _compare_security_schemes(self) -> None:
        old = ((self.old.root.get("components") or {}).get("securitySchemes")) or {}
        new = ((self.new.root.get("components") or {}).get("securitySchemes")) or {}
        for name in sorted(set(old) & set(new)):
            o, _ = self.old.resolve(old[name])
            n, _ = self.new.resolve(new[name])
            if not isinstance(o, dict) or not isinstance(n, dict):
                continue
            for attr in ("type", "in", "name", "scheme", "openIdConnectUrl"):
                if attr in o and str(o.get(attr, "")).lower() != str(n.get(attr, "")).lower():
                    self.add(
                        "security-scheme-changed",
                        BREAKING,
                        f"security scheme {name!r}: {attr} changed from {_fmt(o.get(attr))} to {_fmt(n.get(attr))}",
                        f"components.securitySchemes.{name}",
                    )
            old_flows, new_flows = o.get("flows") or {}, n.get("flows") or {}
            for flow in sorted(set(old_flows) - set(new_flows)):
                self.add(
                    "security-scheme-changed",
                    BREAKING,
                    f"security scheme {name!r}: OAuth flow {flow} removed",
                    f"components.securitySchemes.{name}",
                )
            for flow in sorted(set(old_flows) & set(new_flows)):
                for attr in ("tokenUrl", "authorizationUrl"):
                    a, b = (old_flows[flow] or {}).get(attr), (new_flows[flow] or {}).get(attr)
                    if a and a != b:
                        self.add(
                            "security-scheme-changed",
                            BREAKING,
                            f"security scheme {name!r}: {flow} {attr} changed from {a!r} to {b!r}",
                            f"components.securitySchemes.{name}",
                        )

    # -- schemas ---------------------------------------------------------------

    def _flatten(self, spec: Spec, node: Any, base: str, depth: int = 0) -> Flat:
        schema, base = spec.resolve(node, base)
        if not isinstance(schema, dict):
            schema = {}
        flat = Flat(raw={}, base=base)
        for key, value in schema.items():
            if key in ("allOf", "properties", "required", "items", "additionalProperties", "oneOf", "anyOf"):
                continue
            flat.raw[key] = value
        for name, prop in (schema.get("properties") or {}).items():
            flat.properties[str(name)] = (prop, base)
        flat.required |= {str(r) for r in schema.get("required") or []}
        if "items" in schema and isinstance(schema["items"], dict):
            flat.items = (schema["items"], base)
        if "additionalProperties" in schema:
            ap = schema["additionalProperties"]
            flat.additional = ap if isinstance(ap, bool) else (ap, base)
        for kw in ("oneOf", "anyOf"):
            if isinstance(schema.get(kw), list):
                flat.variants[kw] = [(v, base) for v in schema[kw]]
        if depth < 32:
            for part in schema.get("allOf") or []:
                sub = self._flatten(spec, part, base, depth + 1)
                for key, value in sub.raw.items():
                    flat.raw.setdefault(key, value)
                for name, prop in sub.properties.items():
                    flat.properties.setdefault(name, prop)
                flat.required |= sub.required
                flat.items = flat.items or sub.items
                if flat.additional is None:
                    flat.additional = sub.additional
                for kw, variants in sub.variants.items():
                    flat.variants.setdefault(kw, variants)
        return flat

    def _schema(
        self, old_node: Any, old_base: str, new_node: Any, new_base: str, direction: str, where: str, ptr: str
    ) -> None:
        old_resolved, _ = self.old.resolve(old_node, old_base)
        new_resolved, _ = self.new.resolve(new_node, new_base)
        scope = f"{self._method} {self._path} {direction}"
        key = (id(old_resolved), id(new_resolved), f"{scope} {where} {ptr}")
        cycle_key = (id(old_resolved), id(new_resolved), scope)
        if key in self._seen or cycle_key in self._seen:
            return
        self._seen.add(key)
        self._seen.add(cycle_key)
        try:
            self._schema_inner(old_node, old_base, new_node, new_base, direction, where, ptr)
        finally:
            self._seen.discard(cycle_key)

    def _loc(self, where: str, ptr: str) -> str:
        return f"{where} {ptr}".strip() if ptr else where

    def _schema_inner(
        self, old_node: Any, old_base: str, new_node: Any, new_base: str, direction: str, where: str, ptr: str
    ) -> None:
        old = self._flatten(self.old, old_node, old_base)
        new = self._flatten(self.new, new_node, new_base)
        loc = self._loc(where, ptr)
        req = direction == REQUEST
        if not self._compare_types(old.raw, new.raw, direction, loc):
            return
        self._compare_enum(old.raw, new.raw, direction, loc)
        self._compare_limits(old.raw, new.raw, direction, loc)
        self._compare_format(old.raw, new.raw, direction, loc)
        if "default" in old.raw and "default" in new.raw and _dump(old.raw["default"]) != _dump(new.raw["default"]):
            self.add(
                "default-changed",
                INFO,
                f"default changed from {_fmt(old.raw['default'])} to {_fmt(new.raw['default'])}",
                loc,
            )
        if req and not old.raw.get("deprecated") and new.raw.get("deprecated") and ptr:
            self.add("property-deprecated", INFO, "property deprecated", loc)

        self._compare_properties(old, new, direction, where, ptr)

        if old.items and new.items:
            self._schema(old.items[0], old.items[1], new.items[0], new.items[1], direction, where, f"{ptr}[]")

        if req:
            old_closed, new_closed = old.additional is False, new.additional is False
            if not old_closed and new_closed:
                self.add(
                    "request-additional-properties-disallowed",
                    BREAKING,
                    "additional properties are no longer allowed",
                    loc,
                )
            elif old_closed and not new_closed:
                self.add(
                    "request-additional-properties-allowed", NON_BREAKING, "additional properties are now allowed", loc
                )
        if isinstance(old.additional, tuple) and isinstance(new.additional, tuple):
            self._schema(
                old.additional[0],
                old.additional[1],
                new.additional[0],
                new.additional[1],
                direction,
                where,
                f"{ptr}{{*}}",
            )

        for kw in ("oneOf", "anyOf"):
            self._compare_variants(kw, old.variants.get(kw), new.variants.get(kw), direction, where, ptr)

    def _compare_types(self, old: dict[str, Any], new: dict[str, Any], direction: str, loc: str) -> bool:
        """Report type changes. Returns False when the change is so big that recursing is noise."""
        old_t, new_t = _types(old), _types(new)
        if old_t == new_t:
            return True
        if old_t is not None and new_t is not None and old_t - {"null"} == new_t - {"null"}:
            gained = "null" in new_t
            msg = "became nullable" if gained else "is no longer nullable"
            if direction == REQUEST:
                sev = NON_BREAKING if gained else BREAKING
            else:
                sev = BREAKING if gained else NON_BREAKING
            self.add(f"{direction}-nullable-{'added' if gained else 'removed'}", sev, msg, loc)
            return True
        msg = f"type changed from {_show_types(old_t)} to {_show_types(new_t)}"
        if direction == REQUEST:
            compatible = new_t is None or (old_t is not None and _covers(new_t, old_t))
            if compatible:
                self.add("request-type-widened", NON_BREAKING, msg, loc)
                return True
        else:
            compatible = old_t is None or (new_t is not None and _covers(old_t, new_t))
            if compatible:
                self.add("response-type-narrowed", NON_BREAKING, msg, loc)
                return True
        self.add(f"{direction}-type-changed", BREAKING, msg, loc)
        return False

    def _compare_enum(self, old: dict[str, Any], new: dict[str, Any], direction: str, loc: str) -> None:
        old_e, new_e = _enum(old), _enum(new)
        if old_e is None and new_e is None:
            return
        if old_e is None:
            assert new_e is not None
            if direction == REQUEST:
                self.add("request-enum-added", BREAKING, "values are now restricted to an enum", loc)
            else:
                self.add("response-enum-added", NON_BREAKING, "values are now restricted to an enum", loc)
            return
        if new_e is None:
            if direction == REQUEST:
                self.add("request-enum-removed", NON_BREAKING, "enum restriction removed", loc)
            else:
                self.add("response-enum-removed", BREAKING, "enum restriction removed; any value may be returned", loc)
            return
        removed = [old_e[k] for k in old_e if k not in new_e]
        added = [new_e[k] for k in new_e if k not in old_e]
        if removed:
            values = ", ".join(_fmt(v) for v in removed)
            if direction == REQUEST:
                self.add("request-enum-value-removed", BREAKING, f"enum value(s) removed: {values}", loc)
            else:
                self.add(
                    "response-enum-value-removed", NON_BREAKING, f"enum value(s) no longer returned: {values}", loc
                )
        if added:
            values = ", ".join(_fmt(v) for v in added)
            if direction == REQUEST:
                self.add("request-enum-value-added", NON_BREAKING, f"enum value(s) added: {values}", loc)
            else:
                self.add(
                    "response-enum-value-added",
                    BREAKING,
                    f"new enum value(s) may be returned: {values}; clients with exhaustive handling may break",
                    loc,
                )

    def _limit(self, schema: dict[str, Any], keyword: str) -> Any:
        value = schema.get(keyword)
        # OpenAPI 3.1 / JSON Schema 2020-12 numeric exclusive bounds
        exclusive = schema.get("exclusiveMaximum" if keyword == "maximum" else "exclusiveMinimum")
        if keyword in ("maximum", "minimum") and isinstance(exclusive, int | float) and not isinstance(exclusive, bool):
            return exclusive if value is None else value
        return value

    def _compare_limits(self, old: dict[str, Any], new: dict[str, Any], direction: str, loc: str) -> None:
        narrowed: list[str] = []
        widened: list[str] = []
        for keyword, kind in LIMITS.items():
            a, b = self._limit(old, keyword), self._limit(new, keyword)
            if a == b or not _num(a, b):
                continue
            if a is None:
                narrowed.append(f"{keyword} {b} added")
            elif b is None:
                widened.append(f"{keyword} {a} removed")
            elif (kind == "max" and b < a) or (kind == "min" and b > a):
                narrowed.append(f"{keyword} {a} -> {b}")
            else:
                widened.append(f"{keyword} {a} -> {b}")
        for flag in ("exclusiveMaximum", "exclusiveMinimum"):
            a, b = old.get(flag), new.get(flag)
            if isinstance(a, bool) or isinstance(b, bool):  # OpenAPI 3.0 boolean form
                if not a and b is True:
                    narrowed.append(f"{flag} added")
                elif a is True and not b:
                    widened.append(f"{flag} removed")
        if not old.get("uniqueItems") and new.get("uniqueItems"):
            narrowed.append("uniqueItems added")
        elif old.get("uniqueItems") and not new.get("uniqueItems"):
            widened.append("uniqueItems removed")
        for keyword in RESTRICTIONS:
            a, b = old.get(keyword), new.get(keyword)
            if a == b:
                continue
            if a is None:
                narrowed.append(f"{keyword} {_fmt(b)} added")
            elif b is None:
                widened.append(f"{keyword} {_fmt(a)} removed")
            else:
                narrowed.append(f"{keyword} changed from {_fmt(a)} to {_fmt(b)}")
        if direction == REQUEST:
            if narrowed:
                self.add(
                    "request-constraint-narrowed", BREAKING, "accepted values narrowed: " + "; ".join(narrowed), loc
                )
            if widened:
                self.add(
                    "request-constraint-widened", NON_BREAKING, "accepted values widened: " + "; ".join(widened), loc
                )
        else:
            if widened:
                self.add(
                    "response-constraint-widened",
                    NON_BREAKING,
                    "returned values may be wider: " + "; ".join(widened),
                    loc,
                )
            if narrowed:
                self.add("response-constraint-narrowed", INFO, "returned values narrowed: " + "; ".join(narrowed), loc)

    def _compare_format(self, old: dict[str, Any], new: dict[str, Any], direction: str, loc: str) -> None:
        a, b = old.get("format"), new.get("format")
        if a == b:
            return
        msg = (
            f"format changed from {_fmt(a)} to {_fmt(b)}"
            if a and b
            else (f"format {_fmt(b)} added" if b else f"format {_fmt(a)} removed")
        )
        widening = (direction == REQUEST and b is None) or (direction == RESPONSE and a is None)
        if widening:
            self.add(
                f"{direction}-format-relaxed" if b is None else f"{direction}-format-added", NON_BREAKING, msg, loc
            )
        else:
            self.add(f"{direction}-format-changed", BREAKING, msg, loc)

    def _compare_properties(self, old: Flat, new: Flat, direction: str, where: str, ptr: str) -> None:
        req = direction == REQUEST
        names = sorted(set(old.properties) | set(new.properties) | old.required | new.required)
        for name in names:
            child = f"{ptr}.{name}" if ptr else name
            loc = self._loc(where, child)
            in_old, in_new = name in old.properties, name in new.properties
            old_req, new_req = name in old.required, name in new.required
            new_prop = self._raw(self.new, new.properties[name]) if in_new else {}
            old_prop = self._raw(self.old, old.properties[name]) if in_old else {}
            if req and (new_prop.get("readOnly") or old_prop.get("readOnly")):
                continue
            if not req and (new_prop.get("writeOnly") or old_prop.get("writeOnly")):
                continue
            if in_old and not in_new and not new_req:
                if req:
                    sev = BREAKING if new.additional is False else INFO
                    self.add("request-property-removed", sev, f"property {name!r} removed", loc)
                else:
                    self.add("response-property-removed", BREAKING, f"property {name!r} removed", loc)
                continue
            if in_new and not in_old and not old_req:
                if req and new_req:
                    self.add("request-property-required-added", BREAKING, f"new required property {name!r}", loc)
                elif req:
                    self.add("request-property-added", NON_BREAKING, f"new optional property {name!r}", loc)
                else:
                    self.add("response-property-added", NON_BREAKING, f"new property {name!r}", loc)
                continue
            if not old_req and new_req:
                if req:
                    self.add("request-property-became-required", BREAKING, f"property {name!r} became required", loc)
                else:
                    self.add(
                        "response-property-became-required",
                        NON_BREAKING,
                        f"property {name!r} is now always returned",
                        loc,
                    )
            elif old_req and not new_req:
                if req:
                    self.add(
                        "request-property-became-optional", NON_BREAKING, f"property {name!r} became optional", loc
                    )
                else:
                    self.add(
                        "response-property-became-optional",
                        BREAKING,
                        f"property {name!r} is no longer always returned",
                        loc,
                    )
            if in_old and in_new:
                (o, ob), (n, nb) = old.properties[name], new.properties[name]
                self._schema(o, ob, n, nb, direction, where, child)

    def _raw(self, spec: Spec, prop: tuple[Any, str]) -> dict[str, Any]:
        node, _ = spec.resolve(prop[0], prop[1])
        return node if isinstance(node, dict) else {}

    @staticmethod
    def _variant_label(node: Any, index: int) -> str:
        if isinstance(node, dict):
            if isinstance(node.get("$ref"), str):
                return node["$ref"].rsplit("/", 1)[-1]
            if node.get("title"):
                return str(node["title"])
        return f"#{index}"

    def _compare_variants(
        self,
        kw: str,
        old: list[tuple[Any, str]] | None,
        new: list[tuple[Any, str]] | None,
        direction: str,
        where: str,
        ptr: str,
    ) -> None:
        if not old or not new:
            return
        old_map = {self._variant_label(v[0], i): v for i, v in enumerate(old)}
        new_map = {self._variant_label(v[0], i): v for i, v in enumerate(new)}
        loc = self._loc(where, ptr)
        for label in old_map:
            if label in new_map:
                (o, ob), (n, nb) = old_map[label], new_map[label]
                self._schema(o, ob, n, nb, direction, where, f"{ptr}<{kw}:{label}>")
            elif direction == REQUEST:
                self.add(f"request-{kw.lower()}-option-removed", BREAKING, f"{kw} option {label} removed", loc)
            else:
                self.add(f"response-{kw.lower()}-option-removed", NON_BREAKING, f"{kw} option {label} removed", loc)
        for label in new_map:
            if label not in old_map:
                if direction == REQUEST:
                    self.add(f"request-{kw.lower()}-option-added", NON_BREAKING, f"{kw} option {label} added", loc)
                else:
                    self.add(
                        f"response-{kw.lower()}-option-added",
                        BREAKING,
                        f"{kw} option {label} added; clients may receive a shape they do not know",
                        loc,
                    )


def _num(*values: Any) -> bool:
    return all(v is None or (isinstance(v, int | float) and not isinstance(v, bool)) for v in values)


def compare(old: Spec, new: Spec) -> list[Finding]:
    """Return every difference between ``old`` and ``new``, most severe first."""
    return Differ(old, new).run()
