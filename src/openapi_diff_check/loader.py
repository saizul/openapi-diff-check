"""Load OpenAPI documents from files or URLs and resolve ``$ref`` pointers lazily."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urldefrag, urljoin, urlparse
from urllib.request import url2pathname

import httpx
import yaml

from openapi_diff_check._version import __version__

MAX_BYTES = 20 * 1024 * 1024


class SpecError(Exception):
    """A spec could not be loaded or a reference could not be resolved."""


def _is_url(source: str) -> bool:
    return urlparse(source).scheme in ("http", "https")


def to_uri(source: str) -> str:
    """Turn a path or URL into an absolute URI (``file://`` for local paths)."""
    if _is_url(source) or source.startswith("file://"):
        return source
    return Path(source).expanduser().resolve().as_uri()


def parse_text(text: str, where: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        pass
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SpecError(f"{where}: not valid YAML or JSON: {exc}") from exc


class Resolver:
    """Fetches documents on demand and follows ``$ref`` chains.

    Local references (``#/components/...``) always work. References to other local files
    work for specs loaded from disk. References to ``http(s)`` documents other than the one
    explicitly requested need ``allow_remote=True``.
    """

    def __init__(
        self, *, allow_remote: bool = False, transport: httpx.BaseTransport | None = None, timeout: float = 30
    ):
        self.allow_remote = allow_remote
        self._transport = transport
        self._timeout = timeout
        self._docs: dict[str, Any] = {}

    def fetch(self, uri: str, *, explicit: bool = False) -> Any:
        if uri in self._docs:
            return self._docs[uri]
        scheme = urlparse(uri).scheme
        if scheme in ("http", "https"):
            if not (explicit or self.allow_remote):
                raise SpecError(f"remote $ref to {uri} is disabled; pass --remote-refs on to allow it")
            text = self._get(uri)
        elif scheme == "file":
            path = Path(url2pathname(unquote(urlparse(uri).path)))
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise SpecError(f"cannot read {path}: {exc.strerror or exc}") from exc
        else:
            raise SpecError(f"unsupported reference scheme in {uri}")
        doc = parse_text(text, uri)
        self._docs[uri] = doc
        return doc

    def _get(self, url: str) -> str:
        headers = {
            "User-Agent": f"openapi-diff-check/{__version__}",
            "Accept": "application/json, application/yaml, */*",
        }
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout, follow_redirects=True) as client:
                response = client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise SpecError(f"cannot fetch {url}: {exc}") from exc
        if response.status_code != 200:
            raise SpecError(f"cannot fetch {url}: HTTP {response.status_code}")
        if len(response.content) > MAX_BYTES:
            raise SpecError(f"{url} is larger than {MAX_BYTES // (1024 * 1024)} MiB")
        return response.text

    def resolve(self, node: Any, base: str) -> tuple[Any, str]:
        """Follow ``$ref`` until a non-reference node is reached. Returns the node and its base URI."""
        seen: set[str] = set()
        while isinstance(node, dict) and isinstance(node.get("$ref"), str):
            target = urljoin(base, node["$ref"])
            if target in seen:
                raise SpecError(f"circular $ref chain at {node['$ref']}")
            seen.add(target)
            doc_uri, fragment = urldefrag(target)
            doc = self.fetch(doc_uri or base)
            node = pointer(doc, fragment, target)
            base = doc_uri or base
        return node, base


def pointer(doc: Any, fragment: str, where: str = "") -> Any:
    """Evaluate a JSON pointer fragment (``/components/schemas/Pet``)."""
    if fragment in ("", "/"):
        return doc
    if not fragment.startswith("/"):
        raise SpecError(f"unsupported $ref fragment {fragment!r} in {where} (only JSON pointers are supported)")
    node = doc
    for raw in fragment[1:].split("/"):
        token = unquote(raw).replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and token in node:
            node = node[token]
        elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
            node = node[int(token)]
        else:
            raise SpecError(f"$ref {where} does not exist")
    return node


class Spec:
    """A loaded OpenAPI document plus the resolver used for its references."""

    def __init__(self, root: dict[str, Any], uri: str, resolver: Resolver):
        self.root = root
        self.uri = uri
        self.resolver = resolver

    @property
    def version(self) -> str:
        return str(self.root.get("openapi", ""))

    def resolve(self, node: Any, base: str | None = None) -> tuple[Any, str]:
        return self.resolver.resolve(node, base or self.uri)


def _check_root(root: Any, where: str) -> dict[str, Any]:
    if not isinstance(root, dict):
        raise SpecError(f"{where}: the document is not a mapping")
    version = str(root.get("openapi", ""))
    if "swagger" in root:
        raise SpecError(f"{where}: Swagger 2.0 is not supported; convert it to OpenAPI 3 first")
    if not (version.startswith("3.0") or version.startswith("3.1")):
        raise SpecError(f"{where}: expected 'openapi: 3.0.x' or '3.1.x', found {version or 'nothing'}")
    return root


def load_spec(
    source: str,
    *,
    allow_remote: bool = False,
    transport: httpx.BaseTransport | None = None,
    resolver: Resolver | None = None,
) -> Spec:
    """Load ``source`` (a path, ``file://`` or ``http(s)://`` URL; ``-`` is not supported)."""
    resolver = resolver or Resolver(allow_remote=allow_remote, transport=transport)
    uri = to_uri(source)
    root = _check_root(resolver.fetch(uri, explicit=True), source)
    return Spec(root, uri, resolver)


def spec_from_dict(root: dict[str, Any], uri: str = "memory://spec") -> Spec:
    """Wrap an in-memory document (used by tests and the Python API)."""
    resolver = Resolver()
    resolver._docs[uri] = root
    return Spec(_check_root(root, uri), uri, resolver)
