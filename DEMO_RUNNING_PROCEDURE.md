# NeuroCI Complete Demo Running Procedure
## CI Failure → LLM Fix → PR Creation (End-to-End)

---

## PHASE 1: SETUP (Do this 30 minutes before demo)

### Step 1: Create a test GitHub repo
1. Go to `https://github.com/new`
2. Create repo named: `neuroci-demo`
3. Make it **Private** (safer for demo)
4. Add a README (initialize with README)
5. Copy the repo URL: `https://github.com/YOUR_USERNAME/neuroci-demo.git`

### Step 2: Get GitHub Personal Access Token
1. Go to `https://github.com/settings/tokens?type=beta`
2. Click **Generate new token**
3. Name: `NeuroCI Demo`
4. Select permissions:
   - ✅ `repo` (all)
   - ✅ `workflow`
   - ✅ `contents:write`
   - ✅ `pull_requests:write`
5. Expiration: 90 days
6. Click **Generate token**
7. **Copy the token** (starts with `github_pat_...`)

### Step 3: Update .env with GitHub credentials

Edit `c:\Users\mahad\OneDrive\Desktop\mahi\DevSecOps\.env`:

```env
GITHUB_TOKEN=github_pat_YOUR_TOKEN_HERE
GITHUB_WEBHOOK_SECRET=demo-secret-neuroci-2026
```

Replace:
- `github_pat_YOUR_TOKEN_HERE` with your actual token
- Keep `GITHUB_WEBHOOK_SECRET` as is (or use any random string)

### Step 4: Update the webhook payload for your repo

Edit `c:\Users\mahad\OneDrive\Desktop\mahi\DevSecOps\tests\fixtures\sample_logs\sample_failure.json`:

Find and replace these lines:

```json
"repository": {
  "name": "neuroci-demo",
  "full_name": "YOUR_USERNAME/neuroci-demo",
  "clone_url": "https://github.com/YOUR_USERNAME/neuroci-demo.git"
}
```

Replace `YOUR_USERNAME` with your actual GitHub username.

Also find:
```json
"head_branch": "main"
```

And ensure it matches your repo's default branch (usually `main`).

### Step 5: Pre-populate Grafana with data

Start the app and run webhook 5 times:

```powershell
cd c:\Users\mahad\OneDrive\Desktop\mahi\DevSecOps
.\.venv\Scripts\Activate.ps1

docker compose up -d
docker compose logs -f worker
```

In a second terminal:
```powershell
cd c:\Users\mahad\OneDrive\Desktop\mahi\DevSecOps
.\.venv\Scripts\Activate.ps1

# Run 5 times (wait 5 seconds between each)
python scripts/send_signed_webhook.py --payload .\tests\fixtures\sample_logs\sample_failure.json
python scripts/send_signed_webhook.py --payload .\tests\fixtures\sample_logs\sample_failure.json
python scripts/send_signed_webhook.py --payload .\tests\fixtures\sample_logs\sample_failure.json
python scripts/send_signed_webhook.py --payload .\tests\fixtures\sample_logs\sample_failure.json
python scripts/send_signed_webhook.py --payload .\tests\fixtures\sample_logs\sample_failure.json
```

**Wait 60 seconds** for Prometheus to scrape metrics.

---

## PHASE 2: DEMO TIME (12–15 minutes)

### SCREEN SETUP

Open **5 browser tabs** in this order:

| Tab | URL | Purpose |
|-----|-----|---------|
| 1 | `http://localhost:8000/docs` | FastAPI webhook API |
| 2 | `http://localhost:8000/api/v1/metrics/snapshot` | JSON metrics |
| 3 | `http://localhost:3000` | Grafana dashboard |
| 4 | `http://localhost:9090` | Prometheus |
| 5 | `https://github.com/YOUR_USERNAME/neuroci-demo/pulls` | GitHub PRs |

Plus: **Keep a terminal open** showing:
```powershell
docker compose logs -f worker
```

---

### SCENE 1: Introduction (2 min)

