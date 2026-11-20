from pathlib import Path

import httpx
import pytest

from openapi_diff_check.diff import compare
from openapi_diff_check.loader import Resolver, SpecError, load_spec, pointer, spec_from_dict, to_uri

SPECS = Path(__file__).parent / "fixtures" / "specs"

PET_YAML = """\
Pet:
  type: object
  properties:
    id: {type: integer}
"""

REMOTE_SPEC = """\
openapi: 3.0.3
info: {title: Remote, version: "1"}
paths:
  /pets:
    get:
      responses:
        "200":
          description: OK
          content:
            application/json:
              schema: {$ref: "./pet.yaml#/Pet"}
"""


def fake_web(files: dict[str, str], calls: list[str] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        body = files.get(str(request.url))
        if body is None:
            return httpx.Response(404, text="not found")
        return httpx.Response(200, text=body)

    return httpx.MockTransport(handler)


def test_load_yaml_with_relative_file_refs_and_json():
    old = load_spec(str(SPECS / "petstore-v1.yaml"))
    new = load_spec(str(SPECS / "petstore-v2.json"))
    assert old.version == "3.0.3" and new.root["info"]["version"] == "2.0.0"
    rules = {f.rule for f in compare(old, new)}
    assert {"response-type-changed", "request-property-required-added", "operation-removed"} <= rules


def test_relative_ref_inside_external_file_resolves_against_that_file():
    spec = load_spec(str(SPECS / "petstore-v1.yaml"))
    pet, base = spec.resolve({"$ref": "./components/pet.yaml#/Pet"})
    status, _ = spec.resolve(pet["properties"]["status"], base)
    assert status["enum"] == ["available", "pending", "sold"]


def test_to_uri():
    assert to_uri("https://example.test/a.yaml") == "https://example.test/a.yaml"
    assert to_uri(str(SPECS / "swagger2.yaml")).startswith("file://")


def test_swagger2_and_wrong_versions_are_rejected():
    with pytest.raises(SpecError, match=r"Swagger 2\.0 is not supported"):
        load_spec(str(SPECS / "swagger2.yaml"))
    with pytest.raises(SpecError, match=r"expected 'openapi: 3\.0\.x'"):
        spec_from_dict({"openapi": "4.0.0"})
    with pytest.raises(SpecError, match="not a mapping"):
        spec_from_dict([])  # type: ignore[arg-type]


def test_missing_file_and_invalid_yaml(tmp_path):
    with pytest.raises(SpecError, match="cannot read"):
        load_spec(str(tmp_path / "nope.yaml"))
    bad = tmp_path / "bad.yaml"
    bad.write_text("openapi: [3.0", encoding="utf-8")
    with pytest.raises(SpecError, match="not valid YAML or JSON"):
        load_spec(str(bad))


def test_broken_ref_is_reported():
    old = load_spec(str(SPECS / "broken-ref.yaml"))
    with pytest.raises(SpecError, match="does not exist"):
        compare(old, old)


def test_ref_loop_is_reported():
    spec = load_spec(str(SPECS / "ref-loop.yaml"))
    with pytest.raises(SpecError, match="circular"):
        compare(spec, spec)


def test_remote_refs_are_off_by_default():
    spec = load_spec(str(SPECS / "remote-ref.yaml"))
    with pytest.raises(SpecError, match=r"remote \$ref to https://schemas\.example\.test/pet\.yaml is disabled"):
        compare(spec, spec)


def test_remote_refs_can_be_enabled():
    calls: list[str] = []
    transport = fake_web({"https://schemas.example.test/pet.yaml": PET_YAML}, calls)
    resolver = Resolver(allow_remote=True, transport=transport)
    spec = load_spec(str(SPECS / "remote-ref.yaml"), resolver=resolver)
    assert compare(spec, spec) == []
    assert calls == ["https://schemas.example.test/pet.yaml"]  # fetched once, then cached


def test_spec_from_url_with_relative_refs():
    files = {"https://api.example.test/openapi.yaml": REMOTE_SPEC, "https://api.example.test/pet.yaml": PET_YAML}
    spec = load_spec("https://api.example.test/openapi.yaml", transport=fake_web(files))
    # the main document is explicitly requested; its relative refs are remote and need opting in
    with pytest.raises(SpecError, match="disabled"):
        compare(spec, spec)
    spec = load_spec("https://api.example.test/openapi.yaml", transport=fake_web(files), allow_remote=True)
    assert compare(spec, spec) == []


def test_url_errors():
    with pytest.raises(SpecError, match="HTTP 404"):
        load_spec("https://api.example.test/missing.yaml", transport=fake_web({}))

    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(SpecError, match="cannot fetch"):
        load_spec("https://api.example.test/x.yaml", transport=httpx.MockTransport(boom))


def test_json_pointer_escapes():
    doc = {"paths": {"/pets/{id}": {"get": 1}}, "a~b": [10, 20]}
    assert pointer(doc, "/paths/~1pets~1{id}/get") == 1
    assert pointer(doc, "/a~0b/1") == 20
    assert pointer(doc, "") is doc
    with pytest.raises(SpecError, match="only JSON pointers"):
        pointer(doc, "Pet")
