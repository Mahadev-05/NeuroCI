NeuroCI — Demo Script

Goal: Run a short local demo that shows a failing workflow being processed and a generated patch.

Prerequisites:
- Docker & Docker Compose installed
- `.env` configured with minimal placeholders (no external LLM keys required for demo)

Steps (PowerShell):

1. Start local stack

```powershell
docker compose up -d
docker compose ps
```

2. Wait for services to be ready (watch `webhook` and `worker` logs)

```powershell
docker compose logs -f webhook
```

3. Trigger demo webhook using fixture

```powershell
curl -X POST http://localhost:8000/api/v1/webhook/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: workflow_run" \
  -H "X-GitHub-Delivery: demo-1" \
  -d @tests/fixtures/sample_logs/sample_workflow_run.json
```

4. Observe worker processing in logs

```powershell
docker compose logs -f worker
```

5. View generated patch (local filesystem / logs)
- Check `docker compose logs worker` for `patch_generated` event
- Or inspect `tests/fixtures/expected_patches/` for precomputed diffs

6. (Optional) Run a unit test to simulate the pipeline

```powershell
python -m pytest tests/test_patch_generator.py::test_generate_patch -q
```

Fallback (no Docker):
- Open `tests/fixtures/expected_patches/` and show example diffs
- Show `VISUAL_OVERVIEW.md` and `PROJECT_OVERVIEW.md` diagrams

Cleanup:

```powershell
docker compose down
```

Notes:
- If external LLM calls are blocked, the demo uses recorded responses from `tests/fixtures`.
- For classroom, recommend preparing screenshots of Grafana and sample PRs beforehand.
