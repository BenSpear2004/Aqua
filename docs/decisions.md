# Decisions

Each entry records the decision, the alternatives considered, and why.

## October 2026: Stack and layout

**Decision.** FastAPI backend with the NL2SQL pipeline in `backend/nl2sql/`, React and Vite frontend, Gemini API (AI Studio keys) as the model, PostgreSQL on Tiger Cloud as the database, deployed with docker-compose at `/srv/bank-ai`.

**Alternatives.** Streamlit UI with code in `src/nl2sql/` (the original plan); Ollama as the primary model (the starter code).

**Reasoning.** The repo already had a working FastAPI, React, and docker-compose setup, and the frontend owner is building in React, so Streamlit would have been thrown away. Gemini's free API tier is stronger than models the server can run locally. Ollama stays available for serving the fine-tuned open model later, behind the same `llm.py` interface. The model name is read from env so the team can switch to whichever Gemini or Gemma model performs best without code changes.
