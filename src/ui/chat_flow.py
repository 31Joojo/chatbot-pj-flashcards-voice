# src/ui/chat_flow.py
### Modules importation
import re
import emoji
import gradio as gr
from typing import Optional, Any
import plotly.graph_objects as go

from src.core.models import FlashcardCreate
from src.core.scheduler import (
    compute_session_score,
    suggest_next_review,
    pick_recommended_date,
)
from src.llm.generate_cards import generate_cards
from src.llm.grade_answer import explain_with_ollama, grade_with_ollama
from src.speech.stt import transcribe_audio
from src.speech.tts import synthesize_to_wav
from src.storage.clearner import _clear_tts_dir
from src.storage.repo import FlashcardRepo
from src.ui.review_flow import grade_card
from src.ui.state import reset_chat_state, reset_stats, update_stats
from src.ui.text_utils import (
    _add_turn, _parse_int,
    _strip_md, _normalize_tags,
    _similarity, _normalize_grade
)


### Setting repo for storing flashcards
_REPO: Optional[FlashcardRepo] = None
_EMOJI_RE = re.compile(r"[\U0001F000-\U0010FFFF\u2600-\u27BF\uFE0F]")

MONTHS_FR = [
    "janvier","février","mars","avril","mai","juin",
    "juillet","août","septembre","octobre","novembre","décembre"
]

### ------------------------------ Helpers ------------------------------ ###
### Helper : set_repo()
def set_repo(repo: FlashcardRepo) -> None:
    """
    Register the Flashcard repository used by the chat flow.

    :param FlashcardRepo repo: Repository instance to use
    :return None: This function does not return anything
    """
    global _REPO
    _REPO = repo

### Helper : _repo()
def _repo() -> FlashcardRepo:
    """
    Retrieve the active Flashcard repository.

    This helper ensures that the repository has been properly
    initialized before being accessed.

    :raises RuntimeError: If the repository has not been set
    :return FlashcardRepo: Active repository instance
    """
    if _REPO is None:
        raise RuntimeError("Repo not set. Call set_repo(repo) from app.py")
    return _REPO

### Helper : _ret()
def _ret(history, chat_state, details_md=None, audio_path=None, plot=None):
    """
    Build a unified return tuple for Gradio chat callbacks.

    :param list history: Current chat history
    :param dict chat_state: Current chat state
    :param Optional[str] details_md: Markdown details content
    :param Optional[str] audio_path: Path to generated TTS audio
    :param Optional[Any] plot: Plotly figure to display
    :return tuple: Standardized Gradio outputs tuple
    """
    if details_md is None:
        details_md = chat_state.get("last_details", "")

    details_vis = bool(chat_state.get("details_visible", False))
    details_upd = gr.update(value=details_md, visible=details_vis)

    ### Do not clear the plot if no update is provided
    plot_upd = gr.update() if plot is None else gr.update(value=plot, visible=True)

    return (
        history,
        chat_state,
        gr.update(value=""),
        details_upd,
        audio_path,
        plot_upd,
    )

### Helper : _mk_details()
def _mk_details(label: str, conf: float, feedback: str) -> str:
    """
    Build a detailed Markdown report for automatic grading.

    This content is stored in the chat state and can be displayed
    on demand to avoid cluttering the main conversation flow.

    :param str label: Assigned grade label
    :param float conf: Confidence score
    :param str feedback: Short feedback message
    :return str: Markdown-formatted details text
    """
    return (
        f"### Détails de l'auto-notation\n"
        f"- **Grade** : `{label}`\n"
        f"- **Confidence** : `{conf:.2f}`\n"
        f"- **Feedback** : {feedback or '—'}\n"
        "\n*(Ces détails ne sont pas affichés automatiquement pour garder le chat lisible.)*"
    )

### Helper : _mk_session_details()
def _mk_session_details(entries):
    """
    Build a detailed Markdown summary for a full review session.

    :param list entries: List of grading detail dictionaries
    :return str: Markdown-formatted session details
    """
    if not isinstance(entries, list):
        return "Aucun détail pour cette session."

    ### Keep only valid dictionary entries
    clean = [e for e in entries if isinstance(e, dict)]

    if not clean:
        return "Aucun détail pour cette session."

    lines = ["### Détails de la session"]
    for i, e in enumerate(clean, 1):
        grade = e.get("grade", "?")
        conf = float(e.get("confidence", 0.0) or 0.0)
        lines.append(f"#### Q{i} — `{grade}` (conf: {conf:.2f})")
        lines.append(f"**Question :** \n{e.get('question','')}")
        lines.append(f"\n**Ta réponse :** \n{e.get('student','')}")
        lines.append(f"\n**Réponse attendue :** \n{e.get('expected','')}")
        fb = e.get("feedback", "")
        if fb:
            lines.append(f"\n**Feedback :** \n{fb}")

        ### Normalize tags
        tags = e.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        elif isinstance(tags, (list, tuple, set)):
            tags = [str(t).strip() for t in tags if str(t).strip()]
        else:
            tags = []

        if tags:
            lines.append(f"**Tags :** {', '.join(tags)}")

        lines.append("\n---\n")

    return "\n".join(lines).strip()

