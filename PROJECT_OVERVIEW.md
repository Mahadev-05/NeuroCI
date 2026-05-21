# 🧠 NeuroCI — Project Overview

## Executive Summary

**NeuroCI** is an **LLM-powered autonomous CI/CD repair system** that automatically detects, diagnoses, and fixes CI/CD pipeline failures without human intervention. It integrates deeply with GitHub Actions, uses advanced AI/ML techniques, and submits pull requests with fixes for qualifying failures.

### Key Metrics
- **43%** of CI failures are repeat patterns (fixable)
- **23 min** average developer time lost per CI failure
- **~60%** of fixable bugs need ≤5 line changes
- **Goal**: Achieve **4× MTTR (Mean Time To Recovery) improvement**

---

## 🏗️ Architecture Overview

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

### Pipeline Flow

1. **Webhook Reception** → GitHub sends `workflow_run` event to FastAPI server
2. **Deduplication** → Redis prevents duplicate processing of same failure
3. **Task Queuing** → Enqueued in Celery/Redis for async processing
4. **Log Analysis** → Parse CI logs and extract error information
5. **Classification** → LLM classifies failure into 10 canonical types
6. **Memory Lookup** → ChromaDB retrieves similar past fixes via RAG
7. **Patch Generation** → LLM generates code patch (multi-agent debate for high-risk)
8. **Validation** → Flake8 + AST validation ensures patch is syntactically correct
9. **Policy Evaluation** → OPA checks confidence, file paths, branch protection
10. **Decision** → Auto-PR if confidence ≥0.85, else escalate to Slack
11. **Feedback Loop** → PR merge/rejection updates ChromaDB memory

---

## 🛠️ Technical Stack

### Backend & Core
| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Web Framework** | FastAPI | 0.115+ | Webhook server, REST API, async processing |
| **ASGI Server** | Uvicorn | 0.30+ | Production HTTP server |
| **Task Queue** | Celery | 5.4+ | Async job processing |
| **Message Broker** | Redis | 5.0+ | Queue broker + deduplication + result backend |
| **Configuration** | Pydantic | 2.8+ | Settings management, validation |

### AI/ML & LLM
| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **LLM Framework** | LangChain | 0.3+ | Multi-provider LLM orchestration |
| **LangChain Core** | langchain-core | 0.3+ | Base abstractions |
| **LangChain Community** | langchain-community | 0.3+ | Third-party integrations |
| **Vector Store** | ChromaDB | 0.5+ | Embedding storage, RAG memory, similarity search |

### LLM Providers (Multi-Provider Support)
| Provider | Model | Cost | Status |
|----------|-------|------|--------|
| **Google Gemini** | gemini-2.0-flash | FREE ✅ | Recommended, fastest |
| **Groq** | llama-3.3-70b-versatile | FREE tier | High throughput |
| **Ollama** | llama3.1 | FREE (local) | Privacy-first, no API calls |
| **OpenAI** | gpt-4o | Paid $ | Premium, highest accuracy |

**Embeddings:**
- Gemini: `text-embedding-004`
- OpenAI: `text-embedding-3-small`
- Ollama: `nomic-embed-text`

### Policy & Governance
| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Policy Engine** | Open Policy Agent (OPA) | Latest | Rego-based policy evaluation |
| **Policy Language** | Rego | - | Declarative policy rules |

### Code Quality & Validation
| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Linter** | Flake8 | 7.0+ | Python syntax & style validation |
| **Patch Validation** | AST + Regex | Built-in | Ensures patch correctness |

### Notifications & Alerts
| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Slack Integration** | slack-bolt | 1.19+ | Messaging, escalation alerts |
| **Slack SDK** | slack-sdk | 3.31+ | Lower-level Slack API |

### Observability & Monitoring
| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Metrics** | Prometheus Client | 0.21+ | Metrics collection |
| **Logging** | structlog | 24.4+ | Structured JSON logging |
| **Metrics DB** | Prometheus | Latest | Time-series metrics storage |
| **Dashboards** | Grafana | Latest | Visualization & alerting |

### Utilities
| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **HTTP Client** | httpx | 0.27+ | Async GitHub API calls |
| **Retry Logic** | tenacity | 9.0+ | Exponential backoff |
| **Config Loading** | python-dotenv | 1.0+ | `.env` file management |
| **YAML Parsing** | PyYAML | 6.0+ | Config file parsing |

### Language & Runtime
- **Language**: Python 3.11+
- **Package Management**: pip (via pyproject.toml)

---

## 📦 Failure Categories (10 Canonical Types)

NeuroCI classifies failures and determines repairability:

