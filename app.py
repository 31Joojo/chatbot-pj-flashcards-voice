# app.py
### Modules importation
from pathlib import Path
import emoji
import gradio as gr

from src.storage.repo import FlashcardRepo
from src.ui.state import default_chat_state
from src.ui.chat_flow import set_repo as set_chat_repo, chat_start, chat_send, chat_send_audio, chat_reset_to_start, \
    show_details, chat_start_review

### Setting repo for storing flashcards
DB_PATH = Path("data/flashcards.db")
repo = FlashcardRepo(DB_PATH)
set_chat_repo(repo)
tts_dir = str(Path("data/tts").resolve())

### Style
CSS_PATH = Path(__file__).parent / "src" / "ui" / "assets" / "style.css"
APP_CSS = CSS_PATH.read_text(encoding="utf-8") if CSS_PATH.exists() else ""

### Header
WELCOME_HEADER = "## Bonjour, je suis AudrAI. Quel cours veux-tu réviser aujourd’hui ?"

### ------------------------------ Helpers ------------------------------ ###
### Helper : refresh_courses()
def refresh_courses():
    """
    Refresh the list of available courses for the UI selector.

    This helper queries the database for the most recent sources
    and formats them as (label, value) pairs compatible with
    Gradio dropdown components.

    :return gr.update: Gradio update object with refreshed choices
    """
    ### Fetch recent sources from the repository
    sources = repo.list_sources(limit=200)

    ### Convert sources to (title, id) tuples expected by gr.Dropdown
    return gr.update(choices=[(s["title"], s["id"]) for s in sources])

### Helper : _get_title_for_source()
def _get_title_for_source(source_id: int) -> str:
    """
    Retrieve a human-readable title for a given source.

    :param int source_id: Identifier of the source
    :return str: Best available title for display
    """
    try:
        ### Search through known sources
        for s in repo.list_sources(limit=500):

            ### Match the requested source identifier
            if int(s.get("id", 0)) == int(source_id):

                ### Retrieve explicit title when available
                t = (s.get("title") or "").strip()
                if t:
                    return t

                ### Fallback to preview text if title is missing
                p = (s.get("preview") or "").strip()
                if p:
                    return p

    except Exception:
        pass

    ### Final fallback if nothing was found
    return f"Cours {source_id}"

### ------------------------------ Wrappers ----------------------------- ###
def chat_start_ui(source_text, model, history, chat_state, tts_on):
    """
    UI wrapper for starting a flashcard creation session.

    :param source_text: Source text provided by the user
    :param model: Ollama model name
    :param history: Current chat history
    :param chat_state: Chat state machine
    :param tts_on: Whether text-to-speech is enabled
    :return tuple: chat_start outputs extended with a UI header update
    """
    ### Delegate core logic to the shared chat_start handler
    out = chat_start(source_text, model, history, chat_state, tts_on)

    ### UI header for flashcard creation mode
    header = "## Création de flashcards"

    ### Append header update to the original outputs
    return *out, gr.update(value=header)

def chat_start_review_ui(source_id, model, history, chat_state, tts_on):
    """
    UI wrapper for starting a review session.

    :param source_id: Identifier of the source to review
    :param model: Ollama model name
    :param history: Current chat history
    :param chat_state: Chat state machine
    :param tts_on: Whether text-to-speech is enabled
    :return tuple: chat_start_review outputs extended with a UI header update
    """
    ### Delegate review initialization to the core handler
    out = chat_start_review(source_id, model, history, chat_state, tts_on)

    ### Build a descriptive header when a source is selected
    if source_id:
        title = _get_title_for_source(int(source_id))
        header = f"## Session de révision — {title}"
    else:
        header = "## Session de révision"

    ### Append header update to the original outputs
    return *out, gr.update(value=header)

def chat_reset_to_start_ui(chat_state):
    """
    UI wrapper for resetting the chat to its initial state.

    :param chat_state: Current chat state
    :return tuple: Reset outputs extended with a UI header update
    """
    ### Reset the chat state and UI panels
    out = chat_reset_to_start(chat_state)

    ### Restore the welcome header
    return *out, gr.update(value=WELCOME_HEADER)

