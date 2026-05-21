# NeuroCI — Technical Architecture Deep Dive

## System Architecture Layers

### Layer 1: Event Ingestion (GitHub Webhook)
```
GitHub Actions (CI/CD Pipeline)
    ↓ workflow_run event (JSON payload)
    ↓
FastAPI Webhook Receiver (/webhook/github)
    ↓ HMAC-SHA256 signature verification
    ↓ Redis deduplication (event_id hash)
    ↓
Redis Queue (Celery broker)
```

**Security:**
- Signature verification prevents unauthorized requests
- Deduplication prevents processing same failure twice
- HTTP endpoint uses HTTPS in production

---

### Layer 2: Async Task Processing (Celery)
```
Celery Worker Pool (configurable concurrency)
    ├─ Task: run_repair_pipeline
    ├─ Task: send_slack_notification
    └─ Task: update_memory (post-merge feedback)

Redis
    ├─ Task queue (pending repairs)
    ├─ Result backend (completion status)
    └─ Dedup cache (24h TTL)
```

**Key Points:**
- Non-blocking: Webhook returns 202 Accepted immediately
- Scalable: Multiple workers can run in parallel
- Reliable: Task retry on failure
- Monitoring: Task status tracked in Redis

---

### Layer 3: Agent Brain (LLM Orchestration)
```
┌─────────────────────────────────────────────┐
│          Repair Agent Orchestrator          │
│         (repair_agent.py - main loop)       │
└──────────────────┬──────────────────────────┘
                   │
        ┌──────────┼──────────┐
        │          │          │
        ▼          ▼          ▼
   ┌────────┐ ┌────────┐ ┌─────────┐
   │Classify│ │  RAG   │ │ Generate│
   │Failure │ │ Memory │ │ Patch   │
   └────────┘ └────────┘ └─────────┘
        │          │          │
        ▼          ▼          ▼
   ┌─────────────────────────────┐
   │     LangChain LLM Router     │
   └──────────────┬──────────────┘
                  │
        ┌─────────┼─────────┐
        │         │         │
    Gemini      Groq      Ollama      OpenAI
   (FREE)     (FREE)     (Local)     (Paid)
```

**Agent Responsibilities:**

1. **Classifier**: Fast, deterministic categorization
2. **Retriever**: ChromaDB similarity search
3. **Generator**: Patch creation (single or multi-agent debate)
4. **Validator**: Syntax & format checking

---

### Layer 4: Memory System (Vector Store)
```
ChromaDB Vector Database
    ├─ Collection: neuroci_fixes
    ├─ Embedding model: text-embedding-004 (Gemini)
    │
    ├─ Document schema:
    │  {
    │    "id": "sha256_hash",
    │    "failure_log": "...",
    │    "category": "ImportError",
    │    "patch": "unified diff",
    │    "confidence": 0.92,
    │    "pr_merged": true,
    │    "timestamp": "2024-05-20T10:30:00Z"
    │  }
    │
    └─ Retrieval: cosine similarity (top-3)
```

**Learning Loop:**
- New failure → Generate patch → Deploy (test in staging)
- Patch merged → Add to ChromaDB with metadata
- Future similar failures → Retrieved as context
- Confidence increases over time

---

### Layer 5: Policy Engine (OPA)
```
OPA Runtime (Open Policy Agent)
    ├─ Policy file: policies/neuroci.rego
    │
    ├─ Evaluation request:
    │  {
    │    "repo": "owner/repo",
    │    "branch": "main",
    │    "target_file": "src/main.py",
    │    "confidence": 0.87,
    │    "category": "ImportError",
    │    "lines_changed": 3
    │  }
    │
    └─ Decision: allow | deny (with reasoning)
```

**Policy Rules (Rego):**
```rego
# Confidence threshold
confidence_ok {
    input.confidence >= 0.85
}

# Safe file paths
safe_file {
    not contains_sensitive_path(input.target_file)
}

# Protected branches
protected_branch {
    input.branch in ["main", "develop", "staging"]
}

# High-risk categories require higher confidence
high_risk_ok {
    input.category == "LogicBug"
    input.confidence >= 0.90
}

# Final decision
allow {
    confidence_ok
    safe_file
    protected_branch
    [input.category == "LogicBug", high_risk_ok][count(input.category)]
}
```

---