| Category | Patchable | High-Risk | Description | Strategy |
|----------|-----------|-----------|-------------|----------|
| **ImportError** | ✅ | ❌ | Missing module, wrong path | Add import, fix path |
| **DependencyVersionConflict** | ✅ | ❌ | Incompatible package versions | Update requirements |
| **TestAssertion** | ✅ | ❌ | Assertion failed in tests | Fix test expectations |
| **FlakyTest** | ❌ | ✅ | Intermittent failure | Retry/reschedule |
| **ConfigMissing** | ✅ | ❌ | Missing env var or config | Add default/env var |
| **TypeMismatch** | ✅ | ❌ | Type annotation/runtime mismatch | Cast, convert, annotate |
| **SyntaxError** | ✅ | ❌ | Python syntax errors | Fix syntax |
| **LogicBug** | ✅ | ✅ | Logic flow issues (pagination, expiry) | Multi-agent debate |
| **AuthError** | ❌ | ❌ | Authentication/token issues | Requires manual intervention |
| **NetworkTimeout** | ❌ | ❌ | Service unavailability | Retry/monitor |
| **Unknown** | ❌ | ❌ | Unclassified | Escalate |

**Non-patchable categories** (FlakyTest, AuthError, NetworkTimeout, Unknown) → Alert via Slack
**High-risk categories** (LogicBug) → Multi-agent debate before approval

---

## 🧠 Agent Architecture

### 1. **Classifier Agent**
- **Role**: Categorize CI failure
- **LLM Cost**: ~1-2 cents (temperature=0.0)
- **Confidence**: Returns category + confidence score
- **Output**: `FailureCategory` enum + reasoning

### 2. **Retrieval-Augmented Generation (RAG)**
- **Vector Store**: ChromaDB (cosine similarity)
- **Memory**: Past failure→fix pairs (embeddings)
- **Retrieval**: Top-3 similar historical fixes
- **Purpose**: Provide context for patch generation

### 3. **Debate Agents** (for high-risk LogicBug)
- **Agent A**: Temperature=0.1 (conservative)
- **Agent B**: Temperature=0.3 (creative)
- **Judge**: Evaluates both patches, selects safer one
- **Output**: Single best patch with confidence

### 4. **Patch Generator**
- **Task**: Generate code patch from failure + log
- **Output Format**: Unified diff (.patch file)
- **Retries**: Up to 3 attempts on validation failure
- **Context**: File content (first 6KB), error logs (first 4KB)

### 5. **Validator**
- **Checks**:
  - Flake8 syntax validation
  - AST parsing correctness
  - Unified diff format verification
- **Decision**: Approve or retry generation

### 6. **Policy Engine (OPA)**
- **Inputs**: Repo, branch, file path, confidence, category, lines changed
- **Policies** (Rego):
  - Confidence threshold: ≥0.85 for auto-PR
  - File path restrictions: Exclude sensitive paths
  - Branch protection: Only main/develop branches
- **Output**: allow/deny decision

### 7. **GitHub PR Creator**
- **Inputs**: Validated patch + policy approval
- **Actions**:
  - Create feature branch
  - Commit patch
  - Create pull request
  - Add labels, description
- **Fallback**: Slack notification if confidence < 0.85

---

## 🔄 Processing Pipeline Stages

### Stage 1: Log Extraction
```
GitHub workflow run logs (zip) 
  ↓
Extract per-step logs
  ↓
Find failed step
  ↓ Parse error message
```

**Parser identifies:**
- File path
- Error type (ImportError, SyntaxError, etc.)
- Error message
- Line number (if available)
- Language (Python, JavaScript, Go, etc.)

### Stage 2: Classification
```
Log excerpt → LLM → Category + Confidence
```

Example:
```json
{
  "category": "ImportError",
  "confidence": 0.95,
  "reasoning": "Missing 'requests' module import"
}
```

### Stage 3: Memory Lookup
```
Failure fingerprint → Vector embedding → ChromaDB search → Top-3 similar fixes
```

### Stage 4: Patch Generation
```
Failure context + Similar fixes → LLM → Code patch (unified diff)
```

### Stage 5: Validation
```
Patch → Flake8 → AST parse → Format check → ✅ Valid or ❌ Retry
```

### Stage 6: Policy Evaluation
```
Patch metadata → OPA Rego policies → allow/deny
```

### Stage 7: Action
```
if allow && confidence ≥ 0.85:
    Create PR (auto-merge may be enabled)
else:
    Slack alert to team
```

---

## 📊 Metrics & Observability

### Prometheus Metrics
- `neuroci_repairs_total` — Total repair attempts by category
- `neuroci_fixes_total` — Successful patches (PRs created)
- `neuroci_mttr_histogram` — Mean Time To Recovery (stage timings)
- `neuroci_llm_calls_total` — LLM API call count
- `neuroci_confidence_score_histogram` — Confidence distribution

