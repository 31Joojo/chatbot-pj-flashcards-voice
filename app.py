# app.py
### Modules importation
from pathlib import Path
import re
import requests, json
from difflib import SequenceMatcher
import emoji

import gradio as gr

from src.llm.generate_cards import generate_cards
from src.core.models import FlashcardCreate
from src.core.scheduler import SM2State, sm2_update, next_due
from src.storage.repo import FlashcardRepo
from src.llm.prompts import GRADE_PROMPT, EXPLAIN_PROMPT

### Setting repo for storing flashcards
DB_PATH = Path("data/flashcards.db")
repo = FlashcardRepo(DB_PATH)

print("RUNNING FILE:", __file__, flush=True)

### Helper : _parse_int()
def _parse_int(text: str):
    """
    Extract the first integer (1–2 digits) found in a text.

    :param str text: Input text potentially containing a number
    :return Optional[int]: Extracted integer value, or None if no number is found
    """
    m = re.search(r"\b(\d{1,2})\b", text or "")
    return int(m.group(1)) if m else None

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
def load_due_card(source_id: int | None = None):
    """
    Load the next flashcard that is due for review.

    :param Optional[int] source_id: ID of the source text
    :return Tuple[Any, str, str, str]: Card ID, metadata info string, question text, placeholder answer
    """
    due = repo.get_due(limit=1, source_id=source_id)

    if not due:
        return None, emoji.emojize(":party_popper:") + " No cards due at the moment.", "—", "—"

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

    hint = f"\n\n{emoji.emojize(':light_bulb:')} Hint: {card.hint}" if card.hint else ""
    return f"**Answer:** {card.answer}{hint}"

### Helper : _label_to_quality()
def _label_to_quality(label: str) -> int:
    """
    Map a UI grade label to an SM-2 quality score.

    :param label: One of: 'Again', 'Hard', 'Good', 'Easy'
    :return int: Corresponding SM-2 quality value (0–5)
    """
    return {"Again": 1, "Hard": 3, "Good": 4, "Easy": 5}.get(label, 4)

### Function : grade_card()
def grade_card(card_id, grade_label, source_id: int | None = None):
    """
    Apply a recall grade to a flashcard and update its review schedule.

    This function:
    - retrieves the flashcard,
    - applies the SM-2 algorithm,
    - updates the database,
    - loads the next due card.

    :param card_id: Identifier of the flashcard being reviewed
    :param grade_label: Recall quality label selected by the user
    :param source_id: ID of the source text
    :return Tuple[Any, str, str, str]: Updated card ID, status message, next question, metadata info
    """
    if not card_id:
        return None, emoji.emojize(":cross_mark:") + " Please load a card first.", "—", "—"

    card = repo.get_by_id(int(card_id))
    if not card:
        return None, emoji.emojize(":cross_mark:") + " Card not found.", "—", "—"

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
    next_id, info, question, answer = load_due_card(source_id=source_id)
    return next_id, f"{emoji.emojize(':check_mark_button:')} Graded: {grade_label}", question, info

### Function : create_flashcards_ui()
def create_flashcards_ui(text, n, model):
    try:
        text = (text or "").strip()[:4000]
        if not text:
            return gr.update(value=[]), emoji.emojize(":cross_mark:") + " Merci de fournir un texte."

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
            return gr.update(value=[]), emoji.emojize(":cross_mark:") + " Aucune carte exploitable."

        ids = repo.add_cards(cards)

        rows = []
        for i, card in enumerate(cards):
            tags_str = ",".join(_normalize_tags(card.tags))
            rows.append([ids[i], card.question, card.answer, card.hint, tags_str])

            return gr.update(value=rows), f"{emoji.emojize(':check_mark_button:')} {len(ids)} carte(s) ajoutée(s)."

    except Exception as e:
        return gr.update(value=[]), f'{emoji.emojize(":cross_mark:")} Erreur: {type(e).__name__}: {e}'

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

