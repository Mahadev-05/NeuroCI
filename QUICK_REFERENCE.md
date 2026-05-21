# NeuroCI — Quick Reference & Operational Guide

## 🚀 Quick Start (5 minutes)

### Prerequisites
```bash
✓ Python 3.11+
✓ Docker & Docker Compose
✓ Git
✓ 1 API Key (Gemini FREE recommended)
```

### 1. Clone & Setup
```bash
git clone https://github.com/your-org/neuroci.git
cd neuroci
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
```

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env with:
# - GITHUB_TOKEN=ghp_xxxxx
# - GITHUB_WEBHOOK_SECRET=whsec_xxxxx
# - GEMINI_API_KEY=your_api_key_here
# - GITHUB_ALLOWED_REPOS=owner/repo
```

### 3. Run Local Stack
```bash
docker compose up
```

**Services available:**
- API: http://localhost:8000
- Docs: http://localhost:8000/docs
- Grafana: http://localhost:3000 (admin/admin)
- Prometheus: http://localhost:9090
- ChromaDB: http://localhost:8000

### 4. Test Webhook
```bash
curl -X POST http://localhost:8000/api/v1/webhook/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: workflow_run" \
  -H "X-GitHub-Delivery: test-uuid" \
  -H "X-Hub-Signature-256: sha256=xxx" \
  -d @tests/fixtures/webhook_payload.json
```

---

## 📊 Technical Stack (One-Liner Summary)

**NeuroCI** = FastAPI (REST) + Celery (async) + Redis (queue) + ChromaDB (RAG) + LangChain (LLM orchestration) + OPA (policy) + GitHub API (automation) + Prometheus (observability) + Kubernetes (orchestration)

---

## 🔧 Environment Variables Reference

### GitHub
```bash
GITHUB_TOKEN                      # Personal access token (repo scope)
GITHUB_WEBHOOK_SECRET             # HMAC shared secret
GITHUB_ALLOWED_REPOS              # Comma-separated owner/repo list
```

### LLM Provider (Pick ONE)
```bash
# Option 1: Google Gemini (FREE) — RECOMMENDED
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_key
GEMINI_MODEL=gemini-2.0-flash
GEMINI_EMBEDDING_MODEL=models/text-embedding-004

# Option 2: Groq (FREE tier)
LLM_PROVIDER=groq
GROQ_API_KEY=your_key
GROQ_MODEL=llama-3.3-70b-versatile

# Option 3: Ollama (FREE, local)
LLM_PROVIDER=ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1

# Option 4: OpenAI (PAID)
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
```

### Infrastructure
```bash
REDIS_URL=redis://localhost:6379/0
CHROMA_HOST=localhost
CHROMA_PORT=8000
OPA_URL=http://localhost:8181
```

### Slack (Optional)
```bash
SLACK_BOT_TOKEN=xoxb_...
SLACK_SIGNING_SECRET=...
SLACK_CHANNEL=#neuroci-alerts
```

### Logging
```bash
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
```

---

## 📁 Project Structure Explained

| Path | Purpose |
|------|---------|
| `src/main.py` | FastAPI app entry point |
| `src/config.py` | Settings management |
| `src/agent/` | LLM agents (classify, generate, debate) |
| `src/memory/` | ChromaDB vector store (RAG) |
| `src/pipeline/` | GitHub & log processing |
| `src/policy/` | OPA policy evaluation |
| `src/webhook/` | GitHub webhook receiver |
| `src/tasks/` | Celery task definitions |
| `src/notifications/` | Slack alerts |
| `src/metrics/` | Prometheus instrumentation |
| `tests/` | Unit & integration tests |
| `k8s/` | Kubernetes manifests |
| `helm/` | Helm chart (production) |
| `docker-compose.yml` | Local dev environment |
| `policies/neuroci.rego` | OPA policy rules |

---

## 🔄 How NeuroCI Repairs Failures

### Example 1: Import Error
```
Failure Log:
  ModuleNotFoundError: No module named 'requests'

NeuroCI Steps:
  1. Parse → Extract file, error type
  2. Classify → ImportError (confidence: 0.95)
  3. RAG → Find similar past fixes
  4. Generate → "import requests"
  5. Validate → Flake8 ✓
  6. Policy → Allowed (low-risk category)
  7. Action → Create PR

Result: PR auto-merged if confidence ≥ 0.85
```

### Example 2: Type Mismatch
```
Failure Log:
  TypeError: unsupported operand type(s) for +: 'str' and 'int'
  File "main.py", line 45

NeuroCI Steps:
  1. Parse → Extract line, types
  2. Classify → TypeMismatch (confidence: 0.92)
  3. RAG → Find int() cast fixes
  4. Generate → "int(value) + 1"
  5. Validate → AST parse ✓
  6. Policy → Allowed (file not restricted)
  7. Action → Create PR

Result: Merged if confidence ≥ 0.85
```

### Example 3: Logic Bug (Multi-Agent)
```
Failure Log:
  AssertionError: Expected 1500, got 300
  Bug: Pagination only fetches 1 page, missing pages 2-3