### Helper : _detect_explain_choice()
def _detect_explain_choice(text: str) -> Optional[str]:
    """
    Detect whether the user wants to retry or skip a question.

    :param str text: User input text
    :return Optional[str]: "retry", "pass", or None
    """
    if not text:
        return None

    t = text.strip().lower()

    ### Entry normalization
    t = re.sub(r"[^\w\sàâçéèêëîïôûùüÿñæœ-]", " ", t)
    t = re.sub(r"\s+", " ", t)

    ### Negative forms override retry intent
    if re.search(r"\b(pas|plus)\b.*\b(r[eé]ess|retent|refaire|recommenc)\w*", t):
        return "pass"

    retry_patterns = [
        r"\b(r[eé]ess)\w*", r"\bretent\w*", r"\brecommenc\w*",
        r"\brefaire\w*", r"\bencore\b", r"\bretry\b",
    ]
    pass_patterns = [
        r"\bpass\w*", r"\bsuiv\w*", r"\bnext\b", r"\bskip\b",
        r"\bcontinue\w*", r"\bquestion suivante\b", r"\bpasse\b",
    ]

    if any(re.search(p, t) for p in retry_patterns):
        return "retry"
    if any(re.search(p, t) for p in pass_patterns):
        return "pass"

    return None

### Helper : _mk_bot_reply()
def _mk_bot_reply(label: str, feedback: str, next_question: Optional[str]) -> str:
    """
    Generate a concise bot reply after grading an answer.

    :param str label: Grade label assigned to the answer
    :param str feedback: Short feedback message
    :param Optional[str] next_question: Next question text if any
    :return str: Bot reply message
    """
    ### Case : feedback
    if label in {"Good", "Easy"}:
        head = f"{emoji.emojize(':trophy:')} Bien joué !"
    elif label == "Hard":
        head = f"{emoji.emojize(':thinking_face:')} Pas mal, mais incomplet."
    else:
        head = f"{emoji.emojize(':warning:')} Pas tout à fait."

    tail = ""
    if next_question:
        tail = f"\n\n{emoji.emojize(':brain:')} **Question suivante :** {next_question}"
    else:
        tail = f"\n\n{emoji.emojize(':party_popper:')} Session terminée."

    ### Expected answer is not shown here
    return f"{head}\n\n{emoji.emojize(':speech_balloon:')} {feedback or '—'}{tail}"

### Helper : _make_pie()
def _make_pie(chat_state):
    """
    Create a pie chart summarizing grade distribution.

    :param dict chat_state: Chat state containing grade counts
    :return plotly.graph_objects.Figure: Pie chart figure
    """
    counts = chat_state.get("grade_counts", {})
    labels = ["Again", "Hard", "Good", "Easy"]
    values = [counts.get(k, 0) for k in labels]

    if sum(values) == 0:
        fig = go.Figure()
        fig.add_annotation(text="Pas de réponses notées", x=0.5, y=0.5, showarrow=False)
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
        fig.update_layout(title="Répartition des notes")
        return fig

    fig = go.Figure(data=[go.Pie(labels=labels, values=values, hole=0.35)])
    fig.update_traces(textinfo="percent+label")
    fig.update_layout(title="Répartition des notes")
    return fig

### Helper : _plot_update()
def _plot_update(chat_state):
    """
    Update the statistics plot displayed in the chat interface.

    :param dict chat_state: Current chat state
    :return Any: Gradio update object for the statistics plot
    """
    counts = chat_state.get("final_plot_counts", None)
    if counts is None:
        return gr.update(value=None, visible=False)
    return gr.update(value=_make_pie(counts), visible=True)

### Helper : _toggle_mic()
def _toggle_mic(enabled: bool):
    """
    Toggle microphone-based input in the chat UI.

    When enabled, microphone widgets are shown and text input
    widgets are hidden, and vice versa.

    :param bool enabled: Whether microphone mode is enabled
    :return tuple: Gradio visibility updates
    """
    return (
        gr.update(visible=enabled),
        gr.update(visible=False),
        gr.update(visible=not enabled),
        gr.update(visible=not enabled),
    )