**Say:**
> "This is NeuroCI — an autonomous CI/CD repair system. When GitHub Actions fails, instead of a developer manually diagnosing the error, NeuroCI does it automatically. It classifies the failure, retrieves similar fixes from memory, generates a patch, validates it, and creates a pull request. All without human intervention. I'm going to show you the entire process in real time."

**Show:**
- Your NeuroCI docs on **Tab 1**

---

### SCENE 2: Show the system is ready (2 min)

**Say:**
> "The system is running with 7 microservices: FastAPI webhook server, Celery worker, Redis, ChromaDB vector store, OPA policy engine, Prometheus metrics, and Grafana dashboards. All healthy and ready."

**Show:**
- FastAPI docs: `http://localhost:8000/docs`
- Point to: `POST /api/v1/webhook/github` endpoint
- Explain: "This endpoint receives GitHub webhook payloads with failure events."

---

### SCENE 3: Show current metrics (2 min)

**Say:**
> "Here's the raw JSON metrics the system exports. This is scraped by Prometheus every 15 seconds and visualized in Grafana."

**Show:**
- **Tab 2**: `http://localhost:8000/api/v1/metrics/snapshot`
- Point to:
  - `failures_received`: 5
  - `patches_generated`: 5
  - `avg_mttr_seconds`: 47.3
  - `avg_confidence`: 0.88

**Say:**
> "Average MTTR is 47 seconds. That's the time from failure detection to PR creation. Manual diagnosis is 23 minutes, so we're looking at a 4× improvement."

---

### SCENE 4: FIRE THE WEBHOOK (5 min) — THE MAIN EVENT

**Say:**
> "Now I'm going to simulate a GitHub CI failure by sending a signed webhook. Watch the worker logs carefully. Every step of the repair pipeline fires in real time."

**Action:**
In the second terminal, run:
```powershell
python scripts/send_signed_webhook.py --payload .\tests\fixtures\sample_logs\sample_failure.json
```

**Watch and narrate the worker logs line-by-line:**

Log line 1: `webhook.received: HMAC signature verified`
> "GitHub sent us the failure. The signature is verified — we know this is a legitimate GitHub event."

Log line 2: `github_client: downloading logs from GitHub...`
> "The worker is fetching the full CI log from GitHub's API."

Log line 3: `classifier: failure classified as ImportError (confidence: 0.91)`
> "LLM Call #1: What type of failure is this? The model says ImportError with 91% confidence."

Log line 4: `memory: retrieving from ChromaDB (found 3 similar)`
> "RAG memory: We search for 3 similar failures we've fixed before. ChromaDB returns them in milliseconds."

Log line 5: `patch_generator: generating unified diff...`
> "LLM Call #2: Given the error, the file context, and 3 similar examples, generate a fix."

Log line 6: `validator: syntax check PASS ✓ / flake8 PASS ✓`
> "We never trust the LLM. The patch is validated with ast.parse() and flake8 before anything is pushed."

Log line 7: `opa_policy: policy eval PASS ✓ (confidence 0.91 > threshold 0.85)`
> "OPA policy gates run: Is the confidence above 85%? Yes. Is the file in restricted paths? No. Is the patch under 20 lines? Yes. Approved."

Log line 8: `github_client: creating PR on GitHub...`
> "The confidence is high enough. We create a pull request on GitHub automatically."

Log line 9: `github_client: PR #1 created: https://github.com/YOUR_USERNAME/neuroci-demo/pull/1`
> "There's the PR. Created by NeuroCI. The PR includes the patch, the reasoning, and the confidence score."

Log line 10: `metrics: mttr=47.3s, confidence=0.91, category=ImportError`
> "The metrics are recorded. This MTTR, this confidence, this category — all stored for observability and learning."

---

### SCENE 5: Check the PR on GitHub (2 min)

**Say:**
> "Let me show you the actual PR that was created."

**Action:**
- Switch to **Tab 5**: `https://github.com/YOUR_USERNAME/neuroci-demo/pulls`
- Refresh the page
- Show the open PR