### ------------------------- ###
###   Gradio user interface   ###
### ------------------------- ###
### Main Gradio application container
with gr.Blocks(title="AudrAI") as demo:
    ### Application title
    chat_header = gr.Markdown(WELCOME_HEADER, elem_id="chat_header")

    ### ------------------------- ###
    ###    Chat interaction tab   ###
    ### ------------------------- ###
    with gr.Tab("Chat"):
        ### Central state object storing the conversational state machine
        chat_state = gr.State(default_chat_state())

        ### Panels used to switch between start and chat views
        start_panel = gr.Group(visible=True)
        chat_panel = gr.Group(visible=False, elem_id="session_root")

        ### -------- Start panel : source text --------
        with start_panel:
            with gr.Column(variant="panel", elem_classes="start_content"):
                chat_source = gr.Textbox(
                    lines=12,
                    label="Entrée texte",
                    info="Dans cet espace, tu fourniras le texte qui permettra de lancer ta session de révision.",
                    placeholder="Colle le contenu de ton cours ici :",
                    autoscroll=True,
                    interactive=True,
                    elem_id="textbox_style"
                )

                btn_start = gr.Button("Commencer", variant="primary", elem_classes="btn_start")

                sources = repo.list_sources(limit=200)
                course_dd = gr.Dropdown(
                    choices=[(s["title"], s["id"]) for s in sources],
                    label="Sélecteur de cours à réviser",
                    interactive=True,
                    value=sources[0]["id"] if sources else None,
                )

                btn_review = gr.Button("Réviser ce cours", variant="primary", elem_classes="btn_review")

            with gr.Accordion("Paramètres", open=False):
                chat_model = gr.Textbox(value="qwen2.5:7b-instruct", label="Modèle Ollama")

        ### ----- Chat panel : active conversation ----
        with chat_panel:
            with gr.Row(equal_height=True, elem_id="session_row"):
                ### Left column : conversation and inputs
                with gr.Column(scale=3, elem_id="session_left"):
                    with gr.Group(elem_id="chat_scroller"):
                        chat = gr.Chatbot(label="", show_label=False, height=420)

                    with gr.Group(elem_id="composer"):
                        ### Microphone input
                        mic = gr.Audio(sources=["microphone"], type="filepath", label="", show_label=False, visible=False, elem_id="mic_rec")
                        mic_mode = gr.State(False)
                        btn_record = gr.Button("Parler", variant="primary")

                        with gr.Row(equal_height=True):
                            ### Text-based user input
                            user = gr.Textbox(
                                label="",
                                lines=1,
                                max_lines=2,
                                show_label=False,
                                placeholder="Écris ton message ici",
                                elem_id="text_input",
                                scale=8,
                                autoscroll=True,
                            )

                            ### Send buttons
                            send = gr.Button("Envoyer", scale=1, variant="stop", icon="src/ui/assets/send_6532019.png")

                        ### Reset the session with a new source text
                        btn_change_text = gr.Button("Changer de texte", variant="primary", elem_id="change_text_btn")

                        ### Enable or disable text-to-speech for bot responses
                        tts_on = gr.Checkbox(
                            label=f"{emoji.emojize(':speaker_high_volume:')} Lire les réponses à voix haute",
                            value=True,
                            elem_id="tts_toggle"
                        )

                        ### Audio player for synthesized bot responses
                        bot_audio = gr.Audio(
                            type="filepath",
                            autoplay=True,
                            label="",
                            show_label=False,
                            elem_id="bot_audio",
                        )

                ### Right column: sidebar
                with gr.Column(scale=1, elem_id="session_right"):
                    btn_details = gr.Button("Afficher la correction", visible=True)
                    details_md = gr.Markdown(value="", visible=False, elem_id="details_panel")
                    stats_plot = gr.Plot(label="", show_label=False, visible=False, elem_id="stats_plot")

        ### -------------- Event bindings -------------
        ### Start a new chat session
        btn_start.click(
            chat_start_ui,
            inputs=[chat_source, chat_model, chat, chat_state, tts_on],
            outputs=[chat, chat_state, start_panel, chat_panel, details_md, bot_audio, stats_plot, chat_header],
        ).then(
            refresh_courses, outputs=[course_dd]
        )

        ### Start a revision session
        btn_review.click(
            chat_start_review_ui,
            inputs=[course_dd, chat_model, chat, chat_state, tts_on],
            outputs=[chat, chat_state, start_panel, chat_panel, details_md, bot_audio, stats_plot, chat_header],
        )

        ### Send a text message
        send.click(
            chat_send,
            inputs=[user, chat, chat_state, tts_on],
            outputs=[chat, chat_state, user, details_md, bot_audio, stats_plot],
        )

        ### Submit message
        user.submit(
            chat_send,
            inputs=[user, chat, chat_state, tts_on],
            outputs=[chat, chat_state, user, details_md, bot_audio, stats_plot],
        )

        ### Helper : toggle_mic_mode()
        def toggle_mic_mode(mode: bool):
            """
            Toggle between text input mode and microphone input mode.

            :param bool mode: Current microphone mode state
            :return tuple: Updated mode flag and Gradio visibility updates
            """
            ### Toggle the current mode
            mode = not mode

            ### mode True -> show microphone and hide text input and send button
            ### mode False -> hide microphone and show text input and send button
            return (
                mode,
                ### Mic input
                gr.update(visible=mode),
                ### Text input
                gr.update(visible=not mode),
                ### Send button
                gr.update(visible=not mode),
            )

        ### Button to record voice message
        btn_record.click(
            toggle_mic_mode,
            inputs=[mic_mode],
            outputs=[mic_mode, mic, user, send],
        )

        ### Automatically send audio when recording ends
        mic.change(
            chat_send_audio,
            inputs=[mic, chat, chat_state, tts_on],
            outputs=[chat, chat_state, user, details_md, bot_audio, stats_plot],
        ).then(
            ### Clear audio buffer
            lambda: gr.update(value=None),
            inputs=None,
            outputs=[mic],
        )

        ### Reset chat to the initial start screen
        btn_change_text.click(
            chat_reset_to_start_ui,
            inputs=[chat_state],
            outputs=[chat, chat_state, start_panel, chat_panel, details_md, bot_audio, stats_plot, mic, user, chat_header],
        )

        ### Toggle visibility of grading details
        btn_details.click(
            show_details,
            inputs=[chat, chat_state],
            outputs=[chat, chat_state, details_md],
        )

### ------------------------- ###
###    Application launch     ###
### ------------------------- ###
try:
    demo.launch(
        show_error=True,
        debug=True,
        inline=False,
        css=APP_CSS,
        allowed_paths=[tts_dir],
        theme=gr.themes.Soft()
    )
except Exception as e:
    print(f"Erreur lors du lancement : {e}")
