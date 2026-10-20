# Poisoned fixtures

Documents that try to attack the RAG system through their own text (indirect prompt injection):

- `ignore_instructions.md` — classic "ignore previous instructions", a fake `</source>` delimiter and a fake system tag.

`tests/integration/test_prompt_injection.py` uploads these and checks that they cannot change the system's behaviour, leak
the system prompt, or leak other documents. Keep them passing (CLAUDE.md testing rules). Add new attack texts here.
