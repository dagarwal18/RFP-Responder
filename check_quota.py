#!/usr/bin/env python3
"""
Groq Token Quota Checker

Queries the Groq API to check remaining token quotas for each configured
API key. Run this before starting a pipeline to verify you have enough
daily budget for a full run (~240K-320K tokens).

Usage:
    python check_quota.py                # reads keys from .env
    python check_quota.py --keys k1,k2   # check specific keys
    python check_quota.py --estimate 300000  # estimate runs remaining

Requires: requests, python-dotenv
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package required.  pip install requests")
    sys.exit(1)

# ── Groq rate limit constants (free tier for qwen/qwen3-32b) ─────
DEFAULT_TPD = 500_000  # tokens per day
DEFAULT_TPM = 6_000    # tokens per minute
DEFAULT_RPD = 1_000    # requests per day
DEFAULT_RPM = 60       # requests per minute

# Groq API endpoint
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"


def load_keys_from_env() -> list[str]:
    """Load Groq API keys from .env file(s)."""
    try:
        from dotenv import load_dotenv
        # Try loading from the project root
        for env_path in [".env", "../.env", "../../.env"]:
            if os.path.exists(env_path):
                load_dotenv(env_path)
                break
    except ImportError:
        pass  # dotenv not installed, rely on environment

    keys = []

    # Try GROQ_API_KEYS first (comma-separated)
    raw = os.environ.get("GROQ_API_KEYS", "").strip()
    if raw:
        keys = [k.strip() for k in raw.split(",") if k.strip()]

    # Fallback to single key
    if not keys:
        single = os.environ.get("GROQ_API_KEY", "").strip()
        if single:
            keys = [single]

    return keys


def check_key_validity(api_key: str) -> dict:
    """Check if an API key is valid by listing models."""
    try:
        resp = requests.get(
            GROQ_MODELS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if resp.status_code == 200:
            models = resp.json().get("data", [])
            model_ids = [m.get("id", "") for m in models]
            has_qwen = any("qwen3-32b" in mid for mid in model_ids)
            return {
                "valid": True,
                "models_available": len(models),
                "qwen3_32b_available": has_qwen,
            }
        elif resp.status_code == 401:
            return {"valid": False, "error": "Invalid API key (401 Unauthorized)"}
        else:
            return {"valid": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except requests.RequestException as e:
        return {"valid": False, "error": str(e)}


def probe_rate_limits(api_key: str) -> dict:
    """Send a minimal request to probe rate limit headers.

    Groq returns rate limit info in response headers:
      x-ratelimit-limit-tokens, x-ratelimit-remaining-tokens,
      x-ratelimit-limit-requests, x-ratelimit-remaining-requests,
      x-ratelimit-reset-tokens, x-ratelimit-reset-requests
    """
    try:
        resp = requests.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "qwen/qwen3-32b",
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 1,
            },
            timeout=30,
        )

        headers = resp.headers
        result = {
            "status_code": resp.status_code,
            "limit_tokens":      headers.get("x-ratelimit-limit-tokens", "N/A"),
            "remaining_tokens":  headers.get("x-ratelimit-remaining-tokens", "N/A"),
            "limit_requests":    headers.get("x-ratelimit-limit-requests", "N/A"),
            "remaining_requests": headers.get("x-ratelimit-remaining-requests", "N/A"),
            "reset_tokens":      headers.get("x-ratelimit-reset-tokens", "N/A"),
            "reset_requests":    headers.get("x-ratelimit-reset-requests", "N/A"),
        }

        # Also check for daily limits if present
        for suffix in ["tokens", "requests"]:
            for prefix in ["x-ratelimit-limit-", "x-ratelimit-remaining-", "x-ratelimit-reset-"]:
                key = f"{prefix}{suffix}_day"
                if key in headers:
                    result[key] = headers[key]

        if resp.status_code == 429:
            result["warning"] = "Rate limited! Wait before retrying."
            try:
                error_body = resp.json()
                result["error_message"] = error_body.get("error", {}).get("message", "")
            except Exception:
                pass

        return result

    except requests.RequestException as e:
        return {"error": str(e)}


def format_number(n: str | int) -> str:
    """Format a number with commas for readability."""
    try:
        return f"{int(n):,}"
    except (ValueError, TypeError):
        return str(n)


def main():
    parser = argparse.ArgumentParser(
        description="Check Groq API token quotas before starting a pipeline run.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python check_quota.py
  python check_quota.py --keys gsk_key1,gsk_key2
  python check_quota.py --estimate 300000
        """,
    )
    parser.add_argument(
        "--keys",
        type=str,
        default="",
        help="Comma-separated API keys (overrides .env)",
    )
    parser.add_argument(
        "--estimate",
        type=int,
        default=280_000,
        help="Estimated tokens per pipeline run (default: 280000)",
    )
    parser.add_argument(
        "--skip-probe",
        action="store_true",
        help="Skip the API probe (only validate keys)",
    )
    args = parser.parse_args()

    # ── Resolve keys ─────────────────────────────────────
    if args.keys:
        keys = [k.strip() for k in args.keys.split(",") if k.strip()]
    else:
        keys = load_keys_from_env()

    if not keys:
        print("❌ No API keys found!")
        print("   Set GROQ_API_KEYS or GROQ_API_KEY in .env, or pass --keys")
        sys.exit(1)

    print("═" * 60)
    print(f"  Groq Token Quota Checker — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Model: qwen/qwen3-32b")
    print(f"  Keys found: {len(keys)}")
    print(f"  Estimated tokens/run: {format_number(args.estimate)}")
    print("═" * 60)

    valid_key_count = 0

    for i, key in enumerate(keys, 1):
        masked = f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "***"
        print(f"\n── Key #{i}: {masked} {'─' * 30}")

        # Step 1: Validate
        validity = check_key_validity(key)
        if not validity["valid"]:
            print(f"  ❌ INVALID: {validity['error']}")
            continue

        print(f"  ✅ Valid | Models: {validity['models_available']} | Qwen3-32B: {'✅' if validity['qwen3_32b_available'] else '❌'}")

        if not validity["qwen3_32b_available"]:
            print("  ⚠️  qwen/qwen3-32b not available on this key!")
            continue

        valid_key_count += 1

        if args.skip_probe:
            print("  ⏭  Skipping API probe (--skip-probe)")
            continue

        # Step 2: Probe rate limits
        print("  📊 Probing rate limits...")
        limits = probe_rate_limits(key)

        if "error" in limits and "status_code" not in limits:
            print(f"  ❌ Probe failed: {limits['error']}")
            continue

        remaining_tok = limits.get("remaining_tokens", "N/A")
        limit_tok = limits.get("limit_tokens", "N/A")
        remaining_req = limits.get("remaining_requests", "N/A")
        limit_req = limits.get("limit_requests", "N/A")

        print(f"  Tokens/min:   {format_number(remaining_tok)} / {format_number(limit_tok)} remaining (TPM)")
        print(f"  Requests/min: {format_number(remaining_req)} / {format_number(limit_req)} remaining (RPM)")

        reset_tok = limits.get("reset_tokens", "N/A")
        reset_req = limits.get("reset_requests", "N/A")
        if reset_tok != "N/A":
            print(f"  Token reset: {reset_tok}")
        if reset_req != "N/A":
            print(f"  Request reset: {reset_req}")

        if limits.get("warning"):
            print(f"  ⚠️  {limits['warning']}")
        if limits.get("error_message"):
            print(f"     {limits['error_message']}")

    # ── Summary ──────────────────────────────────────────
    print(f"\n{'═' * 60}")
    print("  SUMMARY")
    print(f"{'═' * 60}")

    # Groq does not expose daily limits in headers.
    # Use the known free-tier TPD constant per valid key.
    total_tpd = valid_key_count * DEFAULT_TPD
    total_rpd = valid_key_count * DEFAULT_RPD
    effective_tpm = valid_key_count * DEFAULT_TPM

    print(f"  Valid keys:              {valid_key_count} / {len(keys)}")
    print(f"  Effective TPM:           {format_number(effective_tpm)}  ({valid_key_count} × {format_number(DEFAULT_TPM)})")
    print(f"  Effective TPD:           {format_number(total_tpd)}  ({valid_key_count} × {format_number(DEFAULT_TPD)})")
    print(f"  Effective RPD:           {format_number(total_rpd)}  ({valid_key_count} × {format_number(DEFAULT_RPD)})")
    print(f"  Est. tokens/run:         {format_number(args.estimate)}")

    if valid_key_count > 0:
        runs_possible = total_tpd / args.estimate
        approx_run_time_min = args.estimate / effective_tpm
        print(f"  Est. runs/day:           ~{runs_possible:.1f}")
        print(f"  Est. run time:           ~{approx_run_time_min:.0f} minutes (TPM-bottlenecked)")

        if runs_possible >= 1.0:
            print(f"\n  ✅ READY — enough daily quota for {int(runs_possible)} full run(s)")
        else:
            pct = (total_tpd / args.estimate) * 100
            print(f"\n  ❌ INSUFFICIENT — only {pct:.0f}% of a full run's budget available per day")

        print()
        print("  ℹ️  Note: Groq headers only show per-MINUTE limits (TPM).")
        print("     Daily limits (TPD) are not in headers — the estimates above")
        print(f"     use the known free-tier cap of {format_number(DEFAULT_TPD)} TPD/key.")

    print()


if __name__ == "__main__":
    main()
