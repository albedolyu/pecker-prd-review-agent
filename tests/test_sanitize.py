from __future__ import annotations

import json

from api.sanitize import redact_sensitive, redact_text


def test_redact_text_handles_token_key_value_pairs():
    value = "provider failed with access_token=abc1234567890abcdef and token: xyz9876543210abcd"

    redacted = redact_text(value)

    assert "abc1234567890abcdef" not in redacted
    assert "xyz9876543210abcd" not in redacted
    assert redacted.count("[REDACTED_SECRET]") == 2


def test_redact_text_handles_extended_secret_key_value_pairs():
    value = (
        "provider failed with client_secret=clientsecret123456 "
        "secret_key: secretkey123456 refresh_token=refresh123456"
    )

    redacted = redact_text(value)

    assert "clientsecret123456" not in redacted
    assert "secretkey123456" not in redacted
    assert "refresh123456" not in redacted
    assert redacted.count("[REDACTED_SECRET]") == 3


def test_redact_text_handles_authorization_basic_headers():
    value = "gateway failed with Authorization: Basic dXNlcjpwYXNzd29yZA==, retrying"

    redacted = redact_text(value)

    assert "dXNlcjpwYXNzd29yZA==" not in redacted
    assert "Authorization: Basic [REDACTED_SECRET]" in redacted


def test_redact_text_preserves_query_params_after_secret_values():
    value = "https://example.test/callback?api_key=abc1234567890abcdef&workspace=alpha"

    redacted = redact_text(value)

    assert "abc1234567890abcdef" not in redacted
    assert "api_key=[REDACTED_SECRET]" in redacted
    assert "&workspace=alpha" in redacted


def test_redact_sensitive_recurses_through_nested_values():
    payload = {
        "error": "token=abc1234567890abcdef",
        "events": [{"message": "password=supersecret"}],
    }

    serialized = json.dumps(redact_sensitive(payload), ensure_ascii=False)

    assert "abc1234567890abcdef" not in serialized
    assert "supersecret" not in serialized
    assert serialized.count("[REDACTED_SECRET]") == 2


def test_redact_sensitive_redacts_secret_named_fields_with_plain_values():
    payload = {
        "access_token": "abc1234567890abcdef",
        "nested": {"password": "supersecret"},
        "safe": "workspace-alpha",
    }

    redacted = redact_sensitive(payload)
    serialized = json.dumps(redacted, ensure_ascii=False)

    assert "abc1234567890abcdef" not in serialized
    assert "supersecret" not in serialized
    assert redacted["access_token"] == "[REDACTED_SECRET]"
    assert redacted["nested"]["password"] == "[REDACTED_SECRET]"
    assert redacted["safe"] == "workspace-alpha"


def test_redact_sensitive_redacts_cookie_named_fields():
    payload = {
        "cookie": "pecker_session=jwt-header.payload.signature",
        "headers": {"set-cookie": "pecker_session=jwt-header.payload.signature"},
        "safe": "workspace-alpha",
    }

    redacted = redact_sensitive(payload)
    serialized = json.dumps(redacted, ensure_ascii=False)

    assert "jwt-header.payload.signature" not in serialized
    assert redacted["cookie"] == "[REDACTED_SECRET]"
    assert redacted["headers"]["set-cookie"] == "[REDACTED_SECRET]"
    assert redacted["safe"] == "workspace-alpha"


def test_redact_sensitive_redacts_common_secret_header_fields():
    payload = {
        "headers": {
            "x-api-key": "vendor-api-key-value",
            "proxy-authorization": "Basic proxy-user-secret",
            "content-type": "application/json",
        },
    }

    redacted = redact_sensitive(payload)
    serialized = json.dumps(redacted, ensure_ascii=False)

    assert "vendor-api-key-value" not in serialized
    assert "proxy-user-secret" not in serialized
    assert redacted["headers"]["x-api-key"] == "[REDACTED_SECRET]"
    assert redacted["headers"]["proxy-authorization"] == "[REDACTED_SECRET]"
    assert redacted["headers"]["content-type"] == "application/json"


def test_redact_sensitive_redacts_prefixed_api_key_fields():
    payload = {
        "openai_api_key": "openai-api-key-value",
        "vendor-api-key": "vendor-api-key-value",
        "public_key": "safe-public-key-label",
    }

    redacted = redact_sensitive(payload)
    serialized = json.dumps(redacted, ensure_ascii=False)

    assert "openai-api-key-value" not in serialized
    assert "vendor-api-key-value" not in serialized
    assert redacted["openai_api_key"] == "[REDACTED_SECRET]"
    assert redacted["vendor-api-key"] == "[REDACTED_SECRET]"
    assert redacted["public_key"] == "safe-public-key-label"


def test_redact_sensitive_redacts_extended_secret_named_fields():
    payload = {
        "client_secret": "client-secret-value",
        "secret_key": "secret-key-value",
        "refresh_token": "refresh-token-value",
        "safe": "workspace-alpha",
    }

    redacted = redact_sensitive(payload)
    serialized = json.dumps(redacted, ensure_ascii=False)

    assert "client-secret-value" not in serialized
    assert "secret-key-value" not in serialized
    assert "refresh-token-value" not in serialized
    assert redacted["client_secret"] == "[REDACTED_SECRET]"
    assert redacted["secret_key"] == "[REDACTED_SECRET]"
    assert redacted["refresh_token"] == "[REDACTED_SECRET]"
    assert redacted["safe"] == "workspace-alpha"


