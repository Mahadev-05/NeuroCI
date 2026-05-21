# NeuroCI Live Demo Runbook

This runbook is a simple, interview-ready flow for presenting the existing NeuroCI system. It focuses on the live path from GitHub push event to FastAPI webhook processing, with Docker, ngrok, Redis, Prometheus, Grafana, and the local smoke test.

## Demo Goal

Show that NeuroCI can run locally, expose a secure webhook endpoint through ngrok, receive a real GitHub webhook event, verify the request with HMAC SHA256, process the event in FastAPI, and expose operational visibility through logs and metrics.

## Architecture

GitHub sends webhook events to an ngrok HTTPS URL. ngrok forwards the request to the local FastAPI webhook service on port 8000. FastAPI verifies the GitHub signature using the shared webhook secret, parses the event type, and routes it to the correct handler. Redis supports queueing, deduplication, and state. Worker containers handle background repair workflows. Prometheus scrapes metrics from the app, and Grafana displays dashboards.

```text
GitHub Repository
    |
    | push webhook, signed with shared secret
    v
ngrok public HTTPS URL
    |
    | forwards to localhost:8000
    v
FastAPI webhook service
    |
    | verifies HMAC SHA256, parses event, logs result
    v
Redis / Celery worker / NeuroCI repair pipeline
    |
    v
Prometheus metrics -> Grafana dashboard
```

## Pre-Demo Checklist

- Docker Desktop is running.
- `.env` exists and contains `GITHUB_WEBHOOK_SECRET`.
- ngrok is installed, authenticated, and available on `PATH`, in the repo root, parent folder, or Downloads.
- GitHub webhook secret matches the local `.env` secret.
- The demo repository has webhook events enabled for `push`.
- PowerShell is opened at the project root.

Project root:

```powershell
cd C:\Users\mahad\OneDrive\Desktop\mahi\DevSecOps
```

## Terminal Command Sequence

### 1. Start The Local Environment

Run:

```powershell
.\scripts\start-local.ps1
```

Expected output:

```text
[INFO] Starting Docker Compose services...
[INFO] Waiting for webhook service to become healthy...
[OK] Webhook service is healthy.
[INFO] Starting ngrok tunnel to localhost:8000...
[OK] ngrok tunnel is ready: https://<random-id>.ngrok-free.app
[OK] Webhook secret loaded from .env

Local webhook endpoint:
  https://<random-id>.ngrok-free.app/api/v1/webhook/github
Local health endpoint:
  http://127.0.0.1:8000/health

Stop the local stack with:
  .\scripts\stop-local.ps1

[INFO] Tailing webhook logs. Press Ctrl+C to exit log view.
```

What to explain:

"This command starts the whole local stack with Docker Compose, waits for FastAPI to become healthy, starts ngrok, prints the public webhook endpoint, and then tails the webhook logs so we can watch GitHub events arrive in real time."

Keep this terminal open because it tails logs.

### 2. Show Docker Containers Running

Open a second PowerShell terminal and run:

```powershell
docker compose ps
```

Expected output should include:

```text
NAME                  SERVICE      STATUS
neuroci-webhook       webhook      running / healthy
neuroci-worker        worker       running
neuroci-redis         redis        running / healthy
neuroci-chromadb      chromadb     running
neuroci-opa           opa          running
neuroci-prometheus    prometheus   running
neuroci-grafana       grafana      running
```

What to explain:

"This confirms the stack is not just a single API. The webhook service receives events, Redis supports queueing and state, the worker runs background automation, OPA is available for policy checks, and Prometheus plus Grafana provide observability."

### 3. Show The ngrok Public Webhook URL

Use the URL printed by `start-local.ps1`:

```text
https://<random-id>.ngrok-free.app/api/v1/webhook/github
```

Optional command:

```powershell
Invoke-RestMethod http://127.0.0.1:4040/api/tunnels
```

Expected output includes an HTTPS `public_url`.

What to explain:

"GitHub cannot call localhost directly, so ngrok gives this local FastAPI service a temporary public HTTPS URL. For production, this would be a real deployed API endpoint behind a stable domain."

### 4. Open GitHub Webhook Settings

In the browser, go to:

```text
GitHub repository -> Settings -> Webhooks
```

Set or verify:

