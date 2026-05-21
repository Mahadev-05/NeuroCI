
# NeuroCI

NeuroCI is an LLM-driven "self-healing" CI/CD system that detects failing GitHub Actions runs, diagnoses the root cause, generates minimal code patches, validates them, and creates pull requests automatically when safe.

This repository contains the full NeuroCI application, deployment manifests, policies, and test fixtures.

Key capabilities:
- Automated classification of CI failures
- Retrieval-augmented generation (RAG) of past fixes
- Multi-LLM support (Gemini, Groq, Ollama, OpenAI)
- Policy gating with OPA (Rego)
- Safe validation (Flake8 + AST)
- Observability (Prometheus + Grafana)

See `PROJECT_OVERVIEW.md`, `ARCHITECTURE_DEEP_DIVE.md`, and `QUICK_REFERENCE.md` for detailed documentation.

---

## Quick Start

Prerequisites:

- Python 3.11+
- Docker & Docker Compose
- Git

Local development steps:

```bash
git clone <your-repo-url>
cd DevSecOps
cp .env.example .env
# Edit .env to set at least GITHUB_WEBHOOK_SECRET and GITHUB_TOKEN (for demo you can use placeholders)
docker compose up -d
```

Open the API docs at: http://localhost:8000/docs

Run the demo runner (PowerShell):

```powershell
.\'run_demo.ps1'
```

Or send a signed webhook locally using the helper script:

```bash
python scripts/send_signed_webhook.py --payload tests/fixtures/sample_logs/sample_workflow_run.json
```

For a real GitHub Actions failure, point the helper at your repo and run:

```bash
python scripts/send_signed_webhook.py --repo owner/repo --run-id 12345
```

### Local GitHub webhook setup
1. Copy `.env.example` and set `GITHUB_WEBHOOK_SECRET` to a strong value.
2. Add the same secret to your GitHub webhook settings.
3. Start the stack:
   ```powershell
   docker compose up -d
   ```
4. Start ngrok from the repo root:
   ```powershell
   .\ngrok.exe config add-authtoken <your-token>
   .\ngrok.exe http 8000
   ```
5. Use the generated ngrok URL as the webhook endpoint:
   `https://<your-subdomain>.ngrok-free.app/api/v1/webhook/github`
6. Select events: **workflow_run**, **pull_request**, **push**, and optionally **ping**.

If GitHub delivers `403 Forbidden`, verify the secret in GitHub matches `GITHUB_WEBHOOK_SECRET` in `.env`.

If external LLM APIs are unavailable, the demo uses recorded fixtures under `tests/fixtures/expected_patches/`.

---

## What it does (short)

- Receives GitHub `workflow_run` failure webhooks
- Downloads and parses workflow logs
- Classifies failure into one of 10 canonical categories using an LLM
- Retrieves similar past fixes from ChromaDB (RAG)
- Generates a minimal unified-diff patch via LLM (single or multi-agent debate)
- Validates patch with Flake8 and AST parsing
- Evaluates policy using OPA (confidence threshold, restricted paths)
- Creates a PR via GitHub API if allowed and confident; otherwise notifies via Slack

---

## Architecture (high level)

See `VISUAL_OVERVIEW.md` and `ARCHITECTURE_DEEP_DIVE.md` for diagrams and a full breakdown. High-level components:

- FastAPI webhook receiver (`src/webhook`) — verifies HMAC signature and enqueues tasks
- Celery workers + Redis (`docker-compose` + `k8s` manifests) — asynchronous repair tasks
- LangChain LLM orchestration (`src/agent`) — classifier, generator, debate agents
- ChromaDB vector store (`src/memory/vector_store.py`) — RAG memory of past fixes
- OPA policy client (`src/policy/opa_client.py`) — Rego-based gates
- GitHub client (`src/pipeline/github_client.py`) — download logs + create PRs

---

## Running the Demo

