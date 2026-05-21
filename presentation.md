# NeuroCI — Lecture Slide Deck

---

# Title
NeuroCI — The Self‑Healing CI/CD Pipeline

Presenter: [Your Name]
Course: [Course / Lecture]
Date: [Date]

Note: Quick 10–15 minute demo + 10 minute Q&A

---

# Slide 1 — Motivation
- CI failures interrupt developer flow
- Average time lost: 23 minutes per failure
- Many failures are small, repeatable, and fixable

Note: Explain why automation matters; give a quick anecdote

---

# Slide 2 — Problem Statement
- Pipelines fail often (43% repeat patterns)
- Manual fixes cost developer time and context switching
- Need: fast, safe, automated repair

Note: Emphasize ROI and developer productivity

---

# Slide 3 — High-Level Architecture
- FastAPI webhook receiver
- Redis + Celery for async processing
- LangChain + multi-LLM providers for diagnosis & patching
- ChromaDB for RAG memory
- OPA for policy gating
- GitHub API for PR creation

Reference: see `VISUAL_OVERVIEW.md` for diagrams

Note: Point to the architecture file for technical audience

---

# Slide 4 — Pipeline Flow (Simplified)
1. GitHub Actions fails → webhook
2. Parse logs → classify failure (LLM)
3. Retrieve similar fixes (RAG)
4. Generate patch (LLM) → validate
5. Policy check → Auto-PR or Slack alert

Note: Walk through this flow slowly during demo setup

---

# Slide 5 — Failure Categories
- Patchable: ImportError, SyntaxError, TypeMismatch, TestAssertion, ConfigMissing, DependencyConflict, LogicBug
- Non-patchable: Flaky tests, Auth, Network

Note: Give examples from `tests/fixtures/`

---

# Slide 6 — Demo Plan
- Quick local demo using `docker compose up`
- Trigger sample failing workflow (pre-made fixtures)
- Show generated patch & PR flow (or simulated PR)

Note: Keep demo short; show result & explain decision logic

---

# Slide 7 — Live Demo (Commands)
PowerShell commands you will run during lecture:

```powershell
# 1) Start local stack
docker compose up -d

# 2) Check services
docker compose ps

# 3) Run test webhook (example fixture)
curl -X POST http://localhost:8000/api/v1/webhook/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: workflow_run" \
  -H "X-GitHub-Delivery: demo-1" \
  -d @tests/fixtures/sample_logs/sample_workflow_run.json
```

Note: If network calls are disabled, show pre-recorded output

---

# Slide 8 — Results & Metrics
- Typical repair time: 30–60s
- Auto-PR threshold: confidence ≥ 0.85
- Success rate target: 85%+
- Observability: Prometheus & Grafana dashboards

Note: Show screenshot from `grafana/dashboards/neuroci.json` if available

---

# Slide 9 — Safety & Policy
- HMAC verification for webhooks
- AST + Flake8 validation for patches
- OPA Rego policies for governance
- Multi-agent debate for high-risk LogicBugs

Note: Reassure about low risk of harmful automated changes

---

# Slide 10 — Roadmap & Extensions
- Add multi-language patching (JS, Go, Rust)
- Fine-tune model on merged PRs
- Integrate tracing (Jaeger)
- Enterprise integration: SSO, audit logs

Note: Invite suggestions from the class

---

# Slide 11 — Q&A
- Live questions
- Offer guided walkthrough after class

Note: Keep 10 minutes for discussion

---

# Appendix — References
- `PROJECT_OVERVIEW.md`
- `ARCHITECTURE_DEEP_DIVE.md`
- `QUICK_REFERENCE.md`

Note: Share repository link with class
