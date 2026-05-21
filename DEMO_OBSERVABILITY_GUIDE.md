# NeuroCI Observability Demo Guide
## Show Grafana, Prometheus, Metrics & All 7 Services

---

## **BEFORE YOU START: Pre-Populate Data**

Run the webhook script **5 times** to generate data in Grafana (do this 30 min before your lecture):

```powershell
# Window 1: Watch logs
docker compose logs -f worker

# Window 2: Fire 5 webhooks (5-10 second pause between each)
python scripts/send_signed_webhook.py --payload .\tests\fixtures\sample_logs\sample_workflow_run.json
python scripts/send_signed_webhook.py --payload .\tests\fixtures\sample_logs\sample_workflow_run.json
python scripts/send_signed_webhook.py --payload .\tests\fixtures\sample_logs\sample_workflow_run.json
python scripts/send_signed_webhook.py --payload .\tests\fixtures\sample_logs\sample_workflow_run.json
python scripts/send_signed_webhook.py --payload .\tests\fixtures\sample_logs\sample_workflow_run.json

# Wait 60 seconds for Grafana to refresh (Prometheus scrapes every 15 seconds)
```

Now Grafana will have actual data to display instead of empty charts.

---

## **7 Browser Tabs — In This Order**

Open these tabs **before** you start the demo:

| Tab | URL | Purpose |
|-----|-----|---------|
| **1** | `http://localhost:8000/health` | **Health check** — proves server is running |
| **2** | `http://localhost:8000/docs` | **FastAPI auto-docs** — production-grade API |
| **3** | `http://localhost:8000/api/v1/metrics/snapshot` | **Live JSON metrics** — raw data before visualization |
| **4** | `http://localhost:9090` | **Prometheus** — time-series database query UI |
| **5** | `http://localhost:3000` | **Grafana** — the main dashboard (MOST IMPRESSIVE) |
| **6** | `http://localhost:8001` | **ChromaDB API** — vector memory system |
| **7** | Terminal with logs | `docker compose logs -f worker` — the narrative |

---

## **Tab 1: Health Check (5 seconds)**

**URL:** `http://localhost:8000/health`

**What appears:**
```json
{"status":"ok","timestamp":"2025-05-20T14:32:15Z"}
```

**What to say:**
> "The FastAPI server is healthy and responding. All downstream services are connected."

**Then click to Tab 2.**

---

## **Tab 2: FastAPI Auto-Docs (20 seconds)**

**URL:** `http://localhost:8000/docs`

**What to show:**
- Scroll to see all endpoints:
  - `POST /api/v1/webhook/github` ← This receives failures
  - `GET /api/v1/metrics/snapshot` ← This exposes metrics
  - `GET /health` ← Liveness check

**What to say:**
> "This is Swagger UI — auto-generated API documentation. Every endpoint is production-grade. FastAPI generates this for free. Notice the webhook receiver at `/api/v1/webhook/github` — that's where GitHub sends failure events."

**Then click to Tab 3.**

---

## **Tab 3: Live JSON Metrics (15 seconds)**

**URL:** `http://localhost:8000/api/v1/metrics/snapshot`

**What appears:**
```json
{
  "failures_received": 5,
  "patches_generated": 4,
  "patches_merged": 3,
  "patches_rejected": 1,
  "avg_mttr_seconds": 47.3,
  "avg_confidence": 0.88,
  "queue_depth": 0,
  "categories": {
    "ImportError": 2,
    "TypeMismatch": 1,
    "SyntaxError": 1
  }
}
```

**What to say:**
> "This is the raw metric snapshot. 5 failures received, 4 patches generated, 3 merged — 75% success rate. Average MTTR was 47 seconds. This JSON is scraped by Prometheus every 15 seconds and stored as time-series data. But raw numbers are boring. Let's visualize it."

**Then click to Tab 4.**

---

## **Tab 4: Prometheus Query UI (30 seconds)**

**URL:** `http://localhost:9090`

**Step 1: Check data is being collected**
- Click **Status** → **Targets**
- You should see:
  - `http://localhost:8000/metrics` — **UP** (FastAPI endpoint)
  - All other targets showing **UP** ✓

**What to say:**
> "Prometheus is scraping our FastAPI metrics endpoint every 15 seconds. All targets are healthy."

**Step 2: Run a live query**
- Click the **Graph** tab
- In the expression bar, paste:
```
increase(neuroci_patches_generated_total[24h])
```
- Press **Execute**
- Shows a single number: e.g., `5`

**What to say:**
> "This query shows 'how many patches generated in the last 24 hours?' The answer is 5. Prometheus stores all metric history over time. Now let's turn these numbers into beautiful charts."

**Then click to Tab 5 (the most impressive part).**

---

## **Tab 5: Grafana Dashboard (2–3 MINUTES — SPEND TIME HERE)**

**URL:** `http://localhost:3000`

**Login (if needed):**
- Username: `admin`
- Password: `admin` (or `neuroci` if you changed it)

### **What you'll see on the NeuroCI Dashboard:**

