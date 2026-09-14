from unittest.mock import Mock

import pytest
import requests

from growr_cli import settings
from growr_cli.providers import ProviderClient


def _client() -> ProviderClient:
    return ProviderClient(timeout_seconds=5, jupiter_api_key="test-key")


def _json_response(payload, ok=True, status_code=200) -> Mock:
    response = Mock()
    response.ok = ok
    response.status_code = status_code
    response.json.return_value = payload
    return response


def test_jupiter_returns_matching_mint_not_first_hit() -> None:
    client = _client()
    client.session.get = Mock(
        return_value=_json_response(
            [
                {"id": "otherMint", "name": "Wrong"},
                {
                    "mint": "ExactMint1111111111111111111111111111111",
                    "name": "Right",
                },
            ]
        )
    )

    token, error = client.get_jupiter_token(
        "ExactMint1111111111111111111111111111111"
    )

    assert error is None
    assert token is not None
    assert token["name"] == "Right"


def test_jupiter_mismatch_is_no_data() -> None:
    client = _client()
    client.session.get = Mock(
        return_value=_json_response([{"id": "someoneElse", "name": "Nope"}])
    )

    token, error = client.get_jupiter_token(
        "ExactMint1111111111111111111111111111111"
    )

    assert token is None
    assert error is None


def test_single_jupiter_id_takes_precedence_over_aliases():
    client = _client()
    client.session.get = Mock(
        return_value=_json_response(
            [
                {"id": "wrong", "mint": "requested", "address": "requested"},
                {"id": "requested", "usdPrice": 0},
            ]
        )
    )
    assert client.get_jupiter_token("requested")[0] == {
        "id": "requested",
        "usdPrice": 0,
    }


def test_jupiter_without_key() -> None:
    client = ProviderClient(timeout_seconds=5, jupiter_api_key=None)
    token, error = client.get_jupiter_token("mint")
    assert token is None
    assert error == "Jupiter API key is not configured"


def test_rugcheck_rejects_non_dict() -> None:
    client = _client()
    client.session.get = Mock(
        return_value=_json_response(["not", "a", "dict"])
    )

    report, error = client.get_rugcheck_report("mint")

    assert report is None
    assert error == "unexpected response shape"


def test_rugcheck_accepts_dict() -> None:
    client = _client()
    client.session.get = Mock(return_value=_json_response({"score": 12}))

    report, error = client.get_rugcheck_report("mint")

    assert error is None
    assert report == {"score": 12}


def test_provider_urls_come_from_settings(monkeypatch) -> None:
    monkeypatch.setattr(
        settings, "RUGCHECK_API_URL", "https://rugcheck.example"
    )
    client = _client()
    client.session.get = Mock(return_value=_json_response({"score": 12}))

    client.get_rugcheck_report("mint")

    client.session.get.assert_called_once_with(
        "https://rugcheck.example/tokens/mint/report",
        params=None,
        headers=None,
        timeout=5,
    )


def test_http_error() -> None:
    client = _client()
    client.session.get = Mock(
        return_value=_json_response({}, ok=False, status_code=503)
    )

    report, error = client.get_rugcheck_report("mint")

    assert report is None
    assert error == "HTTP 503"


def test_request_exception() -> None:
    client = _client()
    client.session.get = Mock(
        side_effect=requests.ConnectionError(
            "https://example.com?api-key=secret-key boom"
        )
    )

    report, error = client.get_rugcheck_report("mint")

    assert report is None
    assert error == "Provider request failed (ConnectionError)"
    assert "secret-key" not in str(error)


def test_enrichment_batches_deduplicate_and_keep_failed_batches():
    size = 100
    client = _client()
    mints = ["mint%s" % i for i in range(size + 1)]
    item = {"id": mints[0]}
    client.session.get = Mock(
        side_effect=[
            _json_response([item]),
            _json_response({}, ok=False, status_code=429),
        ]
    )
    result = client.get_jupiter_tokens([*mints, mints[0]])
    assert list(result) == mints
    assert result[mints[0]].status == "success"
    assert result[mints[1]].status == "no_data"
    assert result[mints[-1]].status == "failed"
    assert result[mints[-1]].detail == "HTTP 429"
    assert client.session.get.call_count == 2
    call = client.session.get.call_args_list[0]
    addresses = call.kwargs["params"]["query"]
    assert len(addresses.split(",")) == size
    assert call.kwargs["timeout"] == 5


def test_batch_jupiter_accepts_only_exact_id():
    client = _client()
    client.session.get = Mock(
        return_value=_json_response(
            [
                {"id": "other", "symbol": "mint", "mint": "mint"},
                {"id": "mint", "holderCount": 0},
            ]
        )
    )
    assert client.get_jupiter_tokens(["mint"])["mint"].data == {
        "id": "mint",
        "holderCount": 0,
    }


@pytest.mark.parametrize("payload", [None, {}, {"pairs": []}, ["bad"]])
def test_batch_malformed_response_is_failed(payload):
    client = _client()
    client.session.get = Mock(return_value=_json_response(payload))
    assert client.get_jupiter_tokens(["mint"])["mint"].status == "failed"


def test_missing_jupiter_key_and_empty_batches_make_no_requests():
    client = ProviderClient(5, None)
    client.session.get = Mock()
    assert (
        client.get_jupiter_tokens(["mint"])["mint"].status == "not_configured"
    )
    assert client.get_jupiter_tokens([]) == {}
    client.session.get.assert_not_called()


@pytest.mark.parametrize(
    "error", [requests.Timeout("secret"), requests.ConnectionError("secret")]
)
def test_batch_transport_errors_are_credential_free(error):
    client = _client()
    client.session.get = Mock(side_effect=error)
    result = client.get_jupiter_tokens(["mint"])["mint"]
    assert result.status == "failed"
    assert "secret" not in result.detail


def test_batch_invalid_json_is_failed():
    client = _client()
    response = _json_response(None)
    response.json.side_effect = ValueError("secret response")
    client.session.get = Mock(return_value=response)
    assert (
        client.get_jupiter_tokens(["mint"])["mint"].detail
        == "Provider returned invalid JSON"
    )
