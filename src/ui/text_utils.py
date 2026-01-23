# src/ui/text_utils.py
### Modules importation
import re
from difflib import SequenceMatcher
import unicodedata

_FR = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
    "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10,
    "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15,
    "seize": 16, "dix-sept": 17, "dix sept": 17, "dix-huit": 18, "dix huit": 18,
    "dix-neuf": 19, "dix neuf": 19, "vingt": 20,
    "vingt et un": 21, "vingt-et-un": 21,
    "vingt deux": 22, "vingt-deux": 22,
    "vingt trois": 23, "vingt-trois": 23,
    "vingt quatre": 24, "vingt-quatre": 24,
    "vingt cinq": 25, "vingt-cinq": 25,
    "vingt six": 26, "vingt-six": 26,
    "vingt sept": 27, "vingt-sept": 27,
    "vingt huit": 28, "vingt-huit": 28,
    "vingt neuf": 29, "vingt-neuf": 29,
    "trente": 30
}

_EN = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

### ------------------------------ Helpers ------------------------------ ###
### Helper : _strip_accents()
def _strip_accents(s: str) -> str:
    """
    Remove diacritical marks from a Unicode string.

    This function normalizes the string using NFD decomposition
    and removes all non-spacing marks.

    :param str s: Input string potentially containing accented characters
    :return str: Accent-free version of the input string
    """
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

### Helper : _parse_int()
def _parse_int(text: str):
    """
    Extract the first integer (1–2 digits) found in a text.

    :param str text: Input text potentially containing a number
    :return Optional[int]: Extracted integer value, or None if no number is found
    """
    t = (text or "").strip().lower()
    if not t:
        return None

    ### Digits
    m = re.search(r"\b(\d{1,3})\b", t)
    if m:
        return int(m.group(1))

    ### Words
    t2 = _strip_accents(t)
    tokens = re.findall(r"[a-z]+", t2)

    for tok in tokens:
        if tok in _FR:
            return _FR[tok]
        if tok in _EN:
            return _EN[tok]

    ### Case : simple compound numbers
    joined = " ".join(tokens)
    joined = joined.replace("-", " ")
    if "vingt" in tokens:
        for tok in tokens:
            if tok in _FR and _FR[tok] < 10:
                return 20 + _FR[tok]

    return None

### Helper : _parse_n_cards()
def _parse_n_cards(text: str, default: int = 8) -> int:
    """
    Extract and clamp the number of flashcards requested by the user.

    :param str text: User message
    :param int default: Default number of cards if none is found
    :return int: Number of cards to generate between 1 and 30
    """
    m = re.search(r"\b(\d{1,2})\b", text or "")
    if not m:
        return default
    n = int(m.group(1))
    return max(1, min(30, n))

### Helper : _normalize_tags()
def _normalize_tags(tags):
    """
    Normalize tags input into a clean list of strings.

    Tags may be provided as a string, a list, or other loosely
    structured input. This function ensures a consistent
    list-of-strings representation.

    :param tags: Raw tags input (string, list, or None)
    :return List[str]: Cleaned list of non-empty tag strings
    """
    if not tags:
        return []

    if isinstance(tags, str):
        ### Comma-separated string
        return [t.strip() for t in tags.split(",") if t.strip()]

    if isinstance(tags, list):
        out = []
        for t in tags:
            if t is None:
                continue
            s = str(t).strip()
            if s:
                out.append(s)
        return out

    ### Fallback : convert to string
    s = str(tags).strip()
    return [s] if s else []

### Helper : _normalize_grade()
def _normalize_grade(text: str) -> str:
    """
    Normalize a free-form grade expression into a standard label.

    Supports both English and French synonyms.
    :param str text: User-provided grade text
    :return str: One of "Again" "Hard" "Good" "Easy" or empty string if unknown
    """
    t = (text or "").strip().lower()
    if t in {"again", "encore"}:
        return "Again"
    if t in {"hard", "dur"}:
        return "Hard"
    if t in {"good", "bien", "ok"}:
        return "Good"
    if t in {"easy", "facile"}:
        return "Easy"
    return ""

### Helper : _label_to_quality_text()
def _label_to_quality_text(s: str) -> str:
    """
    Infer a grading label from free-form text.

    :param str s: User message
    :return str: One of "Again" "Hard" "Good" "Easy" or empty string
    """
    s = (s or "").strip().lower()
    if "again" in s or "encore" in s:
        return "Again"
    if "hard" in s or "dur" in s:
        return "Hard"
    if "easy" in s or "facile" in s:
        return "Easy"
    if "good" in s or "bien" in s or "ok" in s:
        return "Good"
    return ""

### Helper : _extract_source_text()
def _extract_source_text(msg: str) -> str:
    """
    Extract a source text block from a user message.

    :param str msg: User message
    :return str: Extracted source text or empty string if none is found
    """
    msg = msg or ""
    triple = re.search(r'"""([\s\S]+?)"""', msg)
    if triple:
        return triple.group(1).strip()
    code = re.search(r"```([\s\S]+?)```", msg)
    if code:
        return code.group(1).strip()
    return ""

### Helper : _similarity()
def _similarity(a: str, b: str) -> float:
    """
    Compute a rough textual similarity score between two strings.

    Uses SequenceMatcher ratio as a lightweight heuristic.
    :param str a: First string
    :param str b: Second string
    :return float: Similarity score
    """
    a = (a or "").strip().lower()
    b = (b or "").strip().lower()
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()

### Helper : _strip_md()
def _strip_md(text: str) -> str:
    """
    Remove basic Markdown formatting from a text string.

    This function strips common Markdown elements such as:
    - inline code blocks,
    - bold and italic markers,
    - heading markers.

    It is intended as a lightweight cleanup utility, not a full
    Markdown parser.

    :param str text: Input text possibly containing Markdown formatting
    :return str: Cleaned text without Markdown syntax
    """
    t = text or ""

    ### Remove inline and fenced code blocks
    t = re.sub(r"`{1,3}.*?`{1,3}", "", t, flags=re.S)

    ### Remove bold and italic markers while keeping content
    t = re.sub(r"\*\*(.*?)\*\*", r"\1", t)
    t = re.sub(r"\*(.*?)\*", r"\1", t)

    ### Remove heading markers
    t = re.sub(r"#+\s*", "", t)
    return t.strip()

### Helper _add_turn()
def _add_turn(history, user_text, bot_text):
    """
    Append a user / assistant turn to the chat history.

    :param history: Current chat history
    :param user_text: User message
    :param bot_text: Assistant response
    :return: Updated history
    """
    history = history or []
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": bot_text})
    return history
