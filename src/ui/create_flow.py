# src/ui/create_flow.py
### Modules importation
from pathlib import Path
import emoji
import gradio as gr

from src.core.models import FlashcardCreate
from src.llm.generate_cards import generate_cards
from src.ui.text_utils import _normalize_tags
from src.storage.repo import FlashcardRepo

### Setting repo for storing flashcards
DB_PATH = Path("data/flashcards.db")
repo = FlashcardRepo(DB_PATH)

### ----------------------------- Functions ----------------------------- ###
### Function : create_flashcards_ui()
def create_flashcards_ui(text, n, model):
    """
    Generate flashcards from a source text and persist them via the UI flow.

    It validates and truncates the input text, calls the LLM to generate
    flashcards, filters invalid results, stores valid flashcards in the
    database, and returns a tabular preview along with a status message.

    :param str text: Source text provided by the user
    :param int n: Number of flashcards to generate
    :param str model: Ollama model name
    :return tuple: Updated Gradio DataFrame and a user-facing status message
    """
    try:
        ### Sanitize and limit input size
        text = (text or "").strip()[:4000]
        if not text:
            return gr.update(value=[]), emoji.emojize(":cross_mark:") + " Merci de fournir un texte."

        ### Call LLM to generate flashcards
        payload = generate_cards(text, n=n, model=model)
        raw_cards = payload.get("cards", []) or []

        cards = []
        for c in raw_cards[: int(n)]:
            q = str(c.get("question", "")).strip()
            a = str(c.get("answer", "")).strip()

            ### Skip incomplete flashcards
            if not q or not a:
                continue

            cards.append(
                FlashcardCreate(
                    question=q,
                    answer=a,
                    hint=str(c.get("hint", "") or "").strip(),
                    tags=_normalize_tags(c.get("tags")),
                    source_text=text,
                )
            )

        if not cards:
            return gr.update(value=[]), emoji.emojize(":cross_mark:") + " Aucune carte exploitable."

        ### Persist flashcards and collect their identifiers
        ids = repo.add_cards(cards)

        ### Build rows for the UI preview table
        rows = []
        for i, card in enumerate(cards):
            tags_str = ",".join(_normalize_tags(card.tags))
            rows.append([ids[i], card.question, card.answer, card.hint, tags_str])

            return gr.update(value=rows), f"{emoji.emojize(':check_mark_button:')} {len(ids)} carte(s) ajoutée(s)."

    except Exception as e:
        ### Always return valid Gradio outputs in case of error
        return gr.update(value=[]), f'{emoji.emojize(":cross_mark:")} Erreur: {type(e).__name__}: {e}'
