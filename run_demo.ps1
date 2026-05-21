# Run NeuroCI demo: starts services, waits for readiness, sends signed webhook, shows worker logs

# Start Docker Compose
Write-Host "Starting local stack..."
docker compose up -d

# Wait for webhook health endpoint
$healthUrl = "http://localhost:8000/health"
$maxWait = 60
$elapsed = 0
Write-Host "Waiting for webhook at $healthUrl (timeout: $maxWait s)"
while ($elapsed -lt $maxWait) {
    try {
        $resp = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            Write-Host "Webhook healthy."
            break
        }
    } catch {
        Start-Sleep -Seconds 2
        $elapsed += 2
    }
}

if ($elapsed -ge $maxWait) {
    Write-Host "Timed out waiting for webhook health. Check logs: docker compose logs webhook" -ForegroundColor Yellow
    exit 1
}

# Send signed webhook using Python helper
Write-Host "Sending signed demo webhook..."
python .\scripts\send_signed_webhook.py --payload .\tests\fixtures\sample_logs\sample_workflow_run.json

# Give worker a few seconds to pick up task
Start-Sleep -Seconds 3

# Show recent worker logs
Write-Host "---- Recent worker logs ----"
docker compose logs --tail 200 worker

Write-Host "Demo complete. To follow live logs: docker compose logs -f worker"