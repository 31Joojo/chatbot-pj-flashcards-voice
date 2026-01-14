# tests/test_json_extract.py
### Modules importation
import pytest
from src.llm.generate_cards import _extract_json

### Function : test_extract_json_plain()
def test_extract_json_plain():
    """
    Verify that valid JSON is correctly parsed
    when provided without additional text.
    """
    d = _extract_json('{"cards":[{"question":"Q","answer":"A"}]}')
    assert "cards" in d and len(d["cards"]) == 1


### Function : test_extract_json_wrapped()
def test_extract_json_wrapped():
    """
    Verify that the function can extract a JSON block
    surrounded by unstructured text.
    """
    d = _extract_json('bla bla {"cards":[{"question":"Q","answer":"A"}]} fin')
    assert d["cards"][0]["question"] == "Q"


### Function : test_extract_json_invalid()
def test_extract_json_invalid():
    """
    Verify that an exception is thrown when no
    valid JSON can be extracted.
    """
    with pytest.raises(Exception):
        _extract_json("not json")