### Helper : _tss()
def _tts(bot_text: str, tts_on: bool):
    """
    Generate text-to-speech audio for a bot message.

    :param str bot_text: Bot message text
    :param bool tts_on: Whether TTS is enabled
    :return Optional[str]: Path to generated WAV file, or None
    """
    if not tts_on:
        return None

    try:
        clean = _strip_md(bot_text)
        clean = _EMOJI_RE.sub("", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        return synthesize_to_wav(clean)
    except Exception:
        return None

### Helper : _say_date_fr()
def _say_date_fr(date):
    """
    Convert a datetime into a short French human-readable date.

    :param datetime date: Datetime to format
    :return str: French-formatted date string
    """
    return f"le {date.day} {MONTHS_FR[date.month-1]} {date.year}"

### ----------------------------- Functions ----------------------------- ###
### Function : show_details()
def show_details(history, chat_state):
    """
    Toggle the visibility of grading details in the UI.

    :param list history: Current chat history
    :param dict chat_state: Chat state dictionary
    :return tuple: Updated history, state, and details panel update
    """
    if chat_state.get("phase") == "done" and chat_state.get("details_session_md"):
        md = chat_state["details_session_md"]
    else:
        md = chat_state.get("last_details", "")

    chat_state["details_visible"] = True
    chat_state["last_details"] = md

    return history, chat_state, gr.update(value=md, visible=True)

### Function : make_source_title()
def make_source_title(src: str, model: str) -> str:
    """
    Generate a short human-readable title for a source text.

    :param str src: Source text
    :param str model: LLM model name
    :return str: Generated title
    """
    s = " ".join((src or "").split())
    return (s[:50] + "…") if len(s) > 50 else (s or "Cours")

### Function : chat_start()
def chat_start(source_text, model, history, chat_state, tts_on):
    """
    Initialize a new chat session from a source text.

    This function:
    - validates the source text ;
    - creates a new source entry in the database ;
    - initializes the chat state machine.

    :param str source_text: Source text provided by the user
    :param str model: Ollama model name
    :param list history: Current chat history
    :param dict chat_state: Chat state machine
    :param bool tts_on: Whether text-to-speech is enabled
    :return tuple: Updated history, chat state, UI updates, audio, and plot reset
    """
    history = history or []
    chat_state = reset_chat_state(model=(model or "qwen2.5:7b-instruct"))
    chat_state["details_log"] = []
    chat_state["details_session"] = ""
    chat_state["details_mode"] = "last"
    chat_state["details_visible"] = False

    src = (source_text or "").strip()
    if not src:
        bot_text = f"{emoji.emojize(':cross_mark:')} Colle un texte source avant de cliquer Start."
        history.append({"role": "assistant", "content": bot_text})

        audio_path = _tts(bot_text, tts_on)

        return (
            history,
            chat_state,
            gr.update(visible=False),
            gr.update(visible=True),
            gr.update(value="", visible=False),
            audio_path,
            gr.update(value=None, visible=False),
        )

    ### Create a new logical source for the session in the database
    title = make_source_title(src, model)
    source_id = _repo().add_source(source_text=src[:8000], title=title)
    chat_state["source_title"] = title

    chat_state.update({
        "phase": "need_n",
        "source_text": src[:8000],
        "source_id": int(source_id),
        "pending_card_id": None,
    })
    reset_stats(chat_state)
    chat_state["weak_tags"] = {}

    bot_text = f"{emoji.emojize(':check_mark_button:')} Texte reçu (**{title}**). Combien de cartes veux-tu générer ? (Par exemple : 8)"
    history.append({"role": "assistant", "content": bot_text})

    audio_path = _tts(bot_text, tts_on)

    return (
        history,
        chat_state,
        gr.update(visible=False),
        gr.update(visible=True),
        gr.update(value="", visible=False),
        audio_path,
        gr.update(value=None, visible=False),
    )

### Function : chat_send()
def chat_send(user_msg, history, chat_state, tts_on):
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

    :param str user_msg: User message
    :param list history: Current chat history
    :param dict chat_state: Chat state machine
    :param bool tts_on: Whether text-to-speech is enabled
    :return tuple: Updated history, state, UI elements, audio, and plot
    """
    history = history or []
    chat_state = chat_state or {"phase": "idle", "source_text": "", "model": "qwen2.5:7b-instruct", "pending_card_id": None}

    ### Track weaknesses by tag across the session
    chat_state.setdefault("weak_tags", {})

    ### Subfunction : _ret_chat_send()
    ### Centralized helper to return Gradio outputs consistently
    def _ret_chat_send(
            h,
            s,
            bot_text: Optional[str] = None,
            audio: Optional[str] = None,
            plot: Optional[Any] = None,
            tts_text: Optional[str] = None
    ):
        """
        Build the standardized return tuple for chat_send callbacks.

        This helper centralizes UI updates, audio generation,
        details visibility handling, and plot persistence.

        :param list h: Chat history
        :param dict s: Chat state
        :param Optional[str] bot_text: Bot reply text
        :param Optional[str] audio: Pre-generated audio path
        :param Optional[Any] plot: Plotly figure to display
        :param Optional[str] tts_text: Alternative text for TTS synthesis
        :return tuple: Gradio outputs tuple
        """
        ### Generate TTS audio when it's needed
        if bot_text is not None and audio is None:
            audio = _tts(tts_text if tts_text is not None else bot_text, tts_on)

        ### Handle details panel visibility and content
        details_vis = bool(s.get("details_visible", False))
        mode = s.get("details_mode", "last")

        ### Select details content depending on the current mode
        if mode == "session":
            details_text = s.get("details_session", "") or "Aucun détail de session."
        else:
            details_text = s.get("last_details", "") or "Aucun détail pour l’instant."

        details_upd = gr.update(value=details_text, visible=details_vis)

        ### Persist plot if provided
        if plot is not None:
            s["last_plot"] = plot

        ### Restore last plot if available
        plot_upd = gr.update(visible=False)
        if s.get("last_plot") is not None:
            plot_upd = gr.update(value=s["last_plot"], visible=True)

        return h, s, gr.update(value=""), details_upd, audio, plot_upd

    ### Normalize user input
    msg = (user_msg or "").strip()
    if not msg:
        return _ret_chat_send(history, chat_state)

    phase = chat_state.get("phase", "idle")

    ### ---------- Idle phase ---------- ###
    ### If we are mid-session but lost the source_id -> reset safely
    if phase != "idle":
        sid = chat_state.get("source_id")
        if sid is None:
            bot = emoji.emojize(":cross_mark:") + " Bug : source_id manquant. Clique sur **Changer de texte** puis Start."
            history = _add_turn(history, msg, bot)
            chat_state["phase"] = "idle"
            chat_state["pending_card_id"] = None
            return _ret_chat_send(history, chat_state, bot_text=bot)

    ### ------- Quiz done phase -------- ###
    ### End-of-session conversational routing
    if phase == "done":
        low = msg.lower()

        ### Case : explicit request to display session details
        if "détail" in low or "detail" in low:
            bot = f"Voici les détails de la session️."
            history = _add_turn(history, msg, bot)

            chat_state["details_visible"] = True
            chat_state["last_details"] = chat_state.get("details_session_md", "Aucun détail pour cette session.")

            return _ret_chat_send(history, chat_state, bot_text=bot)

        ### Case : redirect user to the dedicated review flow for existing courses
        if any(k in low for k in ["réviser", "reviser", "cours existant", "révision"]):
            bot = (
                f"OK {emoji.emojize(':repeat_button:')} Pour réviser un cours existant, "
                f"utilise le sélecteur de cours dans l'écran de démarrage"
                f"ou va dans l'onglet **Réviser**, puis lance une session."
            )
            history = _add_turn(history, msg, bot)
            return _ret_chat_send(history, chat_state, bot_text=bot)

        ### Case : add more cards on the same source
        if any(k in low for k in ["génère", "genere", "plus", "+"]):
            n = _parse_int(msg) or 5
            n = max(1, min(30, n))
            chat_state["phase"] = "need_n"
            bot = (
                f"OK {emoji.emojize(':thumbs_up_medium-dark_skin_tone:')} "
                f"Combien de cartes veux-tu ajouter ? (par défaut: {n})"
            )
            history = _add_turn(history, msg, bot)
            return _ret_chat_send(history, chat_state, bot_text=bot)

        ### Default terminal message
        bot = emoji.emojize(":check_mark_button:") + (
            " Session terminée.\n\n"
            "- **Changer de texte**\n"
            "- **Générer plus de cartes**\n"
            "- taper **détails** pour le résumé"
        )
        history = _add_turn(history, msg, bot)
        fig = chat_state.get("last_plot")

        if fig is not None:
            chat_state["last_plot"] = fig

        _ret_chat_send(history, chat_state, bot_text=bot)

    ### --------- Need n phase --------- ###
    ### Waiting for the number of cards to generate
    if phase == "need_n":
        n = _parse_int(msg)
        if not n:
            bot = "Je n’ai pas compris le nombre. Réponds juste par un nombre (ex: 8)."
            history = _add_turn(history, msg, bot)
            return _ret_chat_send(history, chat_state, bot_text=bot)

        n = max(1, min(30, n))
        source = chat_state.get("source_text", "")
        model = chat_state.get("model", "qwen2.5:7b-instruct")

        try:
            ### Generate cards with the LLM
            payload = generate_cards(source, n=n, model=model)

            ### Auto-generated title for the source
            title = str(payload.get("title", "") or "").strip()
            if title:
                chat_state["source_title"] = title
                try:
                    _repo().update_source_title(chat_state["source_id"], title)
                except Exception:
                    pass

            ### Validate generated cards before persistence
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
                bot = emoji.emojize(":cross_mark:") + " Aucune carte exploitable n’a été générée. Réessaie avec un autre texte."
                history = _add_turn(history, msg, bot)
                return _ret_chat_send(history, chat_state, bot_text=bot)

            ### Add generated cars in database
            _repo().add_cards(cards, source_id=chat_state["source_id"])

        except Exception as e:
            bot = f"{emoji.emojize(':cross_mark:')} Erreur génération: {type(e).__name__}: {e}"
            history = _add_turn(history, msg, bot)
            return _ret_chat_send(history, chat_state, bot_text=bot)

        ### Launch the quizz
        due = _repo().get_due(limit=1, source_id=chat_state["source_id"])
        if not due:
            chat_state["phase"] = "idle"
            bot = (
                f"{emoji.emojize(':check_mark_button:')} {len(cards)} cartes ajoutées. "
                f"{emoji.emojize(':party_popper:')} Rien à réviser."
            )
            history = _add_turn(history, msg, bot)
            return _ret_chat_send(history, chat_state, bot_text=bot)

        card = due[0]
        chat_state["pending_card_id"] = card.id
        chat_state["phase"] = "quiz_answer"

        bot = (
            f"{emoji.emojize(':check_mark_button:')} {len(cards)} cartes ajoutées.\n\n"
            f"{emoji.emojize(':brain:')} **Question 1 :** {card.question}"
        )
        history = _add_turn(history, msg, bot)
        return _ret_chat_send(history, chat_state, bot_text=bot)

    ### ------- Quiz answer phase ------ ###
    ### User is answering a flashcard
    if phase == "quiz_answer":
        cid = chat_state.get("pending_card_id")
        card = _repo().get_by_id(int(cid)) if cid else None
        if not card:
            chat_state["phase"] = "idle"
            bot = emoji.emojize(":cross_mark:") + " Carte introuvable. Clique Start pour recommencer."
            history = _add_turn(history, msg, bot)
            return _ret_chat_send(history, chat_state, bot_text=bot)

        model = chat_state.get("model", "qwen2.5:7b-instruct")

        ### Prevent double-processing due to Gradio double-trigger
        last = chat_state.get("_last_grade_event")
        key = (cid, msg)
        if last == key:
            ### Ignore duplicate
            return _ret_chat_send(history, chat_state)
        chat_state["_last_grade_event"] = key

        ### Case : explanation intent detection
        lower = msg.lower()
        if any(k in lower for k in ["explique", "je ne sais pas", "hint"]):
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
            return _ret_chat_send(history, chat_state, bot_text=bot)

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

        ### ---- Log answer for summary ----
        log = chat_state.setdefault("details_log", [])
        if not isinstance(log, list):
            chat_state["details_log"] = []
            log = chat_state["details_log"]

        log.append({
            "question": card.question,
            "expected": card.answer,
            "student": msg,
            "grade": label,
            "confidence": float(conf),
            "feedback": feedback,
            "tags": card.tags,
        })

        ### The panel remains on last correction during the session
        chat_state["details_mode"] = "last"

        ### Track weakness tags for recap
        if label in {"Again", "Hard"}:
            raw_tags = card.tags or []

            ### Card.tags can be a string "a,b" or a list ["a","b"]
            if isinstance(raw_tags, str):
                tags_list = [t.strip() for t in raw_tags.split(",") if t.strip()]
            elif isinstance(raw_tags, (list, tuple, set)):
                tags_list = [str(t).strip() for t in raw_tags if str(t).strip()]
            else:
                tags_list = []

            weak = chat_state.setdefault("weak_tags", {})
            for t in tags_list:
                weak[t] = weak.get(t, 0) + 1

        ### Applying SM-2
        sid = chat_state.get("source_id")
        next_id, status, question, info = grade_card(int(cid), label, source_id=sid)

        ### Update session statistics
        update_stats(chat_state, label, conf)

        chat_state["last_details"] = _mk_details(label, conf, feedback)
        ### ----- session details log -----
        chat_state.setdefault("details_log", [])
        if not isinstance(chat_state["details_log"], list):
            ### Security if old state stored a string
            chat_state["details_log"] = []

        chat_state["details_visible"] = False

        ### End of session
        if next_id is None:
            chat_state["pending_card_id"] = None
            chat_state["phase"] = "done"

            chat_state["final_plot_counts"] = dict(chat_state.get("grade_counts", {}))
            chat_state["details_session"] = _mk_session_details(chat_state.get("details_log", []))
            chat_state["details_session_md"] = _mk_session_details(chat_state.get("details_log", []))

            avg_conf = (chat_state["conf_sum"] / max(1, chat_state["graded"]))
            score = compute_session_score(chat_state["grade_counts"], avg_conf)
            sugg = suggest_next_review(score)
            next_due = _repo().get_next_due_at(chat_state["source_id"])
            recommended = pick_recommended_date(sugg, next_due)

            ### Case : a revising plan has been added
            try:
                _repo().upsert_review_plan(chat_state["source_id"], recommended, score)
            except Exception:
                pass

            weak = chat_state.get("weak_tags", {})
            weak_txt = ""
            if weak:
                worst = sorted(weak.items(), key=lambda x: x[1], reverse=True)[:5]
                weak_txt = "\n- Points à revoir: " + ", ".join([f"{k} (x{v})" for k, v in worst])

            date_str = recommended.strftime("%d/%m/%Y")

            recap = (
                f"{emoji.emojize(':party_popper:')} Plus de cartes dues.\n\n"
                f"**Récap session**:\n"
                f"- Questions notées : **{chat_state['graded']}**\n"
                f"- Moyenne confiance : **{avg_conf * 100:.1f} %**\n"
                f"- Again/Hard/Good/Easy : "
                f"{chat_state['grade_counts'].get('Again', 0)}/"
                f"{chat_state['grade_counts'].get('Hard', 0)}/"
                f"{chat_state['grade_counts'].get('Good', 0)}/"
                f"{chat_state['grade_counts'].get('Easy', 0)}\n\n"
                f"- Score global : **{score * 100:.2f} %**\n"
                f"- Prochaine révision recommandée : **{date_str}** "
                f"(~{sugg.days} jour(s) – {sugg.reason})"
                f"{weak_txt}\n\n"
                "Tu veux **changer de texte** ou **réviser un cours existant** ?"
            )

            bot = (
                f"{emoji.emojize(':party_popper:')} Session terminée.\n\n"
                f"{recap}"
            )

            tts_recap = (
                "Session terminée. Plus de cartes dues. "
                f"Score global : {score * 100:.2f} %. "
                f"Prochaine révision recommandée {_say_date_fr(recommended)}, "
                f"dans environ {sugg.days} jour{'s' if sugg.days > 1 else ''}. "
                "Tu veux changer de texte ou réviser un cours existant ?"
            )

            ### Generates the plot when the session ends
            fig = _make_pie(chat_state)
            chat_state["last_plot"] = fig
            history = _add_turn(history, msg, bot)
            return _ret_chat_send(history, chat_state, bot_text=bot, tts_text=tts_recap, plot=fig)

        ### Continue quiz
        chat_state["pending_card_id"] = next_id
        chat_state["phase"] = "quiz_answer"

        if label in {"Good", "Easy"}:
            head = f"{emoji.emojize(':trophy:')} Bien joué !"
        elif label == "Hard":
            head = f"{emoji.emojize(':thinking_face:')} Pas mal, mais incomplet."
        else:
            head = f"{emoji.emojize(':warning:')} Pas tout à fait."

        bot = (
            f"{head}\n\n"
            f"{emoji.emojize(':speech_balloon:')} {feedback or '—'}\n\n"
            f"{emoji.emojize(':brain:')} **Question suivante :** {question}"
        )
        history = _add_turn(history, msg, bot)
        return _ret_chat_send(history, chat_state, bot_text=bot)

    ### ------- Quiz grade phase ------- ###
    if phase == "quiz_grade":
        label = _normalize_grade(msg)
        if not label:
            bot = "Je n’ai pas compris. Réponds: Again / Hard / Good / Easy."
            history = _add_turn(history, msg, bot)
            return _ret_chat_send(history, chat_state, bot_text=bot)

        cid = chat_state.get("pending_card_id")
        if not cid:
            chat_state["phase"] = "idle"
            bot = emoji.emojize(":cross_mark:") + " Plus de carte en cours. Clique Start pour recommencer."
            history = _add_turn(history, msg, bot)
            return _ret_chat_send(history, chat_state, bot_text=bot)

        sid = chat_state.get("source_id")
        next_id, status, question, info = grade_card(int(cid), label, source_id=sid)

        if next_id is None:
            chat_state["pending_card_id"] = None
            chat_state["phase"] = "idle"
            bot = emoji.emojize(':check_mark_button:') + " Noté. " + emoji.emojize(':party_popper:') + " Plus de cartes dues."
            history = _add_turn(history, msg, bot)
            return _ret_chat_send(history, chat_state, bot_text=bot)

        chat_state["pending_card_id"] = next_id
        chat_state["phase"] = "quiz_answer"
        bot = f"{emoji.emojize(':check_mark_button:')} Noté ({label}).\n\n{emoji.emojize(':brain:')} **Question suivante :** {question}"
        history = _add_turn(history, msg, bot)
        return _ret_chat_send(history, chat_state, bot_text=bot)

    ### ------- Quiz explanation phase ------- ###
    if phase == "quiz_explain_choice":
        ### User decision after receiving explanations
        choice = _detect_explain_choice(msg)

        cid = chat_state.get("pending_card_id")
        card = _repo().get_by_id(int(cid)) if cid else None
        if not card:
            chat_state["phase"] = "idle"
            bot = emoji.emojize(":cross_mark:") + " Carte introuvable. Clique Start pour recommencer."
            history = _add_turn(history, msg, bot)
            return _ret_chat_send(history, chat_state, bot_text=bot)

        ### Case : the user wants to retry
        if choice == "retry":
            chat_state["phase"] = "quiz_answer"
            bot = f"OK ! {emoji.emojize(':brain:')} **Même question :** {card.question}"
            history = _add_turn(history, msg, bot)
            return _ret_chat_send(history, chat_state, bot_text=bot)

        ### Case : the user wants to pass and continue the quizz
        if choice == "pass":
            sid = chat_state.get("source_id")
            next_id, status, question, info = grade_card(int(cid), "Again", source_id=sid)

            if next_id is None:
                ### Consider the previous card as ‘Again’
                label = "Again"
                conf = 0.0
                feedback = "Carte passée après explication."

                ### Update stats and last_details
                update_stats(chat_state, label, conf)
                chat_state["last_details"] = _mk_details(label, conf, feedback)

                ### Structured log
                chat_state.setdefault("details_log", [])
                if not isinstance(chat_state["details_log"], list):
                    chat_state["details_log"] = []
                chat_state["details_log"].append({
                    "question": card.question,
                    "expected": card.answer,
                    "student": msg,
                    "grade": label,
                    "confidence": float(conf),
                    "feedback": feedback,
                    "tags": card.tags,
                })

                chat_state["pending_card_id"] = None
                chat_state["phase"] = "done"

                ### Generates the session markdown and plot when it finishes
                chat_state["details_session_md"] = _mk_session_details(chat_state["details_log"])
                fig = _make_pie(chat_state)
                chat_state["last_plot"] = fig

                bot = (
                    f"{emoji.emojize(':party_popper:')} Session terminée.\n\n"
                    f"{emoji.emojize(':party_popper:')} Plus de cartes dues.\n\n"
                    "Tu peux taper **détails** pour voir le résumé de session."
                )
                history = _add_turn(history, msg, bot)
                return _ret_chat_send(history, chat_state, bot_text=bot, plot=fig)

            chat_state["pending_card_id"] = next_id
            chat_state["phase"] = "quiz_answer"
            bot = f"{emoji.emojize(':check_mark_button:')} OK, on passe.\n\n{emoji.emojize(':brain:')} **Question suivante :** {question}"
            history = _add_turn(history, msg, bot)
            return _ret_chat_send(history, chat_state, bot_text=bot)

        bot = "Je n’ai pas compris. Tu peux dire: `passer`, `question suivante`, `réessayer`, `refaire`"
        history = _add_turn(history, msg, bot)
        return _ret_chat_send(history, chat_state, bot_text=bot)

    ### Fallback
    ### Safety net for unexpected states
    chat_state["phase"] = "idle"
    bot = "Je me suis perdu " + emoji.emojize(":grinning_face_with_sweat:") + " Clique Start pour recommencer."
    history = _add_turn(history, msg, bot)
    return _ret_chat_send(history, chat_state, bot_text=bot)

### Function : chat_send_audio()
def chat_send_audio(audio_path, history, chat_state, tts_on):
    """
    Handle audio input by transcribing speech and forwarding
    the result to the text-based chat handler.

    :param str audio_path: Path to recorded audio file
    :param list history: Current chat history
    :param dict chat_state: Chat state machine
    :param bool tts_on: Whether text-to-speech is enabled
    :return tuple: Same outputs as chat_send
    """
    history = history or []
    chat_state = chat_state or {}

    if not audio_path:
        return _ret(history, chat_state, audio_path=None, plot=None)

    try:
        stt = transcribe_audio(audio_path)
        text = (getattr(stt, "text", "") or "").strip()
    except Exception as e:
        bot = f"{emoji.emojize(':cross_mark:')} Erreur STT: {type(e).__name__}: {e}"
        history = _add_turn(history, "", bot)
        return _ret(history, chat_state, audio_path=_tts(bot, tts_on), plot=None)

    if not text:
        bot = f"{emoji.emojize(':cross_mark:')} Je n’ai rien compris. Réessaie en parlant plus près du micro."
        history = _add_turn(history, "", bot)
        return _ret(history, chat_state, audio_path=_tts(bot, tts_on), plot=None)

    return chat_send(text, history, chat_state, tts_on)

### Function : chat_reset_to_start()
def chat_reset_to_start(chat_state):
    """
    Fully reset the chat UI and internal state to the start screen.

    :param dict chat_state: Current chat state
    :return tuple: Reset history, state, and UI visibility updates
    """
    _clear_tts_dir("data/tts")
    chat_state = reset_chat_state(model="qwen2.5:7b-instruct")
    chat_state["weak_tags"] = {}
    history = []

    return (
        history,
        chat_state,
        ### Start panel
        gr.update(visible=True),
        ### Chat panel
        gr.update(visible=False),
        ### Details_md
        gr.update(value="", visible=False),
        ### bot_audio
        gr.update(value=None),
        ### Stats plot
        gr.update(value=None, visible=False),
        ### Mic
        gr.update(value=None),
        ### User textbox
        gr.update(value=""),
    )

### Function : chat_start_review()
def chat_start_review(source_id: int, model: str, history, chat_state, tts_on):
    """
    Start a review-only session for an existing source.

    This function initializes a fresh review session,
    loads the next due flashcard for the selected source,
    and switches the UI to quiz mode.

    :param int source_id: Identifier of the source to review
    :param str model: Ollama model name
    :param list history: Current chat history
    :param dict chat_state: Chat state machine
    :param bool tts_on: Whether text-to-speech is enabled
    :return tuple: Updated history, state, UI updates, audio, and plot reset
    """
    history = history or []

    ### Full state reset for a new review session
    chat_state = reset_chat_state(model=(model or "qwen2.5:7b-instruct"))
    reset_stats(chat_state)

    ### Initialize session-specific tracking
    chat_state["weak_tags"] = {}
    chat_state["last_plot"] = None
    chat_state["details_log"] = []
    chat_state["details_session_md"] = ""
    chat_state["details_mode"] = "last"
    chat_state["details_visible"] = False

    sid = int(source_id) if source_id else None
    if not sid:
        bot = "Choisis un cours."
        history.append({"role": "assistant", "content": bot})
        return (
            history, chat_state,
            gr.update(visible=True), gr.update(visible=False),
            gr.update(value=""), _tts(bot, tts_on),
            gr.update(value=None, visible=False),
        )

    ### Load source context
    chat_state["source_id"] = sid
    chat_state["source_text"] = _repo().get_source_preview(sid)
    chat_state["phase"] = "quiz_answer"

    ### Fetch next due card
    due = _repo().get_due(limit=1, source_id=sid)
    if not due:
        bot = f"{emoji.emojize(':check_mark_button:')} Aucune carte due pour ce cours pour l’instant."
        history.append({"role": "assistant", "content": bot})
        return (
            history, chat_state,
            gr.update(visible=False), gr.update(visible=True),
            gr.update(value=""), _tts(bot, tts_on),
            gr.update(value=None, visible=False),
        )

    card = due[0]
    chat_state["pending_card_id"] = card.id

    bot = f"{emoji.emojize(':repeat_button:')} Révision du cours **{sid}**\n\n{emoji.emojize(':brain:')} **Question :** {card.question}"
    history.append({"role": "assistant", "content": bot})

    return (
        history, chat_state,
        gr.update(visible=False), gr.update(visible=True),
        gr.update(value=""), _tts(bot, tts_on),
        gr.update(value=None, visible=False),
    )