NeuroCI Steps:
  1. Parse → Complex logic issue
  2. Classify → LogicBug (confidence: 0.78)
  3. RAG → Find pagination loop patterns
  4. Debate → Agent A (conservative), Agent B (creative)
     Agent A: "Simple manual pagination"
     Agent B: "Full recursive pagination with retry"
     Judge: "Agent A is safer, but confidence only 0.82"
  5. Policy → Denied (LogicBug needs ≥0.90 for auto-PR)
  6. Action → Slack alert to engineer

Result: Human review required
```

---

## 📈 Monitoring & Observability

### Key Metrics to Track
```bash
# Success rate
neuroci_fixes_total / neuroci_repairs_attempted_total

# Speed (MTTR)
neuroci_mttr_seconds (by category)

# Quality (false positives)
100 - (neuroci_pr_merged_total / neuroci_pr_created_total)

# Cost (LLM API spend)
neuroci_llm_calls_total * cost_per_call
```

### Grafana Dashboard Queries
```
# Repairs per day
rate(neuroci_repairs_attempted_total[1d])

# Success rate by category
neuroci_fixes_total / neuroci_repairs_attempted_total

# Confidence distribution
histogram_quantile(0.95, neuroci_confidence_score)

# LLM cost estimate
neuroci_llm_calls_total{provider="gemini"} * 0.00001
```

### Alert Rules (Prometheus)
```yaml
groups:
  - name: neuroci_alerts
    rules:
      - alert: HighFailureRate
        expr: |
          (neuroci_repairs_attempted_total - neuroci_fixes_total) / 
          neuroci_repairs_attempted_total > 0.5
        for: 1h
        annotations:
          summary: "NeuroCI repair success < 50%"

      - alert: WorkerDown
        expr: up{job="neuroci-worker"} == 0
        for: 5m
        annotations:
          summary: "Celery worker offline"
```

---

## 🧪 Testing

### Run All Tests
```bash
pytest tests/ -v --cov=src --cov-report=html
```

### Test Specific Module
```bash
pytest tests/test_classifier.py -v
pytest tests/test_patch_generator.py -v
pytest tests/test_opa_client.py -v
```

### Run with Markers
```bash
pytest tests/ -m "not integration"  # Skip slow tests
pytest tests/ -k "import_error"     # Run specific tests
```

### Coverage Report
```bash
# Generate coverage
pytest tests/ --cov=src --cov-report=term-missing

# Target: >85% coverage
```

---

## 🚢 Kubernetes Deployment

### Install Namespace
```bash
kubectl create namespace neuroci
```

### Deploy Infrastructure (Redis, ChromaDB)
```bash
kubectl apply -f k8s/infrastructure.yaml
kubectl get pods -n neuroci  # Wait for healthy status
```

### Deploy Celery Worker
```bash
kubectl apply -f k8s/celery-worker.yaml
kubectl logs -f -n neuroci deploy/neuroci-worker
```

### Deploy Webhook Server
```bash
kubectl apply -f k8s/webhook-server.yaml
kubectl expose deploy neuroci-webhook -n neuroci \
  --type=LoadBalancer --port=80 --target-port=8000
```

### View Status
```bash
kubectl get all -n neuroci
kubectl describe pod neuroci-webhook-xxx -n neuroci
kubectl logs neuroci-webhook-xxx -n neuroci
```

### Scale Workers
```bash
kubectl scale deploy neuroci-worker -n neuroci --replicas=5
```

---

## 🎯 Helm Deployment (Production)

### Install
```bash
helm install neuroci ./helm/neuroci/ \
  --namespace neuroci \
  --create-namespace \
  --values helm/neuroci/values-prod.yaml
```

### Upgrade
```bash
helm upgrade neuroci ./helm/neuroci/ \
  --namespace neuroci \
  --values helm/neuroci/values-prod.yaml
```

### Rollback
```bash
helm rollback neuroci 1 -n neuroci
```

### Values Override
```bash
helm install neuroci ./helm/neuroci/ \
  --set webhook.replicas=3 \
  --set worker.replicas=5 \
  --set resources.requests.memory=512Mi
```

---

## 🔍 Debugging Commands

### Check Webhook Signature
```bash
python -c "
import hmac
import hashlib
payload = open('webhook_payload.json').read()
secret = 'my_webhook_secret'
sig = 'sha256=' + hmac.new(
    secret.encode(),
    payload.encode(),
    hashlib.sha256
).hexdigest()
print(sig)
"
```

### Test LLM Connection
```bash
python -c "
from src.agent.llm_factory import get_chat_llm
from langchain_core.messages import HumanMessage
llm = get_chat_llm()
result = llm.invoke([HumanMessage(content='Hello')])
print(result.content)
"
```

### Query ChromaDB
```bash
python -c "
import chromadb
client = chromadb.HttpClient(host='localhost', port=8000)
collection = client.get_collection('neuroci_fixes')
print(f'Total documents: {collection.count()}')
results = collection.query(query_texts=['import error'], n_results=3)
print(results)
"
```

### Check Redis Status
```bash
redis-cli INFO
redis-cli KEYS "*"
redis-cli GET neuroci:dedup:xxxxx
```

### OPA Policy Testing
```bash
opa run
# Type: data.neuroci.allow with sample input
```

---

## 📋 Failure Categories Decision Tree

```
Is the failure patchable?
│
├─ NO (Non-patchable):
│   ├─ FlakyTest → Retry configuration
│   ├─ AuthError → Credential renewal
│   ├─ NetworkTimeout → Infrastructure check
│   └─ Unknown → Human review
│   
└─ YES (Patchable):
    ├─ ImportError → Add import / fix path
    ├─ DependencyVersionConflict → Update requirements
    ├─ TestAssertion → Fix assertion or implementation
    ├─ ConfigMissing → Add env var / config file
    ├─ TypeMismatch → Cast or convert types
    ├─ SyntaxError → Fix Python syntax
    └─ LogicBug → Multi-agent debate (higher confidence required)
