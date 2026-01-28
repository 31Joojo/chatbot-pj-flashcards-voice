# src/llm/prompts.py

FLASHCARDS_PROMPT = """Tu es un assistant pédagogique.

Objectif:
- Générer {n} flashcards à partir d'un texte source.
- Générer un titre court à partir d'un texte source.
- Les QUESTIONS doivent être en français.
- Les RÉPONSES doivent être en français (tu peux garder les termes techniques en anglais si nécessaire).
- Le texte source peut être en anglais.

Contraintes:
- Réponds en JSON STRICT, sans markdown, sans texte autour.
- Le champ "title" est une CHAÎNE de caractères.
- Le titre "title" doit résumer le thème central en 3 à 10 mots.
- IMPORTANT: ne copie pas une phrase du texte. Ne reprends pas mot pour mot le début du texte.
- Pas d'émojis, pas de guillemets, pas de "..." ni de "…", pas de ponctuation finale.
- Le champ "cards" est une LISTE de {n} objets.
- Le champ "tags" est une LISTE de 1 à 3 tags courts.
- Format attendu:
{{
  "title": "...",
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
Compare la question, la réponse attendue et la réponse de l'élève. TU DOIS RÉPONDRE UNIQUEMENT EN FRANÇAIS.
Retourne UNIQUEMENT un JSON valide (pas de texte autour) avec les clés:
- grade: "Again" | "Hard" | "Good" | "Easy"
- confidence: nombre entre 0 et 1
- feedback: string court (1-2 phrases)
Question: {question}
Réponse attendue: {expected}
Réponse élève: {student}
"""

EXPLAIN_PROMPT = """Tu es un tuteur.
Explique la réponse attendue de manière simple en 2-4 phrases, uniquement en FRANÇAIS, avec un mini exemple si utile.
Ne mets pas de markdown, juste du texte.

Question: {question}
Réponse attendue: {expected}
Réponse élève: {student}
"""