### Layer 6: Action & Feedback
```
┌─────────────────┐
│ Policy Decision │
└────────┬────────┘
         │
    ┌────┴─────┐
    │           │
    ▼           ▼
┌────────┐ ┌───────────┐
│ Denied │ │  Allowed  │
└────────┘ └─────┬─────┘
               │
         ┌─────┴────────┐
         │              │
      Confidence      Confidence
       < 0.85         ≥ 0.85
         │              │
         ▼              ▼
    ┌────────┐    ┌──────────┐
    │  Slack │    │  Create  │
    │ Alert  │    │    PR    │
    └────────┘    └──────────┘
         │              │
         └──────┬───────┘
                ▼
         ┌────────────────┐
         │ PR Lifecycle   │
         ├─ Merged → ✅   │
         ├─ Rejected → ⚠️ │
         └─ Update Memory│
```

---

## Data Flow Sequence Diagram

```
┌──────────┐
│ Developer│
└────┬─────┘
     │ git push
     ▼
┌─────────────┐
│   GitHub    │ workflow_run event
└────┬────────┘
     │ HTTPS webhook
     ▼
┌───────────────────────────┐
│ FastAPI /webhook/github   │
│ 1. Verify HMAC signature  │
│ 2. Check dedup cache      │
│ 3. Extract payload        │
└────┬─────────────────────┘
     │ enqueue task
     ▼
┌──────────────┐
│   Redis      │ task: run_repair_pipeline
└────┬─────────┘
     │ async worker pickup
     ▼
┌───────────────────────────────────────┐
│ Celery Worker                         │
│ run_repair_pipeline()                 │
└────┬──────────────────────────────────┘
     │
     ├─ 1. Download logs (GitHub API)
     │    └─ Extract error → ParsedError
     │
     ├─ 2. Classify (LLM)
     │    ├─ Send to Gemini/Groq/Ollama/OpenAI
     │    └─ Get category + confidence
     │
     ├─ 3. Check patchability
     │    └─ If non-patchable → Slack alert
     │
     ├─ 4. Retrieve memory (ChromaDB)
     │    ├─ Embed failure log
     │    ├─ Similarity search
     │    └─ Get top-3 similar fixes
     │
     ├─ 5. Generate patch (LLM)
     │    ├─ If LogicBug → Multi-agent debate
     │    └─ Else → Single generation
     │
     ├─ 6. Validate patch
     │    ├─ Flake8 check
     │    ├─ AST parse
     │    └─ Unified diff format
     │
     ├─ 7. Evaluate policy (OPA)
     │    ├─ Confidence threshold
     │    ├─ File path restrictions
     │    └─ Branch protection
     │
     └─ 8. Decision & Action
         ├─ If approved & confidence ≥ 0.85
         │  ├─ Create branch (GitHub API)
         │  ├─ Commit patch (GitHub API)
         │  ├─ Open PR (GitHub API)
         │  └─ Add labels, description
         │
         └─ Else
            ├─ Create Slack notification
            ├─ DM engineer with details
            └─ Store in dedup cache
```

---

## Component Interaction Matrix

| From → To | Method | Protocol | Auth | Frequency |
|-----------|--------|----------|------|-----------|
| GitHub → Webhook | Event | HTTPS | HMAC | Per failure |
| Webhook → Redis | Queue | TCP | None | Sync |
| Celery → LLM API | HTTP | HTTPS | API Key | Per repair |
| Celery → ChromaDB | gRPC/HTTP | TCP | None | Per repair |
| Celery → OPA | HTTP/REST | HTTP | None | Per patch |
| Celery → GitHub API | REST | HTTPS | OAuth | Per PR |
| Celery → Slack API | REST | HTTPS | Token | Per alert |
| Prometheus → Metrics | Scrape | HTTP | None | Every 15s |

---

## Failure Handling & Resilience

### Retry Strategy
```python
@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=1, min=2, max=10),
    stop=tenacity.stop_after_attempt(3),
    reraise=True
)
def operation_with_retry():
    # LLM calls, API calls retry on transient errors
    pass
```

### Circuit Breaker (OPA)
```
If OPA unavailable:
    ├─ Attempt 1: Try OPA
    ├─ Attempt 2: Fall back to local policy
    └─ Attempt 3: Conservative default (deny)
```

### Dead Letter Queue
```
Celery task fails after retries:
    ├─ Logged to stdout (JSON)
    ├─ Slack alert to #neuroci-alerts
    └─ Manual review required
```

---

## Performance Optimization Strategies