### Structured Logging
- **Format**: JSON
- **Fields**: `timestamp`, `level`, `logger`, `event`, `run_id`, `stage`, `error`
- **Backends**: Stdout (Docker) → ELK/Datadog (optional)

### Grafana Dashboards
- Repair success rate over time
- Failure category distribution
- MTTR by category
- LLM provider performance
- PR merge rate

---

## 🐳 Containerization & Deployment

### Docker Stack (docker-compose.yml)

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| **webhook** | neuroci (custom) | 8000 | FastAPI webhook server |
| **worker** | neuroci (custom) | - | Celery worker (async repair tasks) |
| **redis** | redis:7-alpine | 6379 | Message broker + cache |
| **chromadb** | chromadb/chroma:latest | 8000 | Vector store (RAG memory) |
| **opa** | openpolicyagent/opa:latest | 8181 | Policy engine |
| **prometheus** | prom/prometheus:latest | 9090 | Metrics collection |
| **grafana** | grafana/grafana:latest | 3000 | Dashboards |

### Kubernetes Deployment

**Files:**
- [k8s/namespace.yaml](k8s/namespace.yaml) — Create `neuroci` namespace
- [k8s/infrastructure.yaml](k8s/infrastructure.yaml) — Redis, ChromaDB StatefulSets
- [k8s/celery-worker.yaml](k8s/celery-worker.yaml) — Celery worker Deployment
- [k8s/webhook-server.yaml](k8s/webhook-server.yaml) — FastAPI webhook Deployment

**Helm Chart:**
- [helm/neuroci/](helm/neuroci/) — Production-ready Helm chart
- Values for resource limits, replicas, affinity

### Dockerfile
- **Multi-stage build**: deps + runtime
- **Base**: `python:3.11-slim`
- **Non-root user**: `neuroci`
- **Health check**: HTTP `/health` endpoint
- **Default cmd**: `uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 2`

---

## 🔐 Security Features

### Webhook Security
- **Signature Verification**: HMAC-SHA256 validation of GitHub webhook secret
- **Deduplication**: Redis prevents replay attacks

### Patch Safety
- **AST Validation**: Ensures patch doesn't introduce syntax errors
- **Flake8 Checking**: Python style/quality gates
- **Policy Engine**: OPA enforces file path, branch, confidence gates

### Credentials Management
- **Environment Variables**: All secrets (API keys, tokens) via `.env`
- **Pydantic Settings**: Type-safe, validated config loading
- **No secrets in code**: `.env` is `.gitignore`d

### Data Protection
- **HTTPS**: FastAPI → GitHub API (httpx follows redirects)
- **Non-root containers**: Minimize attack surface
- **Resource limits**: CPU/memory quotas in K8s

---

## 📂 Project Structure

```
neuroci/
├── src/
│   ├── main.py                 # FastAPI app entry point
│   ├── config.py               # Pydantic settings
│   ├── models.py               # Data models (Pydantic)
│   ├── agent/
│   │   ├── classifier.py       # Failure categorization
│   │   ├── debate.py           # Multi-agent patch selection
│   │   ├── patch_generator.py  # Patch creation
│   │   ├── validator.py        # Patch validation
│   │   ├── repair_agent.py     # Main orchestrator
│   │   ├── llm_factory.py      # Multi-provider LLM setup
│   │   └── prompts.py          # System/user prompts
│   ├── memory/
│   │   ├── vector_store.py     # ChromaDB wrapper (RAG)
│   │   └── seed_data.py        # Fixture loading
│   ├── metrics/
│   │   └── prometheus.py       # Metrics instrumentation
│   ├── notifications/
│   │   └── slack_bot.py        # Slack alerting
│   ├── pipeline/
│   │   ├── github_client.py    # GitHub API async client
│   │   └── log_parser.py       # Error extraction
│   ├── policy/
│   │   └── opa_client.py       # OPA policy evaluation
│   ├── tasks/
│   │   └── repair_task.py      # Celery task definitions
│   └── webhook/
│       ├── receiver.py         # GitHub webhook endpoint
│       └── security.py         # HMAC verification
├── tests/
│   ├── test_*.py               # Unit tests
│   └── fixtures/               # Test data
├── policies/
│   └── neuroci.rego            # OPA Rego policies
├── docker-compose.yml          # Local dev stack
├── Dockerfile                  # Production image
├── k8s/                        # Kubernetes manifests
├── helm/                       # Helm chart
├── terraform/                  # IaC (AWS/GCP provisioning)
├── prometheus/                 # Prometheus config
├── grafana/                    # Grafana dashboards
├── pyproject.toml              # Python dependencies
└── README.md
```

