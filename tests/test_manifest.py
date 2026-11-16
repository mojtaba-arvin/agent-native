import pytest

from agent_native.manifest import ManifestError, validate_manifest

VALID = {
    "schema_version": "1",
    "name": "orders-api",
    "version": "0.1.0",
    "entrypoint": "main:app",
    "operations": [
        {"id": "orders.list", "method": "GET", "path": "/orders", "summary": "List orders"}
    ],
}


def test_valid_manifest_is_accepted():
    validate_manifest(VALID)


@pytest.mark.parametrize("change", [
    {"schema_version": "2"},
    {"name": "Orders"},
    {"version": "latest"},
    {"entrypoint": "../main:app"},
    {"operations": [{"id": "orders.list", "method": "TRACE", "path": "/orders", "summary": "List"}]},
    {"operations": [{"id": "orders.list", "method": "GET", "path": "/orders", "summary": "List"}, {"id": "orders.list", "method": "POST", "path": "/orders", "summary": "Create"}]},
])
def test_invalid_manifest_is_rejected(change):
    candidate = {**VALID, **change}
    with pytest.raises(ManifestError):
        validate_manifest(candidate)
