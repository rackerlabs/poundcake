"""Unit tests for shared HMAC helpers."""

from shared.hmac import (
    build_hmac_signing_payload,
    canonical_json_body,
    hmac_sha256_hex,
    sha256_hex,
)


def test_canonical_json_body_is_stable() -> None:
    payload = {"b": 2, "a": 1}
    assert canonical_json_body(payload) == '{"a":1,"b":2}'
    assert canonical_json_body(None) == ""


def test_build_hmac_signing_payload_includes_body_hash() -> None:
    payload = build_hmac_signing_payload(
        "1700000000",
        "post",
        "/api/v1/communications",
        b'{"a":1}',
    )
    assert payload == (
        "1700000000\nPOST\n/api/v1/communications\n"
        "015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862"
    )


def test_hmac_sha256_hex_is_deterministic() -> None:
    digest = hmac_sha256_hex("secret", "payload")
    assert digest == "b82fcb791acec57859b989b430a826488ce2e479fdf92326bd0a2e8375a42ba4"
    assert sha256_hex(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