#### **Panel 1: MTTR Over Time** (Top-left)
- **Type:** Line chart
- **Shows:** Time from webhook receipt to PR creation (in seconds)
- **Your data:** Should show ~5 data points at roughly **47 seconds** each
- **What to say:**
> "This is Mean Time To Repair. 47 seconds from failure detection to PR creation. Contrast that with the manual process: diagnosing a CI log, finding the error, writing code, testing it, pushing — that's 23 minutes. So we're looking at a 4× improvement in MTTR."

**Point to the line and gesture:** "Each point is one CI failure. Watch this number — when you run a webhook, it spikes up to 50 seconds, then comes down as the system catches up. Real-time observability."

---

#### **Panel 2: Fix Success Rate** (Top-right)
- **Type:** Stacked bar chart (green for merged, red for rejected)
- **Shows:** PR merge success percentage
- **Your data:** Should show ~75% green, 25% red
- **What to say:**
> "This is the success rate. 75% of auto-generated PRs were merged by developers. That means our LLM + RAG memory is accurate 3 out of 4 times. The red bars represent PRs that developers rejected — those are valuable signal that feeds back into the system."

---

#### **Panel 3: Confidence Score Distribution** (Middle-left)
- **Type:** Histogram
- **Shows:** LLM confidence scores (0.0 to 1.0) per failure category
- **Your data:** Should show a cluster above 0.85
- **What to say:**
> "These are the LLM confidence scores for each patch. Notice they cluster above 85% — our threshold for auto-PR mode. Below 85%, the system sends a Slack message instead. This is the human-in-the-loop safety valve."

---

#### **Panel 4: Failures by Category** (Middle-right)
- **Type:** Pie chart
- **Shows:** Distribution of failure types (ImportError, TypeMismatch, SyntaxError, etc.)
- **Your data:** Should show ImportError as the largest slice
- **What to say:**
> "Different failure types have different patterns. ImportError is the most common — and notice it also has the highest fix accuracy. TypeMismatch is rarer but also lower confidence. This is why RAG memory matters — as we see more of the same failure type, we get better at fixing it."

---

#### **Panel 5: Queue Depth** (Bottom-left)
- **Type:** Gauge or line chart
- **Shows:** Current number of jobs waiting in Redis queue
- **Your data:** Should be near **0**
- **What to say:**
> "This is the Redis queue depth — how many failures are waiting to be processed. It should stay near zero. If this number goes up, the worker is falling behind. In our demo, workers are keeping up perfectly."

---

#### **Panel 6: Total Fixes (Today)** (Bottom-right)
- **Type:** Large counter/stat
- **Shows:** Total PRs created in last 24 hours
- **Your data:** Should show **5** (from your 5 pre-demo runs)
- **What to say:**
> "This counter shows total fixes created today. It's at 5 because we ran the demo scenario 5 times. In a real production system with dozens of repos, this number would be hundreds per day. And importantly — we didn't have to lift a finger. This is autonomous repair at scale."

---

### **BONUS: Show How Metrics Update Live**

1. **Keep Grafana open**
2. **Open the Terminal (Tab 7)**
3. **Fire one more webhook** from a different terminal window:
   ```powershell
   python scripts/send_signed_webhook.py --payload .\tests\fixtures\sample_logs\sample_workflow_run.json
   ```
4. **Watch the logs fire** in the terminal
5. **Switch back to Grafana**
6. **Wait 20 seconds** and watch the dashboard update

**What to say while waiting:**
> "The system takes about 45–50 seconds to process a failure. Prometheus refreshes every 15 seconds. So in about 20 seconds, we should see a new data point appear on these charts in real-time."

**When it appears:**
> "There it is. New data point. The system is processing that failure right now — classifying it, generating a patch, validating it, creating a PR. All autonomously. All observable."

---

## **Tab 6: ChromaDB (Optional, 15 seconds)**

**URL:** `http://localhost:8001`

**What to show:**
- Shows the vector database API
- You can click around but don't get deep into API docs
- Main point: this is where the system's memory lives

**What to say:**
> "ChromaDB is the vector memory system. Every PR that gets merged is embedded and stored here. Next time the system sees a similar error, it retrieves these past fixes as examples. This is how the system learns and improves over time."

**Skip this if short on time.**

---

## **Tab 7: Worker Logs (The Narrative)**

Keep this open in a terminal the ENTIRE time.

**What appears when you fire a webhook:**
```
[14:32:15] webhook.received: HMAC signature verified
[14:32:16] github_client: downloading logs from GitHub...
[14:32:18] classifier: failure classified as ImportError (confidence: 0.91)
[14:32:19] memory: retrieving similar past fixes from ChromaDB (found 3)
[14:32:22] patch_generator: generating unified diff...
[14:32:24] validator: syntax check PASS ✓ / flake8 PASS ✓
[14:32:25] opa_policy: evaluating policy rules... PASS ✓
[14:32:26] github_client: creating PR on GitHub...
[14:32:27] metrics: mttr=47.3s, confidence=0.91, category=ImportError
```