```text
Payload URL: https://<random-id>.ngrok-free.app/api/v1/webhook/github
Content type: application/json
Secret: same value as GITHUB_WEBHOOK_SECRET in .env
Events: Push events
Active: checked
```

What to explain:

"The important parts are the payload URL and the secret. GitHub signs each request with this secret. NeuroCI recomputes that signature locally and only accepts the event if the signatures match."

### 5. Trigger A Real GitHub Push Event

Make a tiny safe change and push it:

```powershell
git status
git checkout -b demo/neuroci-webhook-flow
Add-Content .\sample_push_file.txt "Demo push at $(Get-Date -Format o)"
git add .\sample_push_file.txt
git commit -m "Demo NeuroCI webhook push"
git push origin demo/neuroci-webhook-flow
```

Expected output:

```text
[demo/neuroci-webhook-flow <sha>] Demo NeuroCI webhook push
 1 file changed, 1 insertion(+)

Enumerating objects: ...
Writing objects: 100%
To https://github.com/<owner>/<repo>.git
 * [new branch]      demo/neuroci-webhook-flow -> demo/neuroci-webhook-flow
```

What to explain:

"This is the live trigger. The push goes to GitHub, GitHub creates a push webhook delivery, signs it, and sends it to the ngrok URL."

If you do not want to create a new branch during the interview, use an existing demo branch and make the same small append-only change.

### 6. Show Webhook Delivery Success In GitHub

Go to:

```text
GitHub repository -> Settings -> Webhooks -> Recent Deliveries
```

Open the latest `push` delivery.

Expected result:

```text
Event: push
Response code: 202
Response body:
{
  "accepted": true,
  "message": "Push event received for <owner>/<repo> on refs/heads/demo/neuroci-webhook-flow by <user>",
  "run_id": null
}
```

What to explain:

"A 202 response means the webhook receiver accepted the event. I use 202 because webhook processing can be asynchronous: the API validates and accepts the event quickly, then background services can continue the workflow."

### 7. Show FastAPI Logs

Return to the first terminal that is tailing logs.

Expected log lines include:

```text
webhook.security.verified github_event=push verification_status=passed
webhook.received github_event=push verification_status=passed
webhook.push_received repo=<owner>/<repo> ref=refs/heads/demo/neuroci-webhook-flow commit=<sha> pusher=<user>
```

What to explain:

"These logs prove the event reached FastAPI, the signature verification passed, and the push event was parsed and handled successfully."

Useful backup command if the log terminal is cluttered:

```powershell
docker compose logs --tail 80 webhook
```

### 8. Explain HMAC SHA256 Verification

Beginner-friendly explanation:

"GitHub and NeuroCI share a secret value. When GitHub sends a webhook, it combines the request body with that secret and creates a SHA256 HMAC signature. NeuroCI receives the request, computes the same signature using its local secret, and compares the result with GitHub's `X-Hub-Signature-256` header. If they match, the request is trusted. If they do not match, NeuroCI rejects it with 403."

Security points to mention:

- The secret itself is never sent over the network.
- The signature proves the payload was signed by someone who knows the secret.
- `hmac.compare_digest` is used for constant-time comparison to avoid timing leaks.
- This protects the webhook from unauthenticated or tampered requests.

### 9. Show Prometheus And Grafana

Health and metrics:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-WebRequest http://127.0.0.1:8000/metrics
```

Expected health output:

```text
status
------
healthy
```

Open:

```text
Prometheus: http://127.0.0.1:9090
Grafana:    http://127.0.0.1:3000
```

Grafana login:

```text
Username: admin
Password: neuroci
```

What to explain:

"For a DevSecOps system, success is not just automation. We also need visibility. Prometheus collects application metrics, and Grafana gives us an operational dashboard for monitoring the webhook and repair workflow."

### 10. Run The Automated Webhook Test Script

Run:

```powershell
.\scripts\test-webhook.ps1
```

Expected output:

```text
[INFO] Sending local webhook tests to http://127.0.0.1:8000/api/v1/webhook/github

=== Testing Ping event ===
[INFO] Using GitHub webhook secret from environment or .env for signature generation.
[OK] Ping: 202
{"accepted":true,"message":"GitHub ping event received","run_id":null}

=== Testing Push event ===
[INFO] Using GitHub webhook secret from environment or .env for signature generation.
[OK] Push: 202
{"accepted":true,"message":"Push event received for owner/repo on refs/heads/main by test-user","run_id":null}

