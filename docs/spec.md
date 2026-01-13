# Project Specification — VocaCards Adaptive Voice Flashcards

---
## 1. Context & problem
Effective revision requires active repetition, but students often revise passively by rereading. Oral skills are even less practiced, even though they are crucial (exams, presentations, languages, etc.).

---

## 2. Purpose of the chatbot 
Build a voice-first revision app that:
1) transforms content (text/small PDF) into flashcards,
2) runs a quiz session,
3) evaluates the answer (correct/partial/incorrect),
4) plans the next revision using spaced repetition,
5) tracks progress.


---

## 3. Target users
- Students
- Language learners/certification candidates
- Anyone who wants to study on the go (walking, commuting)

---

## 4. Proposition de valeur
- Active review and immediate feedback
- Voice mode for reviewing without a screen
- Reviews tailored to your actual level (errors and confidence)

---

## 5. User stories (MVP)
- US1 — As a user, I paste text and generate a deck of flashcards.
- US2 — As a user, I start a session and respond (text or voice).
- US3 — As a user, I receive corrections and concise feedback.
- US4 — As a user, I see my results and know which cards to review.
- US5 — As a user, difficult cards automatically reappear sooner.

---

## 6. Non-objectives
- Multi-accounts / authentication
- Cloud synchronization
- Advanced design
- Large RAG corpus
- Complex analytics

---

## 7. Detailed features

### 7.1 Import content
**MVP**
- “Paste text” area
**Option**
- Upload PDF (text extraction)

### 7.2 Flashcard generation (LLM)
Expected output per card :
- Question
- Expected answer (reference)
- Tags (chapter/theme)
- Difficulty (1–3)

Constraints :
- Short questions
- Short expected answers or key points
- Strict JSON to facilitate parsing

### 7.3 Quiz session
Session states:
- current card
- user attempt (text or voice)
- correction (LLM)
- score `0/0.5/1` or `wrong/partial/correct`
- user confidence `confident/moderate/uncertain`

Actions:
- answer
- repeat question
- skip
- show answer
- finish

### 7.4 Automatic evaluation
Rubric (MVP) :
- verdict : correct / partial / incorrect
- feedback : 1–2 sentences max
- missing points (short list, optional)

### 7.5 Spaced repetition
Simple algorithm (MVP) :
- incorrect → review soon (e.g., +5 min or +1 day depending on mode)
- partial → average interval
- correct + high confidence → longer interval

Visible outputs :
- “next review” by card
- “cards to review” (list)

### 7.6 Vocal: STT & TTS
- STT : user responds orally, transcription into text
- TTS (optional): reading of the question and/or feedback aloud
Fallback:
- text mode always available (demo security)

---

## 8. Technical pipeline
1) Content import → text extraction
2) Deck generation (LLM) → storage
3) Session: question → user response (audio → STT and text)
4) Correction (LLM) → score + feedback
5) Scheduler : next_review update
6) Results display

---

## 9. Data & storage
- Option 1 : Local JSON (deck + attempts + next_review)
- Option 2 : SQLite
- Test sets : 2–3 short texts in `data/samples/`

---

## 10. Success criteria (demo-ready)
- Generate a deck from text in < 30 seconds
- Launch a session of 5 questions
- Show at least 1 error → feedback + reprogrammed card
- Functional voice mode OR functional text fallback

---

## 11. Risks & mitigation
- Unstable STT (microphone/noise) → text fallback + upstream testing
- Unparseable LLM responses → JSON format + validate + retry
- Fragile live demo → sample data ready + “demo_script.md” + text mode

