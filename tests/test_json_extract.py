# tests/test_json_extract.py
### Modules importation
import pytest
from src.llm.generate_cards import _extract_json

### Function : test_extract_json_plain()
def test_extract_json_plain():
    d = _extract_json('{"cards":[{"question":"Q","answer":"A"}]}')
    assert "cards" in d and len(d["cards"]) == 1

### Function : test_extract_json_wrapped()
def test_extract_json_wrapped():
    d = _extract_json('bla bla {"cards":[{"question":"Q","answer":"A"}]} fin')
    assert d["cards"][0]["question"] == "Q"

### Function : test_extract_json_invalid()
def test_extract_json_invalid():
    with pytest.raises(Exception):
        _extract_json("not json")