### Function : chat_start()
def chat_start(source_text, model, history, chat_state):
    """
    Initialize a new chat session from a source text.

    This function:
    - validates the source text ;
    - creates a new source entry in the database ;
    - initializes the chat state machine.

    :param source_text: Source text provided by the user
    :param model: Ollama model name
    :param history: Current chat history
    :param chat_state: Chat state machine
    :return: Updated history, chat state, and UI visibility updates
    """
    history = history or []
    chat_state = chat_state or {}

    src = (source_text or "").strip()
    if not src:
        history.append({"role": "assistant", "content": f"{emoji.emojize(':cross_mark:')} Colle un texte source avant de cliquer Start."})
        return history, chat_state, gr.update(visible=True), gr.update(visible=False)

    ### Create a new logical source for the session in the database
    source_id = repo.add_source(source_text=src[:8000], title=None)

    chat_state.update({
        "phase": "need_n",
        "source_text": src[:8000],
        "source_id": source_id,
        "model": (model or "qwen2.5:7b-instruct").strip(),
        "pending_card_id": None,
    })

    history.append({"role": "assistant", "content": emoji.emojize(':check_mark_button:') + " Texte reçu. Combien de cartes veux-tu générer ? (ex: 8)"})

    return history, chat_state, gr.update(visible=False), gr.update(visible=True)

### Function : chat_reset_to_start()
def chat_reset_to_start(chat_state):
    """
    Reset the chat session to its initial state.

    :return: Reset chat state and UI visibility updates
    """
    chat_state = chat_state or {}
    chat_state.update({
        "phase": "idle",
        "source_text": "",
        "pending_card_id": None
    })
    return chat_state, gr.update(visible=True), gr.update(visible=False)

