# src/llm/prompts.py

FLASHCARDS_PROMPT = """Tu es un assistant pédagogique.

Objectif:
- Générer {n} flashcards à partir d'un texte source.
- Les QUESTIONS doivent être en français.
- Les RÉPONSES doivent être en français (tu peux garder les termes techniques en anglais si nécessaire).
- Le texte source peut être en anglais.

Contraintes:
- Réponds en JSON STRICT, sans markdown, sans texte autour.
- Format attendu:
{{
  "cards": [
    {{
      "question": "...",
      "answer": "...",
      "hint": "",
      "tags": ["..."]
    }}
  ]
}}

Texte source:
\"\"\"{source_text}\"\"\"
"""

GRADE_PROMPT = """Tu es un correcteur strict.
Compare la question, la réponse attendue et la réponse de l'élève.
Retourne UNIQUEMENT un JSON valide (pas de texte autour) avec les clés:
- grade: "Again" | "Hard" | "Good" | "Easy"
- confidence: nombre entre 0 et 1
- feedback: string court (1-2 phrases)
Question: {question}
Réponse attendue: {expected}
Réponse élève: {student}
"""

EXPLAIN_PROMPT = """Tu es un tuteur.
Explique la réponse attendue de manière simple en 2-4 phrases, avec un mini exemple si utile.
Ne mets pas de markdown, juste du texte.

Question: {question}
Réponse attendue: {expected}
Réponse élève: {student}
"""