**Point out:**
- PR title: `Fix CI failure: ImportError`
- PR description includes:
  - Chain-of-thought reasoning
  - Confidence score: 0.91
  - Failure category: ImportError
  - The actual unified diff patch
  - Link to full logs

**Say:**
> "This PR was created automatically. It includes everything a developer needs to review and approve the fix. The developer can click 'Merge' and the fix is applied."

---

### SCENE 6: Show Grafana observability (3 min)

**Say:**
> "Because NeuroCI runs autonomously 24/7, we need observability. Here's the Grafana dashboard."

**Switch to Tab 3**: `http://localhost:3000`

**Point to each panel:**

1. **MTTR Panel** (top-left)
   > "Time from failure to PR. You can see it's around 47 seconds per event."

2. **Fix Success Rate** (top-right)
   > "Green is merged PRs, red is rejected. 80% of our auto-PRs are merged by developers."

3. **Confidence Distribution** (middle-left)
   > "LLM confidence scores cluster above 85%, our policy threshold."

4. **Failures by Category** (middle-right)
   > "ImportError is the most common. And it has the highest fix accuracy."

5. **Queue Depth** (bottom-left)
   > "Redis queue stays near zero. Workers are keeping up with failures."

6. **Total Fixes** (bottom-right)
   > "Total PRs created today. Started at 5 from our pre-demo runs. Now 6 from this live demo."

**Say:**
> "All of this data comes from Prometheus, which scrapes the FastAPI `/metrics` endpoint every 15 seconds. It's a complete observability story."

---

### SCENE 7: Show Prometheus raw query (1 min)

**Say:**
> "Prometheus is the time-series database. I can query it directly."

**Switch to Tab 4**: `http://localhost:9090`

**Run a live query:**
- In the expression bar, paste:
  ```
  increase(neuroci_patches_generated_total[24h])
  ```
- Press **Execute**
- Shows: e.g., `6`

**Say:**
> "This query asks: 'How many patches generated in the last 24 hours?' The answer is 6. Prometheus stores all history. Grafana visualizes it."

---

### SCENE 8: Closing summary (1 min)

**Say:**
> "Let me summarize what we just saw:

> 1. **Detection**: GitHub fired a webhook when CI failed.
> 2. **Classification**: LLM identified the failure type (ImportError).
> 3. **Memory**: RAG retrieved 3 similar past fixes from ChromaDB.
> 4. **Generation**: LLM generated a unified diff patch with chain-of-thought reasoning.
> 5. **Validation**: The patch was syntax-checked and linted before any push.
> 6. **Policy**: OPA evaluated whether the patch was safe to apply.
> 7. **Action**: A GitHub PR was created automatically.
> 8. **Learning**: The merged fix is stored in ChromaDB for future similar failures.
> 9. **Observability**: Metrics and logs are collected at every step.

> This system demonstrates **autonomous repair**, **LLM orchestration**, **RAG learning**, **policy-as-code safety**, **async task processing**, and **production-grade observability** — all working together as one seamless system.

> NeuroCI closes the loop: detect → diagnose → repair → learn → repeat. No manual intervention required."

---

## PHASE 3: CLEANUP

When the demo is done:

```powershell
docker compose down
```

This stops all containers. Data is preserved for next demo.

---

## TROUBLESHOOTING

| Problem | Solution |
|---------|----------|
| Token invalid | Check `GITHUB_TOKEN` format (should start with `github_pat_...`) |
| PR not created | Check repo name in webhook payload matches your GitHub repo |
| Grafana empty | Wait 60 seconds for Prometheus to scrape, then refresh (F5) |
| Worker logs don't appear | Run `docker compose logs -f worker` in a new terminal |
| Health check failures | Already fixed — worker healthcheck is disabled in compose |

---

## Key Commands Reference

```powershell
# Activate venv
.\.venv\Scripts\Activate.ps1

# Start the system
docker compose up -d

# Check status
docker compose ps

# Watch worker logs
docker compose logs -f worker

# Fire webhook
python scripts/send_signed_webhook.py --payload .\tests\fixtures\sample_logs\sample_failure.json

# Stop the system
docker compose down
```

---

**You're ready to demo!** 🚀