```

---

## 🔐 Security Checklist

- [ ] HMAC signature verification enabled
- [ ] GitHub token stored in `.env` (not in code)
- [ ] All secrets rotated quarterly
- [ ] OPA policies reviewed and tested
- [ ] Patch validation (AST + Flake8) enforced
- [ ] Restricted file paths configured
- [ ] Container runs as non-root user
- [ ] HTTPS enforced in production
- [ ] Resource limits set in K8s
- [ ] Network policies restrict traffic
- [ ] Audit logging enabled

---

## 💡 Best Practices

### Do's ✅
- Use Gemini API (free, fast, reliable)
- Configure `GITHUB_ALLOWED_REPOS` (security)
- Set confidence threshold ≥0.85
- Monitor MTTR metrics weekly
- Audit merged PRs monthly
- Test locally before deploying
- Use Helm for production deployments
- Keep dependencies updated

### Don'ts ❌
- Don't commit secrets to git
- Don't run as root in containers
- Don't skip policy evaluation
- Don't lower confidence threshold below 0.75
- Don't ignore failed Celery tasks
- Don't deploy untested patches
- Don't modify OPA policies without review
- Don't mix API keys for different providers

---

## 🆘 Common Issues & Fixes

| Issue | Cause | Solution |
|-------|-------|----------|
| **Webhook 403 Unauthorized** | Bad HMAC signature | Verify webhook secret matches |
| **Celery task stuck** | Worker offline | `docker restart neuroci-worker` |
| **No patches generated** | LLM rate limit | Wait 1hr, use different provider |
| **ChromaDB connection error** | Service down | `docker compose restart chromadb` |
| **OPA policy rejection** | Confidence too low | Lower threshold or improve logs |
| **PR not created** | GitHub API failure | Check token, rate limits |
| **Slack notifications silent** | Wrong channel/token | Verify bot token and channel name |
| **Memory usage high** | ChromaDB growth | Clean old entries, increase storage |

---

## 📞 Support Resources

- **GitHub Issues**: https://github.com/your-org/neuroci/issues
- **Documentation**: README.md + PROJECT_OVERVIEW.md
- **Architecture**: ARCHITECTURE_DEEP_DIVE.md (this file)
- **Examples**: tests/fixtures/
- **Community**: Slack #neuroci-dev

---

## 🎓 Learning Path

1. **Start**: Read PROJECT_OVERVIEW.md (30 min)
2. **Architecture**: Study ARCHITECTURE_DEEP_DIVE.md (1 hour)
3. **Code**: Review src/agent/repair_agent.py (1 hour)
4. **Deploy**: Run docker compose locally (30 min)
5. **Test**: Run pytest tests/ (30 min)
6. **Monitor**: Access Grafana dashboards (30 min)
7. **Advanced**: Deploy to K8s (2 hours)

---

## 📊 Quick Facts

| Metric | Value |
|--------|-------|
| Lines of Code | ~3,500 |
| Test Coverage | >85% |
| Agent Stages | 5 (classify, retrieve, generate, validate, policy) |
| LLM Providers | 4 (Gemini, Groq, Ollama, OpenAI) |
| Failure Categories | 10 + Unknown |
| Patchable Categories | 7/10 |
| Docker Services | 7 (webhook, worker, redis, chromadb, opa, prometheus, grafana) |
| K8s Resources | 10+ (Deployments, StatefulSets, Services, ConfigMaps) |
| Helm Templates | 15+ |
| Terraform Modules | 5+ |
| Max Repair Time | ~2 minutes (end-to-end) |
| Cost per Repair (Gemini) | ~$0.001-0.005 |
| Success Rate Target | >85% |

---

## 🌐 External Links

- [LangChain Docs](https://langchain.com/)
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [Celery Docs](https://docs.celeryproject.org/)
- [ChromaDB Docs](https://docs.trychroma.com/)
- [OPA Docs](https://www.openpolicyagent.org/)
- [Kubernetes Docs](https://kubernetes.io/docs/)
- [Helm Docs](https://helm.sh/docs/)
- [Prometheus Docs](https://prometheus.io/docs/)
- [Grafana Docs](https://grafana.com/docs/)

---

**Quick Reference Version**: 1.0.0
**Last Updated**: May 20, 2026
**Status**: Production Ready ✅