=== Testing Pull request event ===
[INFO] Using GitHub webhook secret from environment or .env for signature generation.
[OK] Pull request: 202
{"accepted":true,"message":"PR #42 rejected - feedback recorded","run_id":42}

[OK] Webhook smoke tests complete.
```

What to explain:

"This script is my repeatable local safety check. It signs GitHub-style events with the same HMAC SHA256 method and sends them directly to FastAPI. It proves the receiver works even if GitHub or ngrok is unavailable during a demo."

## Two-Minute Presentation Script

"NeuroCI is a DevSecOps automation project that connects GitHub webhook events to an AI-assisted CI repair workflow. For this demo, I am showing the live webhook path end to end.

First, I start the local environment with `.\scripts\start-local.ps1`. This brings up the FastAPI webhook service, Redis, the worker, ChromaDB, OPA, Prometheus, and Grafana using Docker Compose. The script waits until the API is healthy, starts ngrok, and prints the public webhook URL.

Next, I confirm the containers are running with `docker compose ps`. This shows the system is operating as a small platform, not just a standalone script.

Then I copy the ngrok webhook URL into GitHub repository webhook settings. The payload URL points to `/api/v1/webhook/github`, the content type is JSON, and the secret matches my local `.env`.

Now I trigger a real push by committing and pushing a tiny demo change. GitHub receives that push, creates a webhook delivery, signs the payload with HMAC SHA256, and sends it to the ngrok URL.

In GitHub's webhook delivery page, I expect a 202 response. In the FastAPI logs, I expect to see `webhook.security.verified`, `webhook.received`, and `webhook.push_received`. That proves the event reached NeuroCI, passed security verification, and was processed successfully.

The security model is simple: GitHub and NeuroCI share a secret, but the secret is never sent. GitHub signs the request body, NeuroCI recomputes the signature, and mismatches are rejected.

Finally, I show Prometheus and Grafana for observability, and I run `.\scripts\test-webhook.ps1` as a repeatable local smoke test. This gives me both a real GitHub demo and a reliable backup path."

## Longer Detailed Demo Explanation

Start by framing the project:

"NeuroCI is designed to reduce the manual work around CI failures. The first reliable integration point is GitHub webhooks. If the webhook receiver is secure, observable, and repeatable, the rest of the automation has a strong foundation."

Explain the local stack:

"I run the platform locally through Docker Compose so every service starts consistently. The webhook container runs FastAPI on port 8000. Redis gives the system shared state and queueing support. The worker performs background automation. ChromaDB supports memory and retrieval. OPA gives a policy enforcement point. Prometheus and Grafana provide monitoring."

Explain ngrok:

"Because GitHub needs a public HTTPS endpoint, I use ngrok during local development. ngrok forwards the public URL to my local FastAPI service. This lets me test the exact GitHub integration without deploying to the cloud."

Explain GitHub configuration:

"In GitHub, the webhook points to the ngrok URL plus `/api/v1/webhook/github`. I configure JSON payloads and use the same secret as `GITHUB_WEBHOOK_SECRET` in the local environment. For the live demo, I enable push events because they are easy to trigger and validate."

Explain the live push:

"When I push a commit, GitHub immediately generates a push event. That event includes headers like `X-GitHub-Event` and `X-Hub-Signature-256`. FastAPI reads the raw request body, verifies the signature, then routes based on the event type."

Explain the logs:

"The key logs are `webhook.security.verified`, `webhook.received`, and `webhook.push_received`. Together they show three separate things: security passed, the event was accepted, and the push handler processed the payload."

Explain observability:

"I also expose `/health` and `/metrics`. Prometheus scrapes the metrics, and Grafana visualizes the system. That matters because automation needs operational visibility: I need to know whether webhooks are arriving, being accepted, and being processed."

Explain backup test:

"The local `test-webhook.ps1` script sends signed test events directly to the FastAPI endpoint. It uses the same secret and HMAC SHA256 flow, so it is a realistic smoke test. If GitHub delivery or ngrok has a temporary issue, I can still demonstrate the core webhook receiver."

## Demo Checklist

- Start stack with `.\scripts\start-local.ps1`.
- Copy the printed ngrok webhook endpoint.
- Run `docker compose ps`.
- Open GitHub webhook settings.
- Confirm payload URL, JSON content type, secret, push events, and active checkbox.
- Push a small commit to a demo branch.
- Open GitHub recent webhook deliveries.
- Confirm latest delivery is `push` with HTTP `202`.
- Show FastAPI logs with signature verification and push handling.
- Explain HMAC SHA256 in simple terms.
- Show `/health`, `/metrics`, Prometheus, or Grafana.
- Run `.\scripts\test-webhook.ps1`.
- End by summarizing reliability, security, and observability.

## Troubleshooting Backup Plan

### Docker Containers Do Not Start

Run:

```powershell
docker compose ps
docker compose logs --tail 100 webhook
```

Say:

"If a container fails, I check service status and recent logs first. The startup script also waits for the webhook health endpoint, so failures are visible early."

### ngrok URL Is Not Ready

Run:

```powershell
Invoke-RestMethod http://127.0.0.1:4040/api/tunnels
```

If needed, restart:

```powershell
.\scripts\stop-local.ps1
.\scripts\start-local.ps1
```

Say:

"ngrok URLs are temporary in local development. If the URL changes, I update the GitHub webhook payload URL."

### GitHub Delivery Returns 403

Check:

- GitHub webhook secret matches `.env`.
- `GITHUB_WEBHOOK_SECRET` is loaded by Docker Compose.
- The webhook service was restarted after changing `.env`.

Expected failed log:

```text
webhook.security.invalid_signature
```

Say:

"A 403 is expected when the signature does not match. That is the security control working."

### GitHub Delivery Does Not Appear

Check:

- Webhook is active.
- Push events are selected.
- The push went to the repository that owns the webhook.
- Payload URL uses the current ngrok URL.

Backup:

```powershell
.\scripts\test-webhook.ps1
```

Say:

"If GitHub delivery is delayed, I can still show the same signed webhook flow locally using the smoke test script."

### Logs Are Too Noisy

Run:

```powershell
docker compose logs --tail 80 webhook
```

Look for:

```text
webhook.security.verified
webhook.received
webhook.push_received
```

### Prometheus Or Grafana Is Slow

Use direct health and metrics endpoints:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-WebRequest http://127.0.0.1:8000/metrics
```

