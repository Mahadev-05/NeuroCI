NeuroCI — One-Page Handout

NeuroCI — The Self-Healing CI/CD Pipeline

What it does
- Detects CI failures, diagnoses root cause, generates and validates patches, and creates PRs automatically when safe.

Why it matters
- 43% of CI failures are repeatable
- Saves ~23 min per failure
- Target: 4× MTTR improvement

Architecture (high level)
- Webhook (FastAPI) → Redis → Celery → LLM pipeline (LangChain) → ChromaDB (RAG) → OPA → GitHub PRs

Top features
- Multi-LLM support (Gemini/Groq/Ollama/OpenAI)
- RAG memory with ChromaDB
- Policy gating with OPA
- Patch validation (Flake8 + AST)
- Prometheus + Grafana observability

Quick demo steps
1. `docker compose up -d`
2. `curl -X POST http://localhost:8000/api/v1/webhook/github -H "Content-Type: application/json" -H "X-GitHub-Event: workflow_run" -H "X-GitHub-Delivery: demo-1" -d @tests/fixtures/sample_logs/sample_workflow_run.json`
3. Check `docker compose logs worker` for `patch_generated`

Key metrics
- End-to-end repair: 30–60s
- Auto-PR threshold: confidence ≥ 0.85
- Success rate target: 85%+

Contact
- Repo: [your repo URL]
- Questions: [Your email]

Thank you — demo after the slides!