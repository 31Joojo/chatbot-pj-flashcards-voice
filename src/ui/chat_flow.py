# src/ui/chat_flow.py
### Modules importation
import re
import emoji
import gradio as gr
from typing import Optional
import plotly.graph_objects as go

from src.core.models import FlashcardCreate
from src.llm.generate_cards import generate_cards
from src.llm.grade_answer import explain_with_ollama, grade_with_ollama
from src.speech.stt import transcribe_audio
from src.speech.tts import synthesize_to_wav
from src.storage.repo import FlashcardRepo
from src.ui.review_flow import grade_card
from src.ui.state import reset_chat_state, reset_stats, update_stats
from src.ui.text_utils import _add_turn, _parse_int, _strip_md, _normalize_tags, _similarity, _normalize_grade


### Setting repo for storing flashcards
_REPO: Optional[FlashcardRepo] = None
_EMOJI_RE = re.compile(r"[\U0001F000-\U0010FFFF\u2600-\u27BF\uFE0F]")

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
        gr.update(visible=enabled),
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

### ----------------------------- Functions ----------------------------- ###
### Function : show_details()
def show_details(history, chat_state):
    """
    Toggle the visibility of grading details in the UI.

    :param list history: Current chat history
    :param dict chat_state: Chat state dictionary
    :return tuple: Updated history, state, and details panel update
    """
    history = history or []
    chat_state = chat_state or {}

    currently = bool(chat_state.get("details_visible", False))
    new_vis = not currently
    chat_state["details_visible"] = new_vis

    details = chat_state.get("last_details", "")
    if not details:
        details = "Aucun détail pour l’instant."

    return history, chat_state, gr.update(value=details, visible=new_vis)

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
    source_id = _repo().add_source(source_text=src[:8000], title=None)

    chat_state.update({
        "phase": "need_n",
        "source_text": src[:8000],
        "source_id": int(source_id),
        "pending_card_id": None,
    })
    reset_stats(chat_state)

    bot_text = emoji.emojize(':check_mark_button:') + " Texte reçu. Combien de cartes veux-tu générer ? (ex: 8)"
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

    def _ret_chat_send(h, s, bot_text=None, audio=None, plot=None):
        if bot_text is not None:
            audio = _tts(bot_text, tts_on)

        details_vis = bool(s.get("details_visible", False))
        details_upd = gr.update(value=s.get("last_details", ""), visible=details_vis)

        plot_upd = gr.update() if plot is None else gr.update(value=plot, visible=True)

        return (
            h,
            s,
            gr.update(value=""),
            details_upd,
            audio,
            plot_upd,
        )

    msg = (user_msg or "").strip()
    if not msg:
        return _ret_chat_send(history, chat_state)

    phase = chat_state.get("phase", "idle")

    ### ---------- Idle phase ---------- ###
    if phase != "idle":
        sid = chat_state.get("source_id")
        if sid is None:
            bot = emoji.emojize(":cross_mark:") + " Bug : source_id manquant. Clique sur **Changer de texte** puis Start."
            history = _add_turn(history, msg, bot)
            chat_state["phase"] = "idle"
            chat_state["pending_card_id"] = None
            return _ret_chat_send(history, chat_state, bot_text=bot)

    ### ------- Quiz done phase -------- ###
    if phase == "done":
        low = msg.lower()

        ### Show details
        if "détail" in low or "detail" in low:
            if chat_state.get("last_details"):
                bot = "Voici les détails " + emoji.emojize(":right_arrow_curving_down:")
                history = _add_turn(history, msg, bot)
                return _ret_chat_send(history, chat_state, bot_text=bot)

            bot = "Je n’ai pas de détails à afficher pour l’instant."
            history = _add_turn(history, msg, bot)
            return _ret_chat_send(history, chat_state, bot_text=bot)

        ### Regenerate on the same text
        if any(k in low for k in ["génère", "genere", "plus", "+"]):
            n = _parse_int(msg) or 5
            n = max(1, min(30, n))
            chat_state["phase"] = "need_n"
            bot = f"OK {emoji.emojize(':thumbs_up_medium-dark_skin_tone:')} Combien de cartes veux-tu ajouter ? (par défaut: {n})\n\nRéponds par un nombre."
            history = _add_turn(history, msg, bot)
            return _ret_chat_send(history, chat_state, bot_text=bot)

        bot = emoji.emojize(":check_mark_button:") + " Session terminée.\n\nTu peux :\n- cliquer **Changer de texte**\n- ou demander **“génère 5”** pour ajouter des cartes au même texte\n- ou taper **détails** pour voir l’auto-notation."
        history = _add_turn(
            history,
            msg,
            bot
        )
        fig = _make_pie(chat_state)
        plot_upd = gr.update(value=fig, visible=True)
        chat_state["last_plot"] = fig
        return (
            history,
            chat_state,
            gr.update(value=""),
            gr.update(value=chat_state.get("last_details", "")),
            _tts(bot, tts_on),
            plot_upd,
        )

    ### --------- Need n phase --------- ###
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
                bot = emoji.emojize(":cross_mark:") + " Aucune carte exploitable n’a été générée. Réessaie avec un autre texte."
                history = _add_turn(history, msg, bot)
                return _ret_chat_send(history, chat_state, bot_text=bot)

            _repo().add_cards(cards, source_id=chat_state["source_id"])


        except Exception as e:
            bot = f"{emoji.emojize(':cross_mark:')} Erreur génération: {type(e).__name__}: {e}"
            history = _add_turn(history, msg, bot)
            return _ret_chat_send(history, chat_state, bot_text=bot)

        ### Launch the quizz
        due = _repo().get_due(limit=1, source_id=chat_state["source_id"])
        if not due:
            chat_state["phase"] = "idle"
            bot = f"{emoji.emojize(':check_mark_button:')} {len(cards)} cartes ajoutées. {emoji.emojize(':party_popper:')} Rien à réviser pour l’instant."
            history = _add_turn(history, msg, bot)
            return _ret_chat_send(history, chat_state, bot_text=bot)

        card = due[0]
        chat_state["pending_card_id"] = card.id
        chat_state["phase"] = "quiz_answer"

        bot = f"{emoji.emojize(':check_mark_button:')} {len(cards)} cartes ajoutées.\n\n{emoji.emojize(':brain:')} **Question 1 :** {card.question}"
        history = _add_turn(history, msg, bot)
        return _ret_chat_send(history, chat_state, bot_text=bot)

    ### ------- Quiz answer phase ------ ###
    if phase == "quiz_answer":
        cid = chat_state.get("pending_card_id")
        card = _repo().get_by_id(int(cid)) if cid else None
        if not card:
            chat_state["phase"] = "idle"
            bot = emoji.emojize(":cross_mark:") + " Carte introuvable. Clique Start pour recommencer."
            history = _add_turn(history, msg, bot)
            return _ret_chat_send(history, chat_state, bot_text=bot)

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

        ### Applying SM-2
        sid = chat_state.get("source_id")
        next_id, status, question, info = grade_card(int(cid), label, source_id=sid)

        ### stats update
        chat_state["graded"] += 1
        chat_state["conf_sum"] += float(conf)
        chat_state["grade_counts"][label] = chat_state["grade_counts"].get(label, 0) + 1
        update_stats(chat_state, label, conf)
        chat_state["last_details"] = _mk_details(label, conf, feedback)
        chat_state["details_visible"] = True

        ### Prepares output bot
        if next_id is None:
            chat_state["pending_card_id"] = None
            chat_state["phase"] = "done"
            chat_state["final_plot_counts"] = dict(chat_state.get("grade_counts", {}))

            avg_conf = (chat_state["conf_sum"] / max(1, chat_state["graded"])) * 100
            recap = (
                f"{emoji.emojize(':party_popper:')} Plus de cartes dues.\n\n"
                f"**Récap session**:\n"
                f"- Questions notées: **{chat_state['graded']}**\n"
                f"- Moyenne confiance: **{avg_conf:.2f} %**\n"
                f"- Again/Hard/Good/Easy: "
                f"{chat_state['grade_counts'].get('Again', 0)}/"
                f"{chat_state['grade_counts'].get('Hard', 0)}/"
                f"{chat_state['grade_counts'].get('Good', 0)}/"
                f"{chat_state['grade_counts'].get('Easy', 0)}\n\n"
                "Tu veux **changer de texte** ou **générer plus de cartes** sur le même texte ?\n"
                "*(Tu peux aussi taper `détails`.)*"
            )

            bot = (
                f"{emoji.emojize(':party_popper:')} Session terminée.\n\n"
                f"{recap}"
            )
            history = _add_turn(history, msg, bot)
            return _ret_chat_send(history, chat_state, bot_text=bot)

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
        choice = msg.strip().lower()

        cid = chat_state.get("pending_card_id")
        card = _repo().get_by_id(int(cid)) if cid else None
        if not card:
            chat_state["phase"] = "idle"
            bot = emoji.emojize(":cross_mark:") + " Carte introuvable. Clique Start pour recommencer."
            history = _add_turn(history, msg, bot)
            return _ret_chat_send(history, chat_state, bot_text=bot)

        if "réess" in choice or "reess" in choice:
            chat_state["phase"] = "quiz_answer"
            bot = f"OK ! {emoji.emojize(':brain:')} **Même question :** {card.question}"
            history = _add_turn(history, msg, bot)
            return _ret_chat_send(history, chat_state, bot_text=bot)

        if "pass" in choice or "suiv" in choice:
            sid = chat_state.get("source_id")
            next_id, status, question, info = grade_card(int(cid), "Again", source_id=sid)

            if next_id is None:
                chat_state["phase"] = "idle"
                chat_state["pending_card_id"] = None
                bot = emoji.emojize(':check_mark_button:') + " OK, on passe. " + emoji.emojize(':party_popper:') + " Plus de cartes dues."
                history = _add_turn(history, msg, bot)
                return _ret_chat_send(history, chat_state, bot_text=bot)

            chat_state["pending_card_id"] = next_id
            chat_state["phase"] = "quiz_answer"
            bot = f"{emoji.emojize(':check_mark_button:')} OK, on passe.\n\n{emoji.emojize(':brain:')} **Question suivante :** {question}"
            history = _add_turn(history, msg, bot)
            return _ret_chat_send(history, chat_state, bot_text=bot)

        bot = "Je n’ai pas compris. Réponds: `réessayer` ou `passer`."
        history = _add_turn(history, msg, bot)
        return _ret_chat_send(history, chat_state, bot_text=bot)

    ### Fallback
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
    chat_state = reset_chat_state(model="qwen2.5:7b-instruct")
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
