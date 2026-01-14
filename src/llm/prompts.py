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