1. Ensure `.env` contains `GITHUB_WEBHOOK_SECRET`.
2. Start services:

```powershell
docker compose up -d
```

3. Run the demo runner (PowerShell):

```powershell
.\run_demo.ps1
```

This script waits for the webhook `/health` endpoint, posts a signed webhook using `scripts/send_signed_webhook.py`, and prints recent worker logs. For a manual POST, use the Python helper above.

---

## CI Failure Monitoring

NeuroCI now includes a minimal CI failure analysis flow for GitHub Actions `workflow_run` webhooks. This feature is intentionally production-safe: it detects failed runs, extracts useful metadata, generates human-readable analysis, and stores remediation suggestions. It does **not** create code patches, push commits, or open automated pull requests.

### What gets detected

The webhook receiver handles this path:

```text
GitHub Action fails
  -> GitHub sends workflow_run webhook
  -> NeuroCI verifies HMAC SHA256 signature
  -> workflow_run action is completed
  -> conclusion is failure
  -> failure analysis is generated
  -> result is logged and stored
```

For each failed workflow run, NeuroCI extracts workflow name, failed job when present, branch, commit SHA, repository name, conclusion, run URL, and logs URL when available.

Recent analyses are available at:

```text
GET /api/v1/ci/failures
```

Example response:

```json
{
  "count": 1,
  "failures": [
    {
      "run_id": 12345,
      "repository": "owner/repo",
      "workflow_name": "pytest",
      "failed_job": "unit tests",
      "branch": "main",
      "commit_sha": "abc123def456",
      "conclusion": "failure",
      "run_url": "https://github.com/owner/repo/actions/runs/12345",
      "logs_url": "https://api.github.com/repos/owner/repo/actions/runs/12345/logs",
      "failure_type": "pytest failed",
      "summary": "pytest failed on branch main for owner/repo. Likely category: pytest failed. Failed job: unit tests.",
      "remediation_suggestions": [
        "Run pytest locally and inspect the failing assertion.",
        "Check whether recent code changes altered expected behavior.",
        "Review test fixtures and environment-specific assumptions."
      ],
      "created_at": "2026-05-21T10:00:00Z"
    }
  ]
}
```

### Sample workflow_run failure payload

```json
{
  "action": "completed",
  "workflow_run": {
    "id": 12345,
    "name": "pytest",
    "head_branch": "main",
    "head_sha": "abc123def456",
    "conclusion": "failure",
    "html_url": "https://github.com/owner/repo/actions/runs/12345",
    "logs_url": "https://api.github.com/repos/owner/repo/actions/runs/12345/logs",
    "jobs": [
      {
        "name": "unit tests",
        "conclusion": "failure"
      }
    ]
  },
  "repository": {
    "id": 1,
    "full_name": "owner/repo",
    "html_url": "https://github.com/owner/repo",
    "default_branch": "main"
  }
}
```

GitHub's real `workflow_run` webhook usually provides a `logs_url` or `jobs_url`, not full job logs. This implementation avoids extra enterprise complexity and analyzes the fields available in the webhook payload.

### Expected terminal output

When a failed workflow webhook is received, the webhook logs should include:

```text
webhook.security.verified github_event=workflow_run verification_status=passed
webhook.received github_event=workflow_run verification_status=passed
ci.failure_analysis.generated run_id=12345 repo=owner/repo workflow=pytest failed_job="unit tests" failure_type="pytest failed"
ci.failure_analysis.stored run_id=12345 repo=owner/repo workflow=pytest failure_type="pytest failed"
```

The webhook response should look like:

```json
{
  "accepted": true,
  "message": "CI failure analyzed: pytest failed",
  "run_id": 12345
}
```

### Demo steps

1. Start the local stack:

```powershell
.\scripts\start-local.ps1
```

2. Configure the GitHub webhook URL:

```text
https://<ngrok-id>.ngrok-free.app/api/v1/webhook/github
```

