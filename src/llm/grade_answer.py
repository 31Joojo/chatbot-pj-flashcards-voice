# src/llm/grade_answer.py
### Modules importation
import requests
import json

from src.llm.prompts import GRADE_PROMPT, EXPLAIN_PROMPT

### ----------------------------- Functions ----------------------------- ###
### Function : grade_with_ollama()
def grade_with_ollama(question: str, expected: str, student: str, model: str) -> dict:
    """
    Automatically grade a user's answer using an LLM.

    The model is instructed to return a strict JSON object containing grade, confidence, and short feedback

    :param str question: Flashcard question
    :param str expected: Expected answer
    :param str student: Student's answer
    :param str model: Ollama model name
    :return dict: Parsed JSON grading result
    """
    prompt = GRADE_PROMPT.format(
        question=question.strip(),
        expected=expected.strip(),
        student=student.strip(),
    )

    r = requests.post(
        "http://127.0.0.1:11434/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=120,
    )
    r.raise_for_status()
    out = r.json().get("response", "").strip()

    return json.loads(out)

### Function : explain_with_ollama()
def explain_with_ollama(question: str, expected: str, student: str, model: str) -> str:
    """
    Generate a short pedagogical explanation using an LLM.

    :param str question: Flashcard question
    :param str expected: Expected answer
    :param str student: Student's answer
    :param str model: Ollama model name
    :return str: Plain-text explanation
    """
    prompt = EXPLAIN_PROMPT.format(
        question=question.strip(),
        expected=expected.strip(),
        student=student.strip(),
    )
    r = requests.post(
        "http://127.0.0.1:11434/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=120,
    )
    r.raise_for_status()
    return (r.json().get("response") or "").strip()