Say:

"The observability stack is available, but the core proof is the application exposing health and metrics endpoints and Prometheus being part of the compose stack."

## Common Interview Questions And Answers

**Q: Why use HMAC SHA256 for webhooks?**

A: It proves the request body was signed by someone who knows the shared secret. NeuroCI rejects requests with missing or invalid signatures, which protects the endpoint from unauthenticated spoofed events.

**Q: Why return HTTP 202 instead of 200?**

A: 202 means the event was accepted for processing. That fits webhook systems because the API should verify and acknowledge quickly, while longer repair workflows can continue asynchronously.

**Q: Why use ngrok?**

A: GitHub needs a public HTTPS endpoint. ngrok lets a local FastAPI service receive real GitHub webhooks without deploying the app during development.

**Q: What role does Redis play?**

A: Redis supports queueing, shared state, deduplication, and background workflow coordination between the webhook service and worker.

**Q: What happens if someone sends a fake webhook?**

A: Without the correct `X-Hub-Signature-256` value, the request fails signature verification and receives HTTP 403.

**Q: How do you know the system is working?**

A: I check three layers: GitHub shows a successful delivery, FastAPI logs show verification and processing, and health or metrics endpoints show the service is operational.

**Q: How would this change in production?**

A: ngrok would be replaced by a stable HTTPS endpoint behind real infrastructure, secrets would come from a secret manager, and monitoring would be connected to production alerting.

**Q: Why separate webhook and worker containers?**

A: The webhook service should stay fast and responsive. Long-running repair work belongs in background workers so GitHub receives a quick acknowledgment.

**Q: What is the most important security control in this demo?**

A: Signature verification. It ensures that only requests signed with the configured GitHub webhook secret are accepted.

**Q: What is your backup if the live GitHub push fails during the interview?**

A: I run `.\scripts\test-webhook.ps1`. It generates signed GitHub-style events locally and proves the same verification and routing path inside FastAPI.

## Clean Shutdown

After the demo:

```powershell
.\scripts\stop-local.ps1
```

Expected result:

```text
[OK] Docker Compose services stopped.
[OK] ngrok tunnel stopped.
```