### Function : chat_send()
def chat_send(user_msg, history, chat_state):
    """
     Main chat handler implementing the conversational state machine.

    Depending on the current phase, this function routes the user
    message to :
    - flashcard generation ;
    - quiz answering ;
    - grading ;
    - explanation ;
    - or fallback assistance.

    The chat_state dictionary acts as a finite-state controller.

    :param user_msg: User message
    :param history: Current chat history
    :param chat_state: Chat state machine
    """
    history = history or []
    chat_state = chat_state or {"phase": "idle", "source_text": "", "model": "qwen2.5:7b-instruct", "pending_card_id": None}

    msg = (user_msg or "").strip()
    if not msg:
        return history, chat_state

    phase = chat_state.get("phase", "idle")

    ### ---------- Idle phase ---------- ###
    if phase != "idle":
        sid = chat_state.get("source_id")
        if sid is None:
            history = _add_turn(history, msg, emoji.emojize(":cross_mark:") + " Bug : source_id manquant. Clique sur **Changer de texte** puis Start.")
            chat_state["phase"] = "idle"
            chat_state["pending_card_id"] = None
            return history, chat_state, gr.update(value="")

    ### --------- Need n phase --------- ###
    if phase == "need_n":
        n = _parse_int(msg)
        if not n:
            history = _add_turn(history, msg, "Je n’ai pas compris le nombre. Réponds juste par un nombre (ex: 8).")
            return history, chat_state, gr.update(value="")

        n = max(1, min(30, n))
        source = chat_state.get("source_text", "")
        model = chat_state.get("model", "qwen2.5:7b-instruct")

        try:
            payload = generate_cards(source, n=n, model=model)
            raw = payload.get("cards", []) or []
            cards = []
            for c in raw[:n]:
                q = str(c.get("question", "")).strip()
                a = str(c.get("answer", "")).strip()
                if q and a:
                    cards.append(
                        FlashcardCreate(
                            question=q,
                            answer=a,
                            hint=str(c.get("hint", "") or "").strip(),
                            tags=_normalize_tags(c.get("tags")),
                            source_text=source,
                        )
                    )

            if not cards:
                history = _add_turn(history, msg, emoji.emojize(":cross_mark:") + " Aucune carte exploitable n’a été générée. Réessaie avec un autre texte.")
                return history, chat_state, gr.update(value="")

            repo.add_cards(cards, source_id=chat_state["source_id"])

        except Exception as e:
            history = _add_turn(history, msg, f"{emoji.emojize(':cross_mark:')} Erreur génération: {type(e).__name__}: {e}")
            return history, chat_state, gr.update(value="")

        ### Launch the quizz
        due = repo.get_due(limit=1, source_id=chat_state["source_id"])
        if not due:
            chat_state["phase"] = "idle"
            history = _add_turn(history, msg, f"{emoji.emojize(':check_mark_button:')} {len(cards)} cartes ajoutées. {emoji.emojize(':party_popper:')} Rien à réviser pour l’instant.")
            return history, chat_state, gr.update(value="")

        card = due[0]
        chat_state["pending_card_id"] = card.id
        chat_state["phase"] = "quiz_answer"

        history = _add_turn(history, msg, f"{emoji.emojize(':check_mark_button:')} {len(cards)} cartes ajoutées.\n\n{emoji.emojize(':brain:')} **Question 1 :** {card.question}\n\nRéponds en texte.")
        return history, chat_state, gr.update(value="")

    ### ------- Quiz answer phase ------ ###
    if phase == "quiz_answer":
        cid = chat_state.get("pending_card_id")
        card = repo.get_by_id(int(cid)) if cid else None
        if not card:
            chat_state["phase"] = "idle"
            history = _add_turn(history, msg, emoji.emojize(":cross_mark:") + " Carte introuvable. Clique Start pour recommencer.")
            return history, chat_state, gr.update(value="")

        model = chat_state.get("model", "qwen2.5:7b-instruct")

        lower = msg.lower()
        if any(k in lower for k in ["explique", "je ne sais pas", "aide", "indice", "hint"]):
            model = chat_state.get("model", "qwen2.5:7b-instruct")

            ### Short explanation with Ollama
            try:
                explanation = explain_with_ollama(
                    question=card.question,
                    expected=card.answer,
                    student=msg,
                    model=model,
                )
            except Exception:
                explanation = f"Voici l'idée clé : {card.answer}" + (f"\n\n{emoji.emojize(':light_bulb:')} Hint: {card.hint}" if card.hint else "")

            bot = (
                f"{emoji.emojize(':brain:')} **Explication :** {explanation}\n\n"
                "Tu veux réessayer la **même question** ou passer à la suivante ? (réponds: `réessayer` / `passer`)"
            )
            chat_state["phase"] = "quiz_explain_choice"
            history = _add_turn(history, msg, bot)
            return history, chat_state, gr.update(value="")

        ### Auto-grade with Ollama
        try:
            verdict = grade_with_ollama(card.question, card.answer, msg, model=model)
            label = str(verdict.get("grade", "")).strip()
            conf = float(verdict.get("confidence", 0.0))
            feedback = str(verdict.get("feedback", "")).strip()
        except Exception:
            sim = _similarity(msg, card.answer)
            if sim >= 0.75:
                label, conf, feedback = "Good", sim, "Bonne réponse (similarité élevée)."
            elif sim >= 0.55:
                label, conf, feedback = "Hard", sim, "Partiellement correct, mais incomplet."
            else:
                label, conf, feedback = "Again", sim, "Réponse insuffisante ou incorrecte."

        if label not in {"Again", "Hard", "Good", "Easy"}:
            label = "Hard"

        ### Applying SM-2
        sid = chat_state.get("source_id")
        next_id, status, question, info = grade_card(int(cid), label, source_id=sid)

        ### Prepares output bot
        if next_id is None:
            chat_state["pending_card_id"] = None
            chat_state["phase"] = "idle"
            bot = (
                f"{emoji.emojize(':receipt:')} **Correction**: {card.answer}\n\n"
                f"{emoji.emojize(':robot:')} **Auto-grade**: {label} (conf={conf:.2f})\n"
                f"{emoji.emojize(':speech_balloon:')} {feedback}\n\n"
                f"{emoji.emojize(':party_popper:')} Plus de cartes dues."
            )
            history = _add_turn(history, msg, bot)
            return history, chat_state, gr.update(value="")

        chat_state["pending_card_id"] = next_id
        chat_state["phase"] = "quiz_answer"
        bot = (
            f"{emoji.emojize(':receipt:')} **Correction**: {card.answer}\n\n"
            f"{emoji.emojize(':robot:')} **Auto-grade**: {label} (conf={conf:.2f})\n"
            f"{emoji.emojize(':speech_balloon:')} {feedback}\n\n"
            f"{emoji.emojize(':brain:')} **Question suivante :** {question}\n\nRéponds en texte."
        )
        history = _add_turn(history, msg, bot)
        return history, chat_state, gr.update(value="")

    ### ------- Quiz grade phase ------- ###
    if phase == "quiz_grade":
        label = _normalize_grade(msg)
        if not label:
            history = _add_turn(history, msg, "Je n’ai pas compris. Réponds: Again / Hard / Good / Easy.")
            return history, chat_state, gr.update(value="")

        cid = chat_state.get("pending_card_id")
        if not cid:
            chat_state["phase"] = "idle"
            history = _add_turn(history, msg, emoji.emojize(":cross_mark:") + " Plus de carte en cours. Clique Start pour recommencer.")
            return history, chat_state, gr.update(value="")

        sid = chat_state.get("source_id")
        next_id, status, question, info = grade_card(int(cid), label, source_id=sid)

        if next_id is None:
            chat_state["pending_card_id"] = None
            chat_state["phase"] = "idle"
            history = _add_turn(history, msg, emoji.emojize(':check_mark_button:') + " Noté. " + {emoji.emojize(':party_popper:')} + " Plus de cartes dues.")
            return history, chat_state, gr.update(value="")

        chat_state["pending_card_id"] = next_id
        chat_state["phase"] = "quiz_answer"
        history = _add_turn(history, msg, f"{emoji.emojize(':check_mark_button:')} Noté ({label}).\n\n{emoji.emojize(':brain:')} **Question suivante :** {question}\n\nRéponds en texte.")
        return history, chat_state, gr.update(value="")

    if phase == "quiz_explain_choice":
        choice = msg.strip().lower()

        cid = chat_state.get("pending_card_id")
        card = repo.get_by_id(int(cid)) if cid else None
        if not card:
            chat_state["phase"] = "idle"
            history = _add_turn(history, msg, emoji.emojize(":cross_mark:") + " Carte introuvable. Clique Start pour recommencer.")
            return history, chat_state, gr.update(value="")

        if "réess" in choice or "reess" in choice:
            chat_state["phase"] = "quiz_answer"
            history = _add_turn(history, msg, f"OK ! {emoji.emojize(':brain:')} **Même question :** {card.question}\n\nRéponds en texte.")
            return history, chat_state, gr.update(value="")

        if "pass" in choice or "suiv" in choice:
            sid = chat_state.get("source_id")
            next_id, status, question, info = grade_card(int(cid), "Again", source_id=sid)

            if next_id is None:
                chat_state["phase"] = "idle"
                chat_state["pending_card_id"] = None
                history = _add_turn(history, msg, emoji.emojize(':check_mark_button:') + " OK, on passe. " + {emoji.emojize(':party_popper:')} + " Plus de cartes dues.")
                return history, chat_state, gr.update(value="")

            chat_state["pending_card_id"] = next_id
            chat_state["phase"] = "quiz_answer"
            history = _add_turn(history, msg,
                                f"{emoji.emojize(':check_mark_button:')} OK, on passe.\n\n{emoji.emojize(':brain:')} **Question suivante :** {question}\n\nRéponds en texte.")
            return history, chat_state, gr.update(value="")

        history = _add_turn(history, msg, "Je n’ai pas compris. Réponds: `réessayer` ou `passer`.")
        return history, chat_state, gr.update(value="")

    ### Fallback
    chat_state["phase"] = "idle"
    history = _add_turn(history, msg, "Je me suis perdu 😅 Clique Start pour recommencer.")
    return history, chat_state, gr.update(value="")

