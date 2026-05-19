<div align="center">

# 🧠 NeuroCI

### The Self-Healing Pipeline

**An LLM-powered autonomous CI/CD repair system that watches your pipelines, diagnoses failures, generates targeted code patches, and submits pull requests — without human intervention.**

[![CI](https://img.shields.io/badge/CI-GitHub_Actions-2088FF?logo=github-actions&logoColor=white)](/.github/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangChain](https://img.shields.io/badge/LangChain-0.3+-1C3C3C?logo=langchain&logoColor=white)](https://langchain.com)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

---

## 📊 The Problem

| Metric | Value |
|--------|-------|
| CI failures that are repeat patterns | **43%** |
| Avg developer time lost per CI failure | **23 min** |
| Fixable bugs needing ≤5 line changes | **~60%** |
| MTTR improvement target | **4×** |

## 🏗️ Architecture

```
Developer pushes code
         │
    GitHub Actions runs
         │
    ┌─────┴─────┐
    │  Pipeline  │
    │  Fails     │
    └─────┬─────┘
          │ workflow_run webhook
          ▼
    ┌──────────────┐
    │  FastAPI      │ ◄── HMAC-SHA256 verified
    │  Webhook      │     + Redis dedup
    │  Server       │
    └──────┬───────┘
           │ Redis queue
           ▼
    ┌──────────────┐     ┌────────────┐
    │  Celery       │────►│  ChromaDB   │ RAG lookup
    │  Worker       │     │  (Memory)   │
    └──────┬───────┘     └────────────┘
           │
    ┌──────┴───────┐
    │  LLM Agent    │ Gemini / Groq / Ollama / OpenAI
    │  (LangChain)  │
    │               │
    │  1. Classify   │
    │  2. Retrieve   │
    │  3. Generate   │
    │  4. Validate   │
    └──────┬───────┘
           │
    ┌──────┴───────┐     ┌────────────┐
    │  OPA Policy   │────►│  Rego Rules │
    │  Gate         │     └────────────┘
    └──────┬───────┘
           │
    ┌──────┴───────────────┐
    │                       │
    ▼                       ▼
┌────────┐          ┌─────────────┐
│ Auto-PR │          │ Slack Notify │
│ (≥0.85) │          │ (<0.85)      │
└────┬───┘          └──────┬──────┘
     │                      │
     └──────────┬───────────┘
                ▼
    ┌───────────────────┐
    │  Feedback Loop     │
    │  PR merged/rejected│
    │  → ChromaDB update │
    └───────────────────┘
```

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Docker & Docker Compose
- GitHub Personal Access Token
- LLM API Key (one of):
  - **Google Gemini** (free) — recommended
  - **Groq** (free tier)
  - **Ollama** (free, runs locally)
  - **OpenAI** (paid)

### 1. Clone & Configure

```bash
git clone https://github.com/your-org/neuroci.git
cd neuroci
cp .env.example .env
# Edit .env — set LLM_PROVIDER and the corresponding API key
```

### 2. Run with Docker Compose

```bash
docker compose up
```

This starts all 7 services:
- **Webhook Server** → `http://localhost:8000`
- **Celery Worker** → Processing repairs
- **Redis** → Message broker + dedup store
- **ChromaDB** → Vector memory (RAG)
- **OPA** → Policy engine
- **Prometheus** → Metrics (`http://localhost:9090`)
- **Grafana** → Dashboards (`http://localhost:3000`)

### 3. Configure GitHub Webhook

In your repository's Settings → Webhooks → Add webhook:
- **URL:** `https://your-server.com/api/v1/webhook/github`
- **Content type:** `application/json`
- **Secret:** Your `GITHUB_WEBHOOK_SECRET` from `.env`
- **Events:** Select **"Workflow runs"** and **"Pull requests"** (for feedback loop)

### 4. Run Locally (Development)

```bash
pip install -e ".[dev]"
uvicorn src.main:app --reload --port 8000
```

## 📁 Project Structure

```
neuroci/
├── src/
│   ├── main.py                 # FastAPI application
│   ├── config.py               # Settings (pydantic-settings)
│   ├── models.py               # Data models & enums
│   ├── webhook/
│   │   ├── receiver.py         # Webhook endpoint + PR feedback
│   │   └── security.py         # HMAC verification
│   ├── pipeline/
│   │   ├── github_client.py    # GitHub API client
│   │   └── log_parser.py       # CI log extraction
│   ├── agent/
│   │   ├── classifier.py       # Failure classification
│   │   ├── patch_generator.py  # CoT patch generation
│   │   ├── debate.py           # Multi-agent debate
│   │   ├── validator.py        # Syntax validation
│   │   ├── repair_agent.py     # Pipeline orchestrator
│   │   ├── llm_factory.py      # Multi-provider LLM factory
│   │   └── prompts.py          # LLM prompt templates
│   ├── memory/
│   │   └── vector_store.py     # ChromaDB RAG
│   ├── policy/
│   │   └── opa_client.py       # OPA policy evaluation
│   ├── notifications/
│   │   └── slack_bot.py        # Slack integration
│   ├── metrics/
│   │   └── prometheus.py       # Prometheus metrics
│   └── tasks/
│       └── repair_task.py      # Celery tasks
├── policies/
│   └── neuroci.rego            # OPA policy rules
├── k8s/                        # Kubernetes manifests
├── helm/neuroci/               # Helm chart
├── terraform/                  # IaC (GCP + AWS, multi-provider LLM)
├── grafana/                    # Dashboard configs
├── prometheus/                 # Prometheus config
├── tests/                      # Unit & integration tests
├── Dockerfile                  # Production image
├── docker-compose.yml          # Local dev stack
├── pyproject.toml              # Dependencies
└── LICENSE                     # MIT License
```

## 🧠 How It Works

### The 11-Step Pipeline

| Step | What Happens | Component |
|------|-------------|-----------|
| 1 | Developer pushes code | Git |
| 2 | CI runs normally | GitHub Actions |
| 3 | Job fails → webhook fires | GitHub Webhook |
| 4 | Dedup check + log downloaded & parsed | Redis + Celery + GitHub API |
| 5 | Failure classified (10 types) | LLM Call #1 |
| 6 | Similar past fixes retrieved | ChromaDB RAG |
| 7 | Patch generated with CoT | LLM Call #2 |
| 8 | Patch syntax validated | ast + flake8 |
| 9 | OPA policy evaluated | OPA + Rego |
| 10 | Auto-PR or Slack approval | GitHub API / Slack |
| 11 | Feedback loop updates memory | ChromaDB (on PR merge/reject) |

### Failure Categories

| Category | Patchable | Strategy |
|----------|-----------|----------|
| ImportError | ✅ | Fix import path |
| DependencyVersionConflict | ✅ | Update version constraint |
| TestAssertion | ✅ | Fix expected values |
| FlakyTest | ❌ | Requeue + mark flaky |
| ConfigMissing | ✅ | Add config/env var |
| TypeMismatch | ✅ | Fix type annotations |
| SyntaxError | ✅ | Fix syntax |
| LogicBug | ✅ (debate) | Multi-agent debate |
| AuthError | ❌ | Slack alert only |
| NetworkTimeout | ❌ | Slack alert only |

## 🤖 LLM Providers

NeuroCI supports multiple LLM providers. Set `LLM_PROVIDER` in your `.env`:

| Provider | Cost | Setup | Performance |
|----------|------|-------|-------------|
| **Gemini** | Free | [Get API key](https://aistudio.google.com/apikey) | ⭐⭐⭐⭐ |
| **Groq** | Free tier | [Get API key](https://console.groq.com/keys) | ⭐⭐⭐⭐⭐ (fastest) |
| **Ollama** | Free (local) | [Install](https://ollama.com) → `ollama pull llama3.1` | ⭐⭐⭐ |
| **OpenAI** | Paid | [Get API key](https://platform.openai.com/api-keys) | ⭐⭐⭐⭐⭐ |

## 🔒 Safety & Governance

- **OPA/Rego policies** — version-controlled rules for what NeuroCI can do
- **File path allowlist** — never touches `infra/`, `terraform/`, `secrets.py`
- **Patch size limit** — max 20 lines changed per patch
- **Confidence thresholds** — ≥0.85 for auto-PR, ≥0.92 for main branch
- **No auto-merge** — PRs always require human approval
- **HMAC-SHA256** — all webhooks signature-verified
- **Redis dedup** — prevents duplicate processing of the same failure
- **CORS restrictions** — locked down in production

## 📈 Observability

- **Prometheus metrics** at `/metrics` — fix counts, confidence distribution, MTTR
- **Metrics API** at `/api/v1/metrics/snapshot` — structured JSON metrics
- **Grafana dashboard** with MTTR, fix rate, confidence distribution
- **Structured JSON logging** via structlog
- **Pipeline stage timing** — per-stage duration tracking
- **LangSmith tracing** (optional) for LLM call debugging

## 🚢 Deployment

### Kubernetes + Helm

```bash
helm install neuroci ./helm/neuroci \
  --set secrets.githubToken=$GITHUB_TOKEN \
  --set secrets.githubWebhookSecret=$WEBHOOK_SECRET \
  --set llm.provider=gemini \
  --set llm.gemini.apiKey=$GEMINI_API_KEY
```

### Terraform (GCP)

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your values
terraform init
terraform apply -var-file=terraform.tfvars
```

### Terraform (AWS)

```bash
cd terraform
terraform apply \
  -var="cloud_provider=aws" \
  -var="github_token=$GITHUB_TOKEN" \
  -var="github_webhook_secret=$WEBHOOK_SECRET" \
  -var="llm_provider=gemini" \
  -var="gemini_api_key=$GEMINI_API_KEY"
```

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v --cov=src

# Run specific test modules
pytest tests/test_webhook.py -v
pytest tests/test_validator.py -v
pytest tests/test_classifier.py -v
pytest tests/test_config.py -v
pytest tests/test_llm_factory.py -v
pytest tests/test_opa_client.py -v
```

## 📝 License

MIT — see [LICENSE](LICENSE)

---

<div align="center">
<sub>Built with 🧠 by NeuroCI — because pipelines shouldn't need babysitting.</sub>
</div>