3. Enable `workflow_run` events in GitHub webhook settings.
4. Trigger a GitHub Actions failure, for example by pushing a branch with a deliberately failing test.
5. Confirm GitHub webhook delivery returns HTTP `202`.
6. Watch the FastAPI logs for `ci.failure_analysis.generated`.
7. Query the stored analysis:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/ci/failures
```

Expected result:

```text
count failures
----- --------
    1 {@{run_id=12345; repository=owner/repo; workflow_name=pytest; failure_type=pytest failed; ...}}
```

### Current limitations

- The analyzer uses simple explainable heuristics, not a live LLM call.
- It only analyzes metadata available in the webhook payload.
- It does not download or parse full GitHub Actions logs.
- It does not modify code, create branches, push commits, or open pull requests.
- Failed job detection is best effort because GitHub often sends a jobs URL rather than full job details in the webhook.

---

## Safe Automated Remediation PRs

NeuroCI can optionally turn a supported CI failure analysis into a small remediation pull request. This is disabled by default and dry-run mode is enabled by default for safety.

Enable it in `.env`:

```env
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GITHUB_REMEDIATION_ENABLED=true
GITHUB_REMEDIATION_DRY_RUN=true
```

To actually create branches and PRs, set:

```env
GITHUB_REMEDIATION_DRY_RUN=false
```

Recommended token permissions for a demo repository:

- Contents: read/write
- Pull requests: read/write
- Metadata: read

### Remediation flow

```text
GitHub Action fails
  -> NeuroCI receives workflow_run webhook
  -> HMAC SHA256 verification passes
  -> failure is analyzed
  -> supported remediation type is selected
  -> deterministic patch is generated
  -> branch neuroci/autofix-<run_id>-... is created
  -> commit is pushed
  -> pull request is opened
```

PR title format:

```text
[NeuroCI AutoFix] Fix CI failure: <failure_type>
```

The PR body includes the detected failure, generated remediation, an AI-generated warning, and a manual review recommendation.

### Supported remediation types

NeuroCI only attempts deterministic fixes for simple cases:

- missing dependency
- requirements.txt mismatch
- import error with a clear missing package name
- formatting issue
- lint failure
- basic GitHub Actions YAML issue
- simple pytest config issue

Unsupported or ambiguous failures are skipped and logged as `ci.remediation.skipped`.

### Safety controls

- Remediation is opt-in with `GITHUB_REMEDIATION_ENABLED=true`.
- Dry-run mode is on by default.
- One remediation attempt is stored per workflow run id.
- Branches use deterministic `neuroci/autofix-...` names.
- NeuroCI skips failures from its own autofix branches to avoid loops.
- Only known safe files are touched by deterministic rules.
- Advanced code rewrites, auto-merges, and broad source edits are intentionally not implemented.

### Remediation history endpoint

```text
GET /api/v1/ci/remediations
```

Example dry-run response:

```json
{
  "count": 1,
  "remediations": [
    {
      "run_id": 12345,
      "repository": "owner/repo",
      "failure_type": "dependency missing",
      "status": "dry_run",
      "branch_name": "neuroci/autofix-12345-repo-dependency-missing",
      "pr_url": "",
      "dry_run": true,
      "reason": "dry_run_enabled",
      "remediation_summary": "Add missing dependency `requests` to requirements.txt.",
      "files_changed": ["requirements.txt"]
    }
  ]
}
```

### Demo flow

1. Start the local stack:

```powershell
.\scripts\start-local.ps1
```

2. Enable remediation dry-run:

```env
GITHUB_REMEDIATION_ENABLED=true
GITHUB_REMEDIATION_DRY_RUN=true
```

3. Trigger a simple dependency failure in GitHub Actions, such as a missing import where the log/title clearly includes `No module named 'requests'`.

4. Confirm the webhook response:

```json
{
  "accepted": true,
  "message": "CI failure analyzed: dependency missing; remediation dry_run",
  "run_id": 12345
}
```

5. Check remediation history:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/ci/remediations
```

