# app.py
### Modules importation
from pathlib import Path
import emoji
import gradio as gr

from src.storage.repo import FlashcardRepo
from src.ui.review_flow import load_due_card, reveal_answer, grade_again, grade_hard, grade_good, grade_easy
from src.ui.state import default_chat_state
from src.ui.chat_flow import set_repo as set_chat_repo, chat_start, chat_send, chat_send_audio, chat_reset_to_start, \
    show_details, _toggle_mic

### Setting repo for storing flashcards
DB_PATH = Path("data/flashcards.db")
repo = FlashcardRepo(DB_PATH)
set_chat_repo(repo)
tts_dir = str(Path("data/tts").resolve())

CSS = """
#stats_plot { animation: fv-pop .22s ease-out; }
@keyframes fv-pop { from { transform: scale(.97); opacity: 0; } to { transform: scale(1); opacity: 1; } }

#details_md { animation: fv-pop .18s ease-out; }
"""

### ------------------------- ###
###   Gradio user interface   ###
### ------------------------- ###

### Main Gradio application container
with gr.Blocks(title="Flashcards Voice MVP") as demo:
    ### Application title
    gr.Markdown(f"# {emoji.emojize(':headphone:')} Flashcards Voice")

    ### ------------------------- ###
    ###    Chat interaction tab   ###
    ### ------------------------- ###
    with gr.Tab("Chat"):
        gr.Markdown("### Mode Chat (Start → Génération → Quiz)")

        ### Central state object storing the conversational state machine
        chat_state = gr.State(default_chat_state())

        ### Panels used to switch between start and chat views
        start_panel = gr.Group(visible=True)
        chat_panel = gr.Group(visible=False)

        ### -------- Start panel : source text --------
        with start_panel:
            chat_model = gr.Textbox(value="qwen2.5:7b-instruct", label="Modèle Ollama")
            chat_source = gr.Textbox(lines=10, label="Texte source (à coller ici)")
            btn_start = gr.Button("Start")

        ### ----- Chat panel : active conversation ----
        with chat_panel:
            with gr.Row():
                ### Left column : conversation and inputs
                with gr.Column(scale=3):
                    chat = gr.Chatbot(label="Flashcards Bot")

                    ### Toggle between text input and microphone input
                    use_mic = gr.Checkbox(label=f"{emoji.emojize(':studio_microphone:')}️ Utiliser le micro",
                                          value=False)

                    ### Text-based user input
                    user = gr.Textbox(label="Message", placeholder="Ex: 8, puis tes réponses...")

                    ### Microphone input
                    mic = gr.Audio(sources=["microphone"], type="filepath", label="Micro (audio)", visible=False)

                    ### Send buttons
                    send = gr.Button("Envoyer")
                    btn_mic = gr.Button("Envoyer (micro)", visible=False)

                    ### Reset the session with a new source text
                    btn_change_text = gr.Button("Changer de texte", variant="secondary")

                    ### Enable or disable text-to-speech for bot responses
                    tts_on = gr.Checkbox(
                        label=f"{emoji.emojize(':speaker_high_volume:')} Lire les réponses à voix haute", value=True)

                    ### Audio player for synthesized bot responses
                    bot_audio = gr.Audio(type="filepath", autoplay=True)

                ### Right column: sidebar
                with gr.Column(scale=1, elem_id="sidebar"):
                    btn_details = gr.Button("Détails (dernière correction)", visible=True)
                    details_md = gr.Markdown(value="", visible=False, elem_id="details_md")
                    stats_plot = gr.Plot(label="Récap session", visible=False, elem_id="stats_plot")

        ### -------------- Event bindings -------------
        ### Start a new chat session
        btn_start.click(
            chat_start,
            inputs=[chat_source, chat_model, chat, chat_state, tts_on],
            outputs=[chat, chat_state, start_panel, chat_panel, details_md, bot_audio, stats_plot],
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

        ### Toggle microphone mode
        use_mic.change(
            _toggle_mic,
            inputs=[use_mic],
            outputs=[mic, btn_mic, user, send]
        )

        ### Send audio input via microphone button
        btn_mic.click(
            chat_send_audio,
            inputs=[mic, chat, chat_state, tts_on],
            outputs=[chat, chat_state, user, details_md, bot_audio, stats_plot],
        ).then(
            ### Reset microphone input after processing
            lambda: gr.update(value=None),
            inputs=None,
            outputs=[mic],
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
            chat_reset_to_start,
            inputs=[chat_state],
            outputs=[chat, chat_state, start_panel, chat_panel, details_md, bot_audio, stats_plot, mic, user],
        )

        ### Toggle visibility of grading details
        btn_details.click(
            show_details,
            inputs=[chat, chat_state],
            outputs=[chat, chat_state, details_md],
        )

    ### ------------------------- ###
    ###  Flashcard creation tab   ###
    ### ------------------------- ###
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

    ### ------------------------- ###
    ###     Manual review tab     ###
    ### ------------------------- ###
    with gr.Tab("Réviser"):
        card_id = gr.State(value=None)

        btn_load = gr.Button("Charger une carte due")
        info = gr.Markdown()
        question = gr.Markdown("—")
        answer = gr.Markdown("—")
        btn_reveal = gr.Button("Afficher la réponse")

        ### Grading buttons
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

### ------------------------- ###
###    Application launch     ###
### ------------------------- ###
try:
    demo.launch(
        show_error=True,
        debug=True,
        inline=False,
        css=CSS,
        allowed_paths=[tts_dir]
    )
except Exception as e:
    print(f"Erreur lors du lancement : {e}")