def test_redact_sensitive_redacts_token_suffix_fields():
    payload = {
        "session_token": "session-token-value",
        "csrf-token": "csrf-token-value",
        "tokens_used": 12,
    }

    redacted = redact_sensitive(payload)
    serialized = json.dumps(redacted, ensure_ascii=False)

    assert "session-token-value" not in serialized
    assert "csrf-token-value" not in serialized
    assert redacted["session_token"] == "[REDACTED_SECRET]"
    assert redacted["csrf-token"] == "[REDACTED_SECRET]"
    assert redacted["tokens_used"] == 12


def test_redact_sensitive_redacts_private_key_values():
    payload = {
        "private_key": "-----BEGIN PRIVATE KEY-----abc123-----END PRIVATE KEY-----",
        "error": "provider failed with private_key=inline-secret-value",
        "public_key": "safe-public-key-label",
    }

    redacted = redact_sensitive(payload)
    serialized = json.dumps(redacted, ensure_ascii=False)

    assert "BEGIN PRIVATE KEY" not in serialized
    assert "inline-secret-value" not in serialized
    assert redacted["private_key"] == "[REDACTED_SECRET]"
    assert redacted["public_key"] == "safe-public-key-label"


def test_redact_text_handles_cookie_headers():
    value = (
        "gateway retry headers Cookie: pecker_session=jwt-header.payload.signature; "
        "Set-Cookie: refresh_token=refresh-secret; Path=/"
    )

    redacted = redact_text(value)

    assert "jwt-header.payload.signature" not in redacted
    assert "refresh-secret" not in redacted
    assert "Cookie: [REDACTED_SECRET]" in redacted
    assert "Set-Cookie: [REDACTED_SECRET]" in redacted


def test_redact_text_handles_json_like_secret_fields():
    value = (
        'provider payload {"access_token": "json-access-token-value", '
        "'client_secret': 'json-client-secret-value', \"safe\": \"workspace-alpha\"}"
    )

    redacted = redact_text(value)

    assert "json-access-token-value" not in redacted
    assert "json-client-secret-value" not in redacted
    assert '"access_token": "[REDACTED_SECRET]"' in redacted
    assert "'client_secret': '[REDACTED_SECRET]'" in redacted
    assert '"safe": "workspace-alpha"' in redacted


def test_redact_text_handles_common_secret_header_lines():
    value = (
        "gateway headers X-API-Key: vendor-api-key-value "
        "Proxy-Authorization: Basic proxy-user-secret"
    )

    redacted = redact_text(value)

    assert "vendor-api-key-value" not in redacted
    assert "proxy-user-secret" not in redacted
    assert "X-API-Key: [REDACTED_SECRET]" in redacted
    assert "Proxy-Authorization: Basic [REDACTED_SECRET]" in redacted


def test_redact_sensitive_handles_aws_secret_access_key():
    payload = {
        "aws_secret_access_key": "aws-secret-access-key-value",
        "error": "provider failed with aws_secret_access_key=inline-aws-secret-value",
        "public_key": "safe-public-key-label",
    }

    redacted = redact_sensitive(payload)
    serialized = json.dumps(redacted, ensure_ascii=False)

    assert "aws-secret-access-key-value" not in serialized
    assert "inline-aws-secret-value" not in serialized
    assert redacted["aws_secret_access_key"] == "[REDACTED_SECRET]"
    assert redacted["public_key"] == "safe-public-key-label"


def test_redact_sensitive_handles_aws_session_token():
    payload = {
        "aws_session_token": "aws-session-token-value",
        "error": "provider failed with aws_session_token=inline-aws-session-token",
        "tokens_used": 18,
    }

    redacted = redact_sensitive(payload)
    serialized = json.dumps(redacted, ensure_ascii=False)

    assert "aws-session-token-value" not in serialized
    assert "inline-aws-session-token" not in serialized
    assert redacted["aws_session_token"] == "[REDACTED_SECRET]"
    assert redacted["tokens_used"] == 18


def test_redact_sensitive_handles_access_key_ids():
    payload = {
        "aws_access_key_id": "AKIAIOSFODNN7EXAMPLE",
        "error": "provider failed with access_key_id=inline-access-key-id",
        "workspace": "alpha",
    }

    redacted = redact_sensitive(payload)
    serialized = json.dumps(redacted, ensure_ascii=False)

    assert "AKIAIOSFODNN7EXAMPLE" not in serialized
    assert "inline-access-key-id" not in serialized
    assert redacted["aws_access_key_id"] == "[REDACTED_SECRET]"
    assert redacted["workspace"] == "alpha"


def test_redact_sensitive_handles_jwt_fields():
    payload = {
        "jwt": "eyJhbGciOiJIUzI1NiJ9.payload.signature",
        "error": "worker failed with jwt=inline.jwt.signature",
        "review_id": "rev_safe",
    }

    redacted = redact_sensitive(payload)
    serialized = json.dumps(redacted, ensure_ascii=False)

    assert "eyJhbGciOiJIUzI1NiJ9.payload.signature" not in serialized
    assert "inline.jwt.signature" not in serialized
    assert redacted["jwt"] == "[REDACTED_SECRET]"
    assert redacted["review_id"] == "rev_safe"