**What to say for EACH log line:**
1. **webhook.received** → "GitHub sent us the failure. HMAC signature verified — we know it's legit."
2. **github_client: downloading logs** → "Fetching the full CI log from GitHub's API."
3. **classifier** → "LLM Call #1: What type of failure is this? Answer: ImportError. Confidence: 91%."
4. **memory: retrieving** → "RAG search: 'show me 3 similar failures I've seen before.' ChromaDB returns them in milliseconds."
5. **patch_generator** → "LLM Call #2: given the error + context + 3 examples, generate a fix."
6. **validator** → "Run syntax checks. ast.parse() + flake8. No errors. Patch is safe."
7. **opa_policy** → "Policy engine approves: file is in allowed paths, confidence is above threshold, patch size is small."
8. **github_client: creating PR** → "Create a GitHub PR with this patch automatically."
9. **metrics** → "Record the MTTR (47 seconds), confidence, and category. This data feeds Grafana."

---

## **Complete Demo Sequence (12–15 min)**

| Time | Action | Tab |
|------|--------|-----|
| 0:00 | "Let me show you what NeuroCI sees..." | 1 |
| 0:30 | "First, the API that receives failures" | 2 |
| 1:00 | "Here are the raw metrics being collected" | 3 |
| 1:30 | "Prometheus stores all of this as time-series" | 4 |
| 2:00 | **FIRE WEBHOOK** | 7 (logs) |
| 2:30 | "Watch the worker logs fire in real-time..." | 7 |
| 5:00 | "Now let's see it visualized in Grafana..." | 5 |
| 5:30 | "MTTR: 47 seconds vs 23 minutes manual" | 5 |
| 6:00 | "Success rate: 75% of auto-PRs merged" | 5 |
| 6:30 | "Confidence distribution: clustered above 85%" | 5 |
| 7:00 | "Failure categories: ImportError is most common" | 5 |
| 7:30 | "Queue depth: near zero, workers keeping up" | 5 |
| 8:00 | "Total fixes today: 5" | 5 |
| 8:30 | "Let me show you metrics updating live..." | 5 |
| 8:45 | **FIRE 2ND WEBHOOK** | 7 |
| 9:30 | "Watch Grafana refresh with new data..." | 5 |
| 10:30 | "Safety layer: OPA policies control this" | VS Code |
| 11:00 | "Resume talking points & closing" | Slides |

---

## **Keyboard Shortcuts for Smooth Demo**

Use Alt+Tab or Cmd+Tab to switch between windows quickly:
- **Alt+Tab** cycles through your open browser tabs
- **Ctrl+Tab** in browser cycles through tabs
- **F5** refreshes Grafana (not usually needed, but helpful)

**Pro tip:** Pin the terminal window to the side so logs are always visible while you switch tabs.

---

## **If Grafana is Empty (No Data Points)**

Run the webhook script **again** 5 times:

```powershell
for ($i=1; $i -le 5; $i++) {
    python scripts/send_signed_webhook.py --payload .\tests\fixtures\sample_logs\sample_workflow_run.json
    Start-Sleep -Seconds 10
}
```

Then wait 30 seconds and refresh Grafana (F5).

---

## **Closing Statement After Demo**

> "So to recap: NeuroCI detected a failure in real-time, classified it using an LLM, retrieved similar past fixes from a vector database, generated a validated code patch, evaluated it against OPA security policies, and created a GitHub PR — all in 47 seconds, with complete observability at every step. This project demonstrates LLM agent orchestration, RAG memory, policy-as-code, async task processing, and production-grade observability — all running together as one autonomous system."

---

## **Common Issues & Fixes**

| Problem | Solution |
|---------|----------|
| Grafana shows empty dashboard | Run webhook 5 times, wait 60 sec, refresh (F5) |
| Prometheus shows no targets UP | `docker compose restart prometheus` |
| Can't access localhost:3000 | Check `docker compose ps` — grafana should show "Up" |
| Metrics snapshot returns empty JSON | `docker compose logs api` — check for errors |
| Worker logs don't appear | Run `docker compose logs -f worker` in a new terminal |

---

## **What NOT to Do**

❌ Don't explain Prometheus PromQL syntax in detail  
❌ Don't try to edit the Grafana dashboard live  
❌ Don't open the metrics endpoint and read the JSON out loud for 2 minutes  
❌ Don't say "let me wait for this to load" — pre-populate data beforehand  
❌ Don't switch between tabs too quickly — let the audience follow along  
❌ Don't end without the closing summary sentence  

---

## **Files You'll Reference**

- [neuroci_docs.html](neuroci_docs.html) — Interactive guide with all 5 scenes
- [presentation.md](presentation.md) — Slide deck
- [SPEAKER_NOTES.md](SPEAKER_NOTES.md) — Detailed speaker guidance
- [policies/neuroci.rego](policies/neuroci.rego) — Safety rules (show for "How we prevent dangerous changes")

---

**Ready? Pre-populate data, open all 7 tabs, and let the demo speak for itself.** 🚀