6. For a real PR demo, set `GITHUB_REMEDIATION_DRY_RUN=false`, restart the webhook service, trigger the same supported failure, and verify GitHub shows a PR with title:

```text
[NeuroCI AutoFix] Fix CI failure: dependency missing
```

### Limitations

- This is a learning/demo self-healing system, not an unrestricted coding agent.
- It does not inspect full logs unless the failure clue is already present in webhook metadata.
- It does not perform advanced source-code rewrites.
- It does not auto-merge PRs.
- Formatting and workflow YAML remediations are intentionally conservative and may still require manual adjustment.

---

## Prompts & LLM Usage (for implementers)

High-level prompting roles:

- **Classifier** — low-temperature prompt that returns JSON ({category, confidence, reasoning}) from a 4k-character log excerpt.
- **Generator** — produces a structured JSON/unified-diff patch using file context (≤6KB) and top-3 RAG results.
- **Debate** — two agents with different temperatures propose patches; a judge selects the safer option.

Example classification system prompt (short):

```
System: You are a precise classifier. Given a CI log excerpt, output JSON {"category": "...","confidence": 0-1, "reasoning":"..."}.
User: {log_excerpt}
```

Example generator system prompt (short):

```
System: You are a cautious repair agent. Output a JSON object: {"target_file":"...","patch":"<unified diff>","confidence":0-1,"explanation":"..."}.
User: Provide file_content, log_excerpt and RAG context.
```

---

## Tests

Run unit and integration tests with pytest:

```bash
python -m pytest tests/ -v
```

Fixtures and expected patches are under `tests/fixtures/`.

---

## Contributing

Please open issues or PRs. Follow the existing code style, add tests for new behavior, and update documentation files in the repo root.

Key files to review when contributing:

- `src/agent/` — classifiers, generators, validators
- `src/pipeline/` — GitHub client and log parser
- `tests/fixtures/` — sample failure logs and expected patches

---

## Security & Safety

- Webhooks are HMAC-SHA256 verified using `GITHUB_WEBHOOK_SECRET`.
- Patches are validated by Flake8 and AST parsing before any PR creation.
- OPA policies restrict auto-PR creation by confidence and target paths.

---

## License

MIT — see `LICENSE`.

---

## Where to go next

- Read `PROJECT_OVERVIEW.md` for executive-level overview.
- Read `ARCHITECTURE_DEEP_DIVE.md` for technical internals.
- Use `QUICK_REFERENCE.md` for deployment and troubleshooting.

Happy hacking — NeuroCI aims to make CI failures less painful.
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

For Docker Compose local development, the `webhook` service uses live reload when source files change.
Use `docker compose up -d` and verify the webhook endpoint is available at `http://localhost:8000/api/v1/webhook/github`.

### Local automation scripts

The repository includes helper scripts for Windows PowerShell:

- `.\scripts\start-local.ps1` — start Docker Compose, wait for webhook health, start ngrok, and show the public webhook URL.
- `.\scripts\stop-local.ps1` — stop Docker Compose, remove orphan containers, and stop ngrok.
- `.\scripts\test-webhook.ps1` — send local test `ping`, `push`, and `pull_request` webhook payloads.

If `ngrok` is not on PATH, place `ngrok.exe` in the repository root or the parent folder (`..`).

> Ensure the GitHub webhook secret configured in the GitHub repository matches `GITHUB_WEBHOOK_SECRET` in `.env` exactly.
> If the secret contains leading/trailing whitespace, it is trimmed automatically during startup.

Run the local stack:

```powershell
.\scripts\start-local.ps1
```

Test the webhook locally:

```powershell
.\scripts\test-webhook.ps1
```

Stop the stack cleanly:

```powershell
.\scripts\stop-local.ps1
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