### Function : chat_handle()
def chat_handle(user_msg, history, chat_state):
    """
    :param user_msg: User message
    :param history: Chat history
    :param chat_state: Chat state machine
    """
    history = history or []
    chat_state = chat_state or {
        "last_source_text": "",
        "pending_card_id": None,
        "awaiting_answer": False,
        "awaiting_grade": False,
        "model": "qwen2.5:7b-instruct",
    }

    msg = (user_msg or "").strip()
    if not msg:
        return history, chat_state

    ### ----- Command-mode fallback ---- ###
    if msg.startswith("/"):
        cmd = msg.lower().split()

        if cmd[0] == "/review":
            due = repo.get_due(limit=1, source_id=chat_state["source_id"])
            if not due:
                history = _add_turn(history, msg, {emoji.emojize(':party_popper:')} + " Aucune carte due.")
                return history, chat_state

            card = due[0]
            chat_state["pending_card_id"] = card.id
            chat_state["awaiting_answer"] = True
            chat_state["awaiting_grade"] = False

            history = _add_turn(
                history,
                msg,
                f"{emoji.emojize(':brain:')} **Question :** {card.question}\n\nRéponds en message texte."
            )
            return history, chat_state

        if cmd[0] == "/generate":
            n = int(cmd[1]) if len(cmd) > 1 and cmd[1].isdigit() else 8
            source = chat_state.get("last_source_text", "")
            if not source:
                history = _add_turn(
                    history,
                    msg,
                    emoji.emojize(":cross_mark:") + " Je n’ai pas de texte source. Colle ton texte puis demande-moi de générer des cartes."
                )
                return history, chat_state

            payload = generate_cards(source, n=n, model=chat_state["model"])
            raw = payload.get("cards", []) or []

            cards = []
            for c in raw[:n]:
                q = str(c.get("question", "")).strip()
                a = str(c.get("answer", "")).strip()
                if q and a:
                    cards.append(
                        FlashcardCreate(
                            question=q,
                            answer=a,
                            hint=str(c.get("hint", "") or ""),
                            tags=_normalize_tags(c.get("tags")),
                            source_text=source,
                        )
                    )

            if not cards:
                history = _add_turn(history, msg, emoji.emojize(":cross_mark:") + " Aucune carte exploitable générée.")
                return history, chat_state

            repo.add_cards(cards)
            history = _add_turn(history, msg, f"{emoji.emojize(':check_mark_button:')} {len(cards)} cartes ajoutées. Tu veux **réviser** maintenant ?")
            return history, chat_state

        if cmd[0] in ["/again", "/hard", "/good", "/easy"]:
            label = cmd[0].replace("/", "").capitalize()
            cid = chat_state.get("pending_card_id")

            if not cid:
                history = _add_turn(history, msg, emoji.emojize(":cross_mark:") + " Pas de carte en cours. Fais `/review` d’abord.")
                return history, chat_state

            next_id, status, question, info = grade_card(cid, label)
            chat_state["pending_card_id"] = next_id
            chat_state["awaiting_answer"] = next_id is not None
            chat_state["awaiting_grade"] = False

            if next_id is None:
                history = _add_turn(history, msg, emoji.emojize(':check_mark_button:') + " Noté. " + {emoji.emojize(':party_popper:')} + " Plus de cartes dues.")
            else:
                history = _add_turn(history, msg, f"{status}\n\n{emoji.emojize(':brain:')} **Question :** {question}\n\nRéponds en message texte.")
            return history, chat_state

        history = _add_turn(history, msg, "Commande inconnue. Essaye `/generate 8` ou `/review`.")
        return history, chat_state

    ### ---- Natural intent routing ---- ###
    lower = msg.lower()

    ### User pastes source text into the message
    extracted = _extract_source_text(msg)
    if extracted:
        chat_state["last_source_text"] = extracted
        history = _add_turn(history, msg, emoji.emojize(':check_mark_button:') + " Texte reçu. Dis-moi : *“Génère 8 cartes”* ou *“On révise”*.")
        return history, chat_state

    ### Waiting for a grade
    if chat_state.get("awaiting_grade"):
        label = _label_to_quality_text(msg)
        if not label:
            history = _add_turn(history, msg, "Je n’ai pas compris la note. Réponds: Again / Hard / Good / Easy.")
            return history, chat_state

        cid = chat_state.get("pending_card_id")
        next_id, status, question, info = grade_card(cid, label)

        chat_state["pending_card_id"] = next_id
        chat_state["awaiting_answer"] = next_id is not None
        chat_state["awaiting_grade"] = False

        if next_id is None:
            history = _add_turn(history, msg, emoji.emojize(':check_mark_button:') + " Noté. " + {emoji.emojize(':party_popper:')} + " Plus de cartes dues.")
        else:
            history = _add_turn(
                history,
                msg,
                f"{status}\n\n{emoji.emojize(':brain:')} **Question :** {question}\n\nRéponds en texte."
            )
        return history, chat_state

    ### Waiting for a reply to a card
    if chat_state.get("awaiting_answer"):
        cid = chat_state.get("pending_card_id")
        card = repo.get_by_id(int(cid)) if cid else None

        if not card:
            chat_state["awaiting_answer"] = False
            history = _add_turn(history, msg, emoji.emojize(":cross_mark:") + " Carte introuvable. Dis *“On révise”* pour reprendre.")
            return history, chat_state

        sim = _similarity(msg, card.answer)
        bot = (
            emoji.emojize(':check_mark_button:') + " J’ai noté ta réponse.\n\n"
            f"**Réponse attendue :** {card.answer}\n\n"
            f"Ta ressemblance approx: `{sim:.2f}`\n\n"
            "Note-toi : Again / Hard / Good / Easy"
        )

        chat_state["awaiting_answer"] = False
        chat_state["awaiting_grade"] = True

        history = _add_turn(history, msg, bot)
        return history, chat_state

    ### Intent review
    if any(k in lower for k in ["révise", "revision", "quiz", "interro", "on révise"]):
        due = repo.get_due(limit=1, source_id=chat_state["source_id"])
        if not due:
            history = _add_turn(history, msg, f"{emoji.emojize(':party_popper:')} Aucune carte due. Tu peux me demander de générer des cartes à partir d’un texte.")
            return history, chat_state

        card = due[0]
        chat_state["pending_card_id"] = card.id
        chat_state["awaiting_answer"] = True
        chat_state["awaiting_grade"] = False

        history = _add_turn(history, msg, f"{emoji.emojize(':brain:')} **Question :** {card.question}\n\nRéponds en texte.")
        return history, chat_state

    ### Intent generate
    if any(k in lower for k in ["génère", "genere", "crée", "cree", "flashcard", "carte"]):
        n = _parse_n_cards(msg, default=8)
        source = chat_state.get("last_source_text", "")

        if not source:
            history = _add_turn(
                history,
                msg,
                emoji.emojize(":cross_mark:") + " Colle d’abord ton texte (tu peux le mettre entre ``` ```), puis demande *“Génère 8 cartes”*."
            )
            return history, chat_state

        payload = generate_cards(source, n=n, model=chat_state["model"])
        raw = payload.get("cards", []) or []

        cards = []
        for c in raw[:n]:
            q = str(c.get("question", "")).strip()
            a = str(c.get("answer", "")).strip()
            if q and a:
                cards.append(
                    FlashcardCreate(
                        question=q,
                        answer=a,
                        hint=str(c.get("hint", "") or ""),
                        tags=_normalize_tags(c.get("tags")),
                        source_text=source,
                    )
                )

        if not cards:
            history = _add_turn(history, msg, emoji.emojize(":cross_mark:") + " Aucune carte exploitable générée.")
            return history, chat_state

        repo.add_cards(cards)
        history = _add_turn(history, msg, f"{emoji.emojize(':check_mark_button:')} {len(cards)} cartes ajoutées. Dis *“On révise”* pour commencer.")
        return history, chat_state

    ### Default assistant response
    history = _add_turn(
        history,
        msg,
        "Je peux : 1) générer des flashcards depuis un texte 2) te faire réviser.\n\n"
        "Colle ton texte entre ``` ``` puis dis : “Génère 8 cartes”."
    )
    return history, chat_state

