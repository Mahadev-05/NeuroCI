<#
.SYNOPSIS
Send local test webhook payloads to the NeuroCI webhook receiver.
.DESCRIPTION
This script sends GitHub-style ping, push, and pull_request events to the local webhook endpoint and prints response status.
#>
[CmdletBinding()]
param(
    [string]$Url = 'http://127.0.0.1:8000/api/v1/webhook/github'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Info($Message) {
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-WarningMessage($Message) {
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-ErrorAndExit($Message) {
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    exit 1
}

function Write-Success($Message) {
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Get-EnvSecret {
    if ($env:GITHUB_WEBHOOK_SECRET) {
        return $env:GITHUB_WEBHOOK_SECRET
    }

    $scriptRoot = $PSScriptRoot
    $repoRoot = Split-Path -Parent $scriptRoot
    $envFile = Join-Path $repoRoot '.env'

    if (-not (Test-Path $envFile)) {
        return $null
    }

    foreach ($line in Get-Content $envFile) {
        $clean = $line.Trim()
        if ($clean -and -not $clean.StartsWith('#') -and $clean -match '^(GITHUB_WEBHOOK_SECRET)\s*=\s*(.*)$') {
            return $matches[2]
        }
    }

    return $null
}

function Compute-Sha256Signature($Secret, $PayloadBytes) {
    $hmac = [System.Security.Cryptography.HMACSHA256]::new([System.Text.Encoding]::UTF8.GetBytes($Secret))
    $hash = $hmac.ComputeHash($PayloadBytes)
    $signature = ([BitConverter]::ToString($hash) -replace '-', '').ToLowerInvariant()
    return "sha256=$signature"
}

function Send-TestEvent($Name, $EventType, $Payload) {
    Write-Host "`n=== Testing $Name event ===" -ForegroundColor White
    $json = ConvertTo-Json $Payload -Depth 10 -Compress
    $secret = Get-EnvSecret
    if (-not $secret) {
        Write-ErrorAndExit 'GITHUB_WEBHOOK_SECRET is not set in environment or .env file.'
    }
    Write-Info 'Using GitHub webhook secret from environment or .env for signature generation.'

    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $signature = Compute-Sha256Signature -Secret $secret -PayloadBytes $bytes

    try {
        $response = Invoke-WebRequest -Uri $Url -Method Post -Headers @{
            'X-Hub-Signature-256' = $signature
            'X-GitHub-Event'      = $EventType
            'Content-Type'        = 'application/json'
        } -Body $json -UseBasicParsing -TimeoutSec 10

        $status = $null
        try {
            $status = $response.StatusCode.value__
        } catch {
            try {
                $status = $response.StatusCode
            } catch {
                $status = 'unknown'
            }
        }

        Write-Success "$($Name): $status"

        $content = $null
        try {
            $content = $response.Content
        } catch {
            try {
                $content = $response.RawContent
            } catch {
                $content = $response | Out-String
            }
        }

        if ($content) {
            Write-Host $content -ForegroundColor Gray
        }
    } catch {
        $responseObject = $_.Exception.Response
        if ($responseObject) {
            $status = $null
            $content = $null

            try {
                $status = $responseObject.StatusCode.value__
            } catch {
                try {
                    $status = $responseObject.StatusCode
                } catch {
                    $status = 'unknown'
                }
            }

            try {
                $content = $responseObject.Content.ReadAsStringAsync().Result
            } catch {
                try {
                    $content = $responseObject.Content
                } catch {
                    $content = $responseObject | Out-String
                }
            }

            Write-WarningMessage "$Name returned HTTP $status"
            if ($content) {
                Write-Host $content -ForegroundColor Gray
            }
        } else {
            Write-ErrorAndExit "$Name failed: $($_.Exception.Message)"
        }
    }
}

$pingPayload = @{
    zen = 'Keep it logically awesome'
    repository = @{ full_name = 'owner/repo' }
}

$pushPayload = @{
    ref = 'refs/heads/main'
    after = 'abc123def456'
    repository = @{ full_name = 'owner/repo' }
    pusher = @{ name = 'test-user' }
}

$pullRequestPayload = @{
    action = 'closed'
    pull_request = @{ 
        number = 42
        title = 'NeuroCI: Fix ImportError (run #12345)'
        merged = $false
        body = 'Local webhook smoke test'
    }
    repository = @{ full_name = 'owner/repo' }
}

Write-Info "Sending local webhook tests to $Url"
Send-TestEvent -Name 'Ping' -EventType 'ping' -Payload $pingPayload
Send-TestEvent -Name 'Push' -EventType 'push' -Payload $pushPayload
Send-TestEvent -Name 'Pull request' -EventType 'pull_request' -Payload $pullRequestPayload
Write-Success 'Webhook smoke tests complete.'
