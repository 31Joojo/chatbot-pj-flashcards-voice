# app.py
### Modules importation
from pathlib import Path
from typing import Optional, List, Dict, Any
import traceback

import gradio as gr

from src.llm.generate_cards import generate_cards
from src.core.models import FlashcardCreate
from src.core.scheduler import SM2State, sm2_update, next_due
from src.storage.repo import FlashcardRepo


### Setting repo for storing flashcards
DB_PATH = Path("data/flashcards.db")
repo = FlashcardRepo(DB_PATH)

print("RUNNING FILE:", __file__, flush=True)

### Function : _normalize_tags()
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

### Wrapper : grade_again()
def grade_again(cid):
    """Shortcut for grading a card as 'Again'."""
    return grade_card(cid, "Again")

### Wrapper : grade_hard()
def grade_hard(cid):
    """Shortcut for grading a card as 'Hard'."""
    return grade_card(cid, "Hard")

### Wrapper : grade_good()
def grade_good(cid):
    """Shortcut for grading a card as 'Good'."""
    return grade_card(cid, "Good")

### Wrapper : grade_easy()
def grade_easy(cid):
    """Shortcut for grading a card as 'Easy'."""
    return grade_card(cid, "Easy")

### Function : load_due_card()
def load_due_card():
    """
    Load the next flashcard that is due for review.

    :return Tuple[Any, str, str, str]: Card ID, metadata info string, question text, placeholder answer
    """
    due = repo.get_due(limit=1)

    if not due:
        return None, "🎉 No cards due at the moment.", "—", "—"

    card = due[0]
    info = (
        f"Due: {card.due_at.isoformat(timespec='seconds')} | "
        f"EF={card.ease_factor:.2f} | "
        f"Int={card.interval_days}d | "
        f"Rep={card.repetitions}"
    )

    return card.id, info, card.question, "—"

### Function : reveal_answer()
def reveal_answer(card_id):
    """
    Reveal the answer (and optional hint) for a flashcard.

    :param card_id: Identifier of the current flashcard
    :return: Answer text formatted for display
    """
    if not card_id:
        return "—"

    card = repo.get_by_id(int(card_id))
    if not card:
        return "—"

    hint = f"\n\n💡 Hint: {card.hint}" if card.hint else ""
    return f"**Answer:** {card.answer}{hint}"

### Function : _label_to_quality()
def _label_to_quality(label: str) -> int:
    """
    Map a UI grade label to an SM-2 quality score.

    :param label: One of: 'Again', 'Hard', 'Good', 'Easy'
    :return int: Corresponding SM-2 quality value (0–5)
    """
    return {"Again": 1, "Hard": 3, "Good": 4, "Easy": 5}.get(label, 4)

### Function : grade_card()
def grade_card(card_id, grade_label):
    """
    Apply a recall grade to a flashcard and update its review schedule.

    This function:
    - retrieves the flashcard,
    - applies the SM-2 algorithm,
    - updates the database,
    - loads the next due card.

    :param card_id: Identifier of the flashcard being reviewed
    :param grade_label: Recall quality label selected by the user
    :return Tuple[Any, str, str, str]: Updated card ID, status message, next question, metadata info
    """
    if not card_id:
        return None, "❌ Please load a card first.", "—", "—"

    card = repo.get_by_id(int(card_id))
    if not card:
        return None, "❌ Card not found.", "—", "—"

    ### Convert UI label to SM-2 quality score
    q = _label_to_quality(grade_label)

    ### Apply SM-2 update
    new_state = sm2_update(
        SM2State(card.ease_factor, card.interval_days, card.repetitions),
        q
    )
    due_at = next_due(new_state.interval_days)

    ### Persist updated review state
    repo.update_review(
        card_id=card.id,
        ease_factor=new_state.ease_factor,
        interval_days=new_state.interval_days,
        repetitions=new_state.repetitions,
        due_at=due_at,
    )

    ### Load next due card
    next_id, info, question, answer = load_due_card()
    return next_id, f"✅ Graded: {grade_label}", question, info

### Function : create_flashcards_ui()
def create_flashcards_ui(text, n, model):
    try:
        text = (text or "").strip()[:4000]
        if not text:
            return gr.update(value=[]), "❌ Merci de fournir un texte."

        payload = generate_cards(text, n=n, model=model)
        raw_cards = payload.get("cards", []) or []

        cards = []
        for c in raw_cards[: int(n)]:
            q = str(c.get("question", "")).strip()
            a = str(c.get("answer", "")).strip()
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
            return gr.update(value=[]), "❌ Aucune carte exploitable."

        ids = repo.add_cards(cards)

        rows = []
        for i, card in enumerate(cards):
            tags_str = ",".join(_normalize_tags(card.tags))
            rows.append([ids[i], card.question, card.answer, card.hint, tags_str])

            return gr.update(value=rows), f"✅ {len(ids)} carte(s) ajoutée(s)."

    except Exception as e:
        return gr.update(value=[]), f"❌ Erreur: {type(e).__name__}: {e}"


### ------------------------- ###
###   Gradio user interface   ###
### ------------------------- ###

with gr.Blocks(title="Flashcards Voice MVP") as demo:
    gr.Markdown("# 🎧 Flashcards Voice — MVP (Ollama + SQLite + SM-2)")

    with gr.Tab("Créer"):
        model = gr.Textbox(value="qwen2.5:7b-instruct", label="Modèle Ollama")
        n = gr.Slider(3, 20, value=8, step=1, label="Nombre de cartes")
        text = gr.Textbox(lines=10, label="Texte source", placeholder="Colle des notes de cours (anglais OK).")

        btn = gr.Button("Générer & sauvegarder")

        preview = gr.Dataframe(
            headers=["id", "question", "answer", "hint", "tags"],
            datatype=["number", "str", "str", "str", "str"],
            interactive=False,
            label="Aperçu",
        )
        msg = gr.Markdown(value="")

    with gr.Tab("Réviser"):
        card_id = gr.State(value=None)

        btn_load = gr.Button("Charger une carte due")
        info = gr.Markdown()
        question = gr.Markdown("—")
        answer = gr.Markdown("—")
        btn_reveal = gr.Button("Afficher la réponse")

        with gr.Row():
            b_again = gr.Button("Again")
            b_hard = gr.Button("Hard")
            b_good = gr.Button("Good")
            b_easy = gr.Button("Easy")

        btn_load.click(load_due_card, outputs=[card_id, info, question, answer])
        btn_reveal.click(reveal_answer, inputs=[card_id], outputs=[answer])

        b_again.click(grade_again, inputs=[card_id], outputs=[card_id, answer, question, info])
        b_hard.click(grade_hard, inputs=[card_id], outputs=[card_id, answer, question, info])
        b_good.click(grade_good, inputs=[card_id], outputs=[card_id, answer, question, info])
        b_easy.click(grade_easy, inputs=[card_id], outputs=[card_id, answer, question, info])


# Utilise server_port et non port
try:
    demo.launch(
        show_error=True,
        debug=True,
        inline=False # Force l'ouverture dans une vraie fenêtre si besoin
    )
except Exception as e:
    print(f"Erreur lors du lancement : {e}")
