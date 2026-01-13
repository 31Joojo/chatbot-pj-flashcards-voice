# Chatbot & Generative AI — Final project

## VocaCards — Flashcards vocales adaptatives

## Authors :
    * FOFANA Rayane
    * LARMAILLARD-NOIREN Joris
    * Groupe DAI - Promo 2026

---

## Pitch
VocaCards is a **voice-first** revision app: it generates a deck of flashcards from course text,
launches a quiz session, corrects answers, and automatically schedules revisions using simple spaced repetition.

---

## Main features
- Content import (pasted text or PDF)
- Automatic generation of a flashcard deck (question/answer/level/tags)
- Quiz session (question → answer → correction → score)
- Spaced repetition (cards you get wrong come back sooner)
- History and local backup (JSON or SQLite)

---

## Innovation key points
- **Voice review** (STT) : the user responds orally
- **Automatic evaluation** : correct/partial/incorrect + brief feedback
- **Adaptive spaced repetition** based on performance + user confidence

> Note: TTS, voice reading of questions is optional. The MVP is “voice-in,” voice response, with text display of questions.

---

## Demo
1) Paste sample text (provided in `data/samples/`)
2) Generate 5 flashcards
3) Start a session : answer 2 questions (microphone or fallback text)
4) Show the correction + reprogramming of a failed card (“review sooner”)

> Le mode texte sert de plan B si l’audio pose problème.

---

## Quick architecture overview
- UI : Gradio
- Core : Deck / Flashcard / Attempt + scheduler (spaced repetition)
- LLM : flashcard generation + correction
- Speech : STT (recommended) + TTS (optional)
- Storage : JSON (MVP) then SQLite if necessary

---

## Launch the application
```bash
python app.py
```

---

## Repo structure
```text
flashcards-voice/
  app.py
  src/
    core/
    llm/
    speech/
    storage/
  data/
    samples/
  docs/
    spec.md
    demo_script.md
```

