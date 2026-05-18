import json
from unittest.mock import MagicMock

import pytest

from src.two_bot.claim_extractor import extract_claims


@pytest.fixture
def mock_gemini(monkeypatch):
    import src.two_bot.claim_extractor as claim_extractor

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    mock = MagicMock()
    monkeypatch.setattr(claim_extractor, "_call_gemini", mock)
    return mock


def test_extract_claims_returns_list(mock_gemini):
    mock_gemini.return_value = json.dumps(
        [
            {"text": "361 MW", "kind": "number"},
            {"text": "Mali", "kind": "named_entity"},
            {"text": "Spider-Man 2002", "kind": "era_anchor"},
        ]
    )

    claims = extract_claims("Mali fire is 361 MW. Spider-Man 2002 was the era.")

    assert len(claims) == 3
    assert claims[2].kind == "era_anchor"
    assert claims[2].text == "Spider-Man 2002"


def test_extract_claims_accepts_fenced_preamble_response(mock_gemini):
    mock_gemini.return_value = """Here is the JSON:

```json
[
  {"text": "361 MW", "kind": "number"},
  {"text": "Mali", "kind": "named_entity"}
]
```
"""

    claims = extract_claims("Mali fire is 361 MW.")

    assert [claim.text for claim in claims] == ["361 MW", "Mali"]


def test_extract_claims_raises_on_invalid_json(mock_gemini):
    mock_gemini.side_effect = ["not json", "still not json"]

    with pytest.raises(ValueError, match="invalid JSON across"):
        extract_claims("anything")
    assert mock_gemini.call_count == 2


def test_extract_claims_retries_on_invalid_json(mock_gemini):
    mock_gemini.side_effect = [
        "not json",
        json.dumps([{"text": "361 MW", "kind": "number"}]),
    ]

    claims = extract_claims("Mali fire is 361 MW.")

    assert [claim.text for claim in claims] == ["361 MW"]
    assert mock_gemini.call_count == 2


def test_extract_claims_retry_passes_contract_reminder_suffix(mock_gemini):
    mock_gemini.side_effect = [
        "",
        json.dumps([{"text": "Mali", "kind": "named_entity"}]),
    ]

    extract_claims("Mali fire.")

    assert mock_gemini.call_args_list[0].kwargs.get("retry_suffix", "") == ""
    assert "JSON-output retry" in mock_gemini.call_args_list[1].kwargs.get("retry_suffix", "")


def test_claim_extractor_prompt_requires_canonical_anchor():
    from src.two_bot.prompts.claim_extract_prompt import CLAIM_EXTRACT_SYSTEM_PROMPT

    assert "SHORTEST substring" in CLAIM_EXTRACT_SYSTEM_PROMPT
    assert "Spider-Man 2002" in CLAIM_EXTRACT_SYSTEM_PROMPT
