<#
.SYNOPSIS
Start the NeuroCI local developer stack with Docker Compose and ngrok.
.DESCRIPTION
This script brings up the local Docker Compose stack, waits until the webhook service is healthy,
starts an ngrok tunnel to port 8000, prints the public webhook URL, and tails webhook logs.
#>
[CmdletBinding()]
param(
    [switch]$NoLogs
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

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path "$ScriptRoot\.."
Set-Location $RepoRoot
$EnvFilePath = Join-Path $RepoRoot '.env'
$EnvHashPath = Join-Path $ScriptRoot '.env.last.hash'

function Get-EnvHash {
    if (-not (Test-Path $EnvFilePath)) {
        return $null
    }
    try {
        return (Get-FileHash -Path $EnvFilePath -Algorithm SHA256).Hash
    } catch {
        return $null
    }
}

function Ensure-EnvHashState {
    $currentHash = Get-EnvHash
    if (-not $currentHash) {
        return
    }

    if (Test-Path $EnvHashPath) {
        $previousHash = Get-Content -Path $EnvHashPath -ErrorAction SilentlyContinue
        if ($previousHash -and $previousHash -ne $currentHash) {
            Write-Info 'Detected .env change; recreating webhook service to reload updated configuration.'
            try {
                & docker compose up -d --force-recreate webhook
            } catch {
                Write-WarningMessage "Failed to recreate webhook service: $($_.Exception.Message)"
            }
        }
    }

    $currentHash | Out-File -FilePath $EnvHashPath -Encoding ascii -Force
}

function Get-NgrokExePath {
    $candidates = @()
    try {
        $cmd = Get-Command ngrok -ErrorAction SilentlyContinue
        if ($cmd) { $candidates += $cmd.Source }
    } catch {
    }

    $local = Join-Path $RepoRoot 'ngrok.exe'
    if (Test-Path $local) { $candidates += $local }

    $parentLocal = Join-Path $RepoRoot '..\ngrok.exe'
    if (Test-Path $parentLocal) { $candidates += (Resolve-Path $parentLocal).Path }

    $download = Join-Path $env:USERPROFILE 'Downloads\ngrok.exe'
    if (Test-Path $download) { $candidates += $download }

    foreach ($path in $candidates | Select-Object -Unique) {
        if (Test-Path $path) {
            return $path
        }
    }

    return $null
}

function Test-DockerComposeAvailable {
    try {
        & docker compose version > $null 2>&1
        return $true
    } catch {
        return $false
    }
}

function Wait-UntilWebhookHealthy {
    $healthUri = 'http://127.0.0.1:8000/health'
    $attempt = 0
    $maxAttempts = 30

    while ($attempt -lt $maxAttempts) {
        try {
            $response = Invoke-WebRequest -Uri $healthUri -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
            if ($response.StatusCode -eq 200) {
                return $true
            }
        } catch {
        }

        $attempt++
        Write-Host "Waiting for webhook health (${attempt}/${maxAttempts})..." -NoNewline
        Start-Sleep -Seconds 2
        Write-Host "`r`n" -NoNewline
    }

    return $false
}

function Get-NgrokPublicUrl {
    $apiUrl = 'http://127.0.0.1:4040/api/tunnels'
    try {
        $body = Invoke-RestMethod -Uri $apiUrl -TimeoutSec 3 -ErrorAction Stop
        if ($null -eq $body.tunnels) {
            return $null
        }

        foreach ($tunnel in $body.tunnels) {
            if ($tunnel.proto -eq 'https' -and $tunnel.config.addr -match '127\.0\.0\.1:8000|localhost:8000|0\.0\.0\.0:8000') {
                return $tunnel.public_url
            }
        }

        return $null
    } catch {
        return $null
    }
}

function Start-NgrokTunnel {
    $ngrokExe = Get-NgrokExePath
    if (-not $ngrokExe) {
        Write-ErrorAndExit "ngrok executable not found. Install ngrok and ensure it is on PATH or placed in the repo root."
    }

    $existingUrl = Get-NgrokPublicUrl
    if ($existingUrl) {
        Write-Info "Reusing existing ngrok tunnel: $existingUrl"
        return $true
    }

    $pidFile = Join-Path $ScriptRoot '.ngrok.pid'
    try {
        $process = Start-Process -FilePath $ngrokExe -ArgumentList 'http', '8000', '--log=stdout' -PassThru -WindowStyle Hidden
        if ($process -and $process.Id) {
            $process.Id | Out-File -FilePath $pidFile -Encoding ascii -Force
            return $true
        }
    } catch {
        Write-WarningMessage "Failed to start ngrok: $($_.Exception.Message)"
        return $false
    }

    return $false
}

function Ensure-NgrokTunnel {
    $startTime = Get-Date
    $deadline = $startTime.AddSeconds(45)

    while ((Get-Date) -lt $deadline) {
        $publicUrl = Get-NgrokPublicUrl
        if ($publicUrl) {
            return $publicUrl
        }

        Start-Sleep -Seconds 2
    }

    return $null
}

Write-Info "Starting Docker Compose services..."
if (-not (Test-DockerComposeAvailable)) {
    Write-ErrorAndExit 'docker compose is not available. Install Docker Desktop or ensure Docker CLI is on PATH.'
}

Ensure-EnvHashState

try {
    & docker compose up -d
} catch {
    Write-ErrorAndExit "Docker Compose startup failed: $($_.Exception.Message)"
}

Write-Info 'Waiting for webhook service to become healthy...'
if (-not (Wait-UntilWebhookHealthy)) {
    Write-ErrorAndExit 'Webhook service did not become healthy within the timeout period.'
}

Write-Success 'Webhook service is healthy.'

Write-Info 'Starting ngrok tunnel to localhost:8000...'
if (-not (Start-NgrokTunnel)) {
    Write-ErrorAndExit 'Unable to start ngrok. Please verify your ngrok installation and auth token.'
}

$ngrokUrl = Ensure-NgrokTunnel
if (-not $ngrokUrl) {
    Write-ErrorAndExit 'ngrok tunnel did not become ready within the timeout period. Check ngrok logs or auth status.'
}

Write-Success "ngrok tunnel is ready: $ngrokUrl"
if (Test-Path $EnvFilePath) {
    Write-Success "Webhook secret loaded from .env"
} else {
    Write-WarningMessage "No .env file found; GitHub webhook secret may not be loaded into Docker Compose."
}
Write-Host ''
Write-Host 'Local webhook endpoint:' -ForegroundColor White
Write-Host "  $ngrokUrl/api/v1/webhook/github" -ForegroundColor Green
Write-Host 'Local health endpoint:' -ForegroundColor White
Write-Host "  http://127.0.0.1:8000/health" -ForegroundColor Green
Write-Host ''
Write-Host 'Stop the local stack with:' -ForegroundColor White
Write-Host "  .\scripts\stop-local.ps1" -ForegroundColor Cyan
Write-Host ''

if ($NoLogs) {
    Write-Info 'Skipping log tail because -NoLogs was supplied.'
    exit 0
}

Write-Info 'Tailing webhook logs. Press Ctrl+C to exit log view.'
try {
    & docker compose logs -f webhook
} catch {
    Write-WarningMessage "Docker logs tail exited or failed: $($_.Exception.Message)"
}