### ------------------------- ###
###   Gradio user interface   ###
### ------------------------- ###

with gr.Blocks(title="Flashcards Voice MVP") as demo:
    gr.Markdown("# 🎧 Flashcards Voice — MVP (Ollama + SQLite + SM-2)")

    with gr.Tab("Chat"):
        gr.Markdown("### Mode Chat (Start → Génération → Quiz)")

        chat_state = gr.State(
            {"phase": "idle", "source_text": "", "model": "qwen2.5:7b-instruct", "pending_card_id": None})

        start_panel = gr.Group(visible=True)
        chat_panel = gr.Group(visible=False)

        with start_panel:
            chat_model = gr.Textbox(value="qwen2.5:7b-instruct", label="Modèle Ollama")
            chat_source = gr.Textbox(lines=10, label="Texte source (à coller ici)")
            btn_start = gr.Button("Start")

        with chat_panel:
            chat = gr.Chatbot(label="Flashcards Bot")
            user = gr.Textbox(label="Message", placeholder="Ex: 8, puis tes réponses...")
            send = gr.Button("Envoyer")
            btn_change_text = gr.Button("Changer de texte", variant="secondary")

        btn_start.click(
            chat_start,
            inputs=[chat_source, chat_model, chat, chat_state],
            outputs=[chat, chat_state, start_panel, chat_panel],
        )

        send.click(
            chat_send,
            inputs=[user, chat, chat_state],
            outputs=[chat, chat_state, user],
        )

        user.submit(
            chat_send,
            inputs=[user, chat, chat_state],
            outputs=[chat, chat_state, user],
        )

        btn_change_text.click(
            chat_reset_to_start,
            inputs=[chat_state],
            outputs=[chat_state, start_panel, chat_panel],
        )

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


try:
    demo.launch(
        show_error=True,
        debug=True,
        inline=False
    )
except Exception as e:
    print(f"Erreur lors du lancement : {e}")