### 1. Caching
```
Redis caching:
├─ Event dedup (24h TTL)
├─ LLM responses (6h TTL)
└─ Policy decisions (1h TTL)
```

### 2. Batch Processing
```
Celery:
├─ Single worker concurrency: 2-4
├─ Worker pool: Prefork, eventlet, or gevent
└─ Task prioritization: High-risk bugs first
```

### 3. Lazy Loading
```
Dependencies loaded on-demand:
├─ LLM clients: Initialized per request
├─ Vector store: Connection pooled
└─ GitHub client: Reused across tasks
```

### 4. Metrics Instrumentation
```
Prometheus histograms track latency:
├─ Webhook ingestion: <100ms
├─ Log parsing: <1s
├─ Classification: 2-5s
├─ RAG retrieval: <1s
├─ Patch generation: 10-30s
├─ Validation: <1s
├─ Policy evaluation: <500ms
└─ PR creation: 1-3s
```

---

## Observability Stack

### Logs
```
structlog JSON format:
{
  "timestamp": "2024-05-20T10:30:45.123Z",
  "level": "INFO",
  "logger": "repair_agent",
  "event": "patch_generated",
  "run_id": "workflow_run_123456",
  "stage": "patch_generator",
  "patch_lines": 5,
  "confidence": 0.92,
  "category": "ImportError"
}
```

### Metrics
```
Prometheus time-series:
- neuroci_repairs_attempted_total{category="ImportError"} 156
- neuroci_fixes_total{category="ImportError"} 142
- neuroci_mttr_seconds_bucket{category="ImportError", le="30"} 89
- neuroci_llm_calls_total{provider="gemini", operation="classify"} 298
- neuroci_confidence_score_bucket{le="0.85"} 23
```

### Distributed Tracing (Future)
```
Jaeger integration (optional):
├─ Trace ID passed through pipeline
├─ Span per agent stage
└─ Latency attribution per service
```

---

## Multi-LLM Provider Architecture

### Dynamic Provider Selection
```python
# config.py
llm_provider: Literal["gemini", "groq", "ollama", "openai"] = "gemini"

# llm_factory.py
def get_chat_llm(temperature: float, max_tokens: int):
    settings = get_settings()
    
    if settings.llm_provider == "gemini":
        return ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            temperature=temperature,
            max_tokens=max_tokens
        )
    elif settings.llm_provider == "groq":
        return ChatGroq(
            model=settings.groq_model,
            temperature=temperature,
            max_tokens=max_tokens
        )
    # ... etc
```

### Cost Comparison
| Provider | Model | Input | Output | Status |
|----------|-------|-------|--------|--------|
| Gemini | gemini-2.0-flash | FREE | FREE | ✅ Recommended |
| Groq | llama-3.3-70b | FREE tier | FREE tier | ✅ Good |
| Ollama | llama3.1 | FREE | FREE | ✅ Local, no API |
| OpenAI | gpt-4o | $5/M tokens | $15/M tokens | $ Paid |

---

## Security Architecture

### Threat Model

| Threat | Mitigation |
|--------|-----------|
| **Webhook spoofing** | HMAC-SHA256 signature verification |
| **Replay attacks** | Redis event dedup (24h TTL) |
| **Unauthorized PR creation** | Policy engine + confidence gate |
| **Malicious patches** | AST validation + Flake8 |
| **Credential leakage** | .env + pydantic-settings (no logging secrets) |
| **SQL injection** | ChromaDB not exposed publicly |
| **LLM prompt injection** | Input sanitization (error logs truncated) |
| **Supply chain** | Pinned dependencies (pyproject.toml) |

### Credential Rotation
```
GitHub token → Personal access token (PAT) with repo scope
Slack token → Bot OAuth token with chat:write scope
API keys → Rotated quarterly
```

---

## Scalability Analysis

### Bottlenecks & Solutions

| Bottleneck | Current | Solution |
|-----------|---------|----------|
| **Celery workers** | 1 | Horizontal scaling: 2-10 workers |
| **Redis** | Single instance | Cluster (6+ nodes) |
| **ChromaDB** | Single replica | Distributed setup + replication |
| **OPA** | Single instance | Multiple replicas behind load balancer |
| **LLM API rate limits** | ~100 req/min | Queue management + provider diversity |

### Capacity Planning
```
Assumptions:
- 1,000 repos monitored
- 10 failures/day per repo
- → 10,000 repairs/day = ~6/minute

Hardware:
- Webhook: 1 FastAPI instance (m5.large)
- Workers: 4 Celery workers (2x t3.xlarge)
- Redis: 1 instance (r6g.xlarge)
- ChromaDB: 1 instance (c6i.2xlarge)
- OPA: 1 instance (t3.large)
```