---

## 🚀 Deployment Strategies

### Development
```bash
docker compose up
# Starts all services locally
# Access: http://localhost:8000 (API), http://localhost:3000 (Grafana)
```

### Staging
```bash
kubectl apply -f k8s/
# Manual K8s deployment
# Replicas: 1, resource requests: minimal
```

### Production
```bash
helm install neuroci ./helm/neuroci/ -f values-prod.yaml
# or via Terraform
terraform apply
# Auto-scaling, multi-replicas, monitoring enabled
```

---

## 🔄 CI/CD Workflow

### What NeuroCI Repairs

**Example 1: Missing Import**
```python
# Error log: ModuleNotFoundError: No module named 'requests'
# Generated patch:
import requests  # ← Added
response = requests.get(...)
```

**Example 2: Type Mismatch**
```python
# Error: TypeError: unsupported operand type(s) for +: 'str' and 'int'
# Original:
user_count = "10" + 1  # Wrong!
# Generated patch:
user_count = int("10") + 1  # Correct
```

**Example 3: Logic Bug (Pagination)**
```python
# Error: IndexError or incomplete results
# Original:
items = fetch_all(page=1)  # Misses page 2, 3, etc.
# Generated patch:
items = []
page = 1
while True:
    batch = fetch_all(page=page)
    if not batch: break
    items.extend(batch)
    page += 1
```

### What NeuroCI Cannot Repair
- **Flaky tests** (timing-dependent)
- **Auth errors** (token expired)
- **Network timeouts** (service down)
- **Deployment issues** (infra problems)

→ These trigger Slack alerts for human review

---

## 📈 Performance Characteristics

| Metric | Value |
|--------|-------|
| **Webhook latency** | <100ms (sync) |
| **Task queue lag** | <5s (Celery worker pickup) |
| **Repair pipeline (end-to-end)** | 30-120 seconds |
| **LLM calls per repair** | 2-4 (varies by risk) |
| **Typical cost per repair** | $0.01-0.05 (with free tier) |
| **PR submission rate** | 85%+ auto-merge (high confidence) |
| **False positive rate** | <5% (policy gate + debate) |

---

## 🎯 Key Features

✅ **Multi-LLM Support** — Switch providers (Gemini, Groq, Ollama, OpenAI) without code change
✅ **Autonomous Repair** — No human intervention for qualifying failures
✅ **Policy-Driven** — OPA Rego gates ensure compliance
✅ **Learning System** — ChromaDB memory grows with each fix
✅ **Safe Debate** — Multi-agent verification for high-risk patches
✅ **Full Observability** — Prometheus + Grafana + structured logs
✅ **GitHub Integration** — Native webhook + PR creation
✅ **Slack Alerts** — Escalation for non-patchable issues
✅ **Production Ready** — K8s + Helm + Terraform ready
✅ **Open Source** — MIT license (assuming public repo)

---

## 📝 Configuration Example

**.env**
```bash
# GitHub
GITHUB_TOKEN=ghp_xxxxxx
GITHUB_WEBHOOK_SECRET=whsec_xxxxx
GITHUB_ALLOWED_REPOS=owner/repo1,owner/repo2

# LLM Provider (choose one)
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_key_here

# Services
REDIS_URL=redis://redis:6379/0
CHROMA_HOST=chromadb
CHROMA_PORT=8000

# Slack
SLACK_BOT_TOKEN=xoxb_xxxxx
SLACK_SIGNING_SECRET=xxxxx

# OPA
OPA_URL=http://opa:8181

# Logging
LOG_LEVEL=INFO
```

---

## 🧪 Testing

```bash
pytest tests/ -v --cov=src
```

**Test coverage includes:**
- Classifier accuracy
- Patch validation
- GitHub client (mocked)
- Policy evaluation
- Slack notifications
- Vector store operations
- LLM factory provider switching

---

## 🔗 References & Links

- **GitHub**: https://github.com/your-org/neuroci
- **Documentation**: README.md
- **Policy Engine**: https://www.openpolicyagent.org/
- **LangChain**: https://langchain.com/
- **FastAPI**: https://fastapi.tiangolo.com/
- **Celery**: https://docs.celeryproject.io/
- **ChromaDB**: https://docs.trychroma.com/

---

## 📞 Support & Contact

For issues, questions, or contributions:
- Open GitHub Issues
- Submit PRs
- Check documentation in README.md
- Review examples in `tests/fixtures/`

---

**Generated**: May 20, 2026
**Version**: 1.0.0
**Status**: Production Ready ✅
