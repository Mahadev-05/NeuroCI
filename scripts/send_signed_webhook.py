"""Send a signed GitHub webhook to the local NeuroCI webhook receiver.

Usage:
    python scripts/send_signed_webhook.py --payload tests/fixtures/sample_logs/sample_workflow_run.json
    python scripts/send_signed_webhook.py --repo owner/repo --run-id 12345

It reads GITHUB_WEBHOOK_SECRET and optionally GITHUB_TOKEN from the environment or .env file in the repo root.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import hmac
import hashlib
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / '.env')

DEFAULT_URL = "http://localhost:8000/api/v1/webhook/github"
DEFAULT_PAYLOAD = "tests/fixtures/sample_logs/sample_workflow_run.json"


def compute_signature(secret: str, payload: bytes) -> str:
    return (
        "sha256="
        + hmac.new(key=secret.encode('utf-8'), msg=payload, digestmod=hashlib.sha256).hexdigest()
    )


def fetch_workflow_run_payload(repo: str, run_id: int, token: str) -> dict:
    """Fetch workflow run details from GitHub and build a synthetic webhook payload."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
    }
    api_base = "https://api.github.com"

    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
        run_resp = client.get(f"{api_base}/repos/{repo}/actions/runs/{run_id}")
        run_resp.raise_for_status()
        run_data = run_resp.json()

        repo_resp = client.get(f"{api_base}/repos/{repo}")
        repo_resp.raise_for_status()
        repo_data = repo_resp.json()

    return {
        "action": "completed",
        "workflow_run": {
            "id": run_data["id"],
            "name": run_data.get("name") or run_data.get("workflow_name", ""),
            "head_branch": run_data.get("head_branch", ""),
            "head_sha": run_data["head_sha"],
            "conclusion": run_data.get("conclusion"),
            "html_url": run_data.get("html_url", ""),
            "run_attempt": run_data.get("run_attempt", 1),
            "logs_url": run_data.get("logs_url", ""),
        },
        "repository": {
            "id": repo_data["id"],
            "full_name": repo_data["full_name"],
            "html_url": repo_data["html_url"],
            "default_branch": repo_data.get("default_branch", "main"),
        },
    }
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", "-p", default=DEFAULT_PAYLOAD)
    parser.add_argument("--repo", "-r", default="")
    parser.add_argument("--run-id", "-i", type=int)
    parser.add_argument("--url", "-u", default=DEFAULT_URL)
    parser.add_argument("--delivery", "-d", default="demo-1")
    args = parser.parse_args()

    secret = os.environ.get("GITHUB_WEBHOOK_SECRET")
    if not secret:
        print("GITHUB_WEBHOOK_SECRET not found in environment or .env. Set it and retry.")
        return 2

    if args.repo and args.run_id:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            print("GITHUB_TOKEN not found in environment or .env. Set it and retry.")
            return 2
        payload_data = fetch_workflow_run_payload(args.repo, args.run_id, token)
        payload = json.dumps(payload_data, separators=(',', ':')).encode('utf-8')
    else:
        payload_path = Path(args.payload)
        if not payload_path.exists():
            print(f"Payload file not found: {payload_path}")
            return 3
        payload = payload_path.read_bytes()

    signature = compute_signature(secret, payload)

    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "workflow_run",
        "X-GitHub-Delivery": args.delivery,
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(args.url, content=payload, headers=headers)
            print(f"POST {args.url} -> {resp.status_code}")
            try:
                print(resp.text)
            except Exception:
                pass
    except Exception as e:
        print(f"Error sending webhook: {e}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