---

## Testing Strategy

### Unit Tests
```python
# test_classifier.py
async def test_import_error_classification():
    state = AgentState(
        parsed_error=ParsedError(
            file_path="main.py",
            error_type="ModuleNotFoundError",
            error_message="No module named 'requests'",
            language="python"
        )
    )
    result = await classify_failure(state)
    assert result.category == FailureCategory.IMPORT_ERROR
    assert result.category_confidence > 0.9
```

### Integration Tests
```python
# test_integration.py
@pytest.mark.asyncio
async def test_full_repair_pipeline():
    # 1. Create webhook payload
    # 2. Post to /webhook/github
    # 3. Assert Celery task enqueued
    # 4. Run worker
    # 5. Verify PR created
```

### Fixture Data
```
tests/fixtures/
├── metadata.json (workflow run metadata)
├── sample_logs/ (CI failure logs)
└── expected_patches/ (ground truth diffs)
```

---

## Deployment Checklist

### Pre-Production
- [ ] Configure all environment variables (.env)
- [ ] Set GitHub webhook secret
- [ ] Configure LLM provider API key
- [ ] Set Slack bot token
- [ ] Create GitHub PAT with repo scope
- [ ] Test OPA policies locally
- [ ] Load seed data into ChromaDB
- [ ] Run test suite (pytest)
- [ ] Security scan (bandit)
- [ ] Dependency audit (safety)

### Kubernetes
- [ ] Create namespace: `kubectl create namespace neuroci`
- [ ] Deploy infrastructure: `kubectl apply -f k8s/infrastructure.yaml`
- [ ] Deploy worker: `kubectl apply -f k8s/celery-worker.yaml`
- [ ] Deploy webhook: `kubectl apply -f k8s/webhook-server.yaml`
- [ ] Verify health: `kubectl get pods -n neuroci`
- [ ] Check logs: `kubectl logs -f -n neuroci deploy/neuroci-webhook`

### Helm
```bash
helm install neuroci ./helm/neuroci/ \
  --namespace neuroci \
  --values values-prod.yaml \
  --set gemini_api_key=$GEMINI_KEY \
  --set github_token=$GH_TOKEN
```

### Monitoring
- [ ] Access Grafana: http://prometheus:3000
- [ ] Create dashboards
- [ ] Set up Slack alerts
- [ ] Test PagerDuty integration
- [ ] Verify log aggregation

---

## Roadmap & Future Enhancements

### v1.1
- [ ] Multi-language support (JS, Go, Rust patches)
- [ ] Custom model fine-tuning on past fixes
- [ ] A/B testing LLM providers

### v1.2
- [ ] Advanced RAG: Semantic code search
- [ ] Auto-scaling Celery workers
- [ ] Distributed tracing (Jaeger)

### v2.0
- [ ] IDE plugin (VS Code extension)
- [ ] Webhook replay dashboard
- [ ] Feedback loop analytics
- [ ] Cost dashboard (per-provider breakdown)

---

## Troubleshooting Guide

### Webhook Not Triggering
```
1. Check GitHub webhook delivery logs
2. Verify HMAC secret matches settings
3. Check FastAPI logs: kubectl logs -f deploy/neuroci-webhook
4. Test locally: curl -X POST http://localhost:8000/api/v1/webhook/github ...
```

### Patches Not Generated
```
1. Check Celery worker running: docker ps | grep worker
2. Check Redis connectivity: redis-cli ping
3. View worker logs: celery -A src.tasks.repair_task worker -l debug
4. Check LLM API key: echo $GEMINI_API_KEY
```

### OPA Policy Rejections
```
1. Review policies: cat policies/neuroci.rego
2. Test locally: opa run -s policies/
3. View policy reasons: kubectl logs -f deploy/opa
4. Adjust thresholds in .rego file
```

### Memory Issues
```
1. Monitor ChromaDB size: SELECT COUNT(*) FROM collections
2. Clear old entries: DELETE FROM neuroci_fixes WHERE timestamp < '2024-01-01'
3. Rebuild indexes: REINDEX neuroci_fixes
4. Scale up storage if needed
```

---

**Document Version**: 1.0.0
**Last Updated**: May 20, 2026
**Status**: Production Ready ✅
