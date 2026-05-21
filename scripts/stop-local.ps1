<#
.SYNOPSIS
Stop the NeuroCI local developer stack and ngrok tunnel.
.DESCRIPTION
This script stops Docker Compose services, removes orphan containers, and stops any local ngrok tunnel started by start-local.ps1.
#>
[CmdletBinding()]
param()

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

function Stop-NgrokProcesses {
    $pidFile = Join-Path $ScriptRoot '.ngrok.pid'
    $foundProcess = $false

    if (Test-Path $pidFile) {
        try {
            $pid = Get-Content -Path $pidFile | Select-Object -First 1
            if ($pid -and [int]::TryParse($pid, [ref]$null)) {
                $process = Get-Process -Id $pid -ErrorAction SilentlyContinue
                if ($process) {
                    Stop-Process -Id $pid -ErrorAction SilentlyContinue
                    Write-Info "Stopped ngrok process with PID $pid."
                    $foundProcess = $true
                }
            }
        } catch {
            Write-WarningMessage "Unable to stop ngrok by PID file: $($_.Exception.Message)"
        }
        Remove-Item -Path $pidFile -ErrorAction SilentlyContinue
    }

    try {
        $ngrokProcs = Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'ngrok(\.exe)?' -and $_.CommandLine -match 'http\s+8000' }
        foreach ($proc in $ngrokProcs) {
            Stop-Process -Id $proc.ProcessId -ErrorAction SilentlyContinue
            Write-Info "Stopped ngrok process PID $($proc.ProcessId) from command line lookup."
            $foundProcess = $true
        }
    } catch {
        Write-WarningMessage "Error checking ngrok processes: $($_.Exception.Message)"
    }

    if (-not $foundProcess) {
        Write-Info 'No local ngrok processes were found.'
    }
}

Write-Info 'Stopping Docker Compose services...'
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-ErrorAndExit 'Docker CLI is not available on PATH. Cannot stop Docker Compose services.'
}

try {
    & docker compose down --remove-orphans
    Write-Success 'Docker Compose services stopped and orphan containers removed.'
} catch {
    Write-WarningMessage "docker compose down failed: $($_.Exception.Message)"
}

Write-Info 'Stopping ngrok tunnel(s)...'
Stop-NgrokProcesses
Write-Success 'Local stack shutdown completed.'
