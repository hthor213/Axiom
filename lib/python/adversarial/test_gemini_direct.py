#!/usr/bin/env python3
"""Bare-minimum Gemini API test. No server, no DB, no abstractions.

Usage:
    python3 lib/python/adversarial/test_gemini_direct.py specs/015-dashboard.md
    python3 lib/python/adversarial/test_gemini_direct.py specs/015-dashboard.md --key YOUR_KEY
"""

import json
import os
import sys
import urllib.request
import urllib.error

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 test_gemini_direct.py <file.md> [--key API_KEY]")
        sys.exit(1)

    filepath = sys.argv[1]
    api_key = None
    if "--key" in sys.argv:
        api_key = sys.argv[sys.argv.index("--key") + 1]

    # Step 1: Read the file
    print(f"1. Reading {filepath}...")
    with open(filepath) as f:
        content = f.read()
    print(f"   {len(content)} chars, {len(content.splitlines())} lines")

    # Step 2: Get API key
    if not api_key:
        api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        # Try .env
        env_path = os.path.join(os.getcwd(), ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.strip().startswith("GOOGLE_API_KEY="):
                        api_key = line.strip().split("=", 1)[1]
                        break
    if not api_key:
        print("   ERROR: No GOOGLE_API_KEY found in env, .env, or --key")
        sys.exit(1)
    print(f"2. API key: {api_key[:8]}...{api_key[-4:]}")

    # Step 2b: Resolve model name from API (same as production)
    print("2b. Resolving Gemini model from API...")
    list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    list_req = urllib.request.Request(list_url)
    with urllib.request.urlopen(list_req, timeout=10) as resp:
        models_data = json.loads(resp.read().decode())
    gemini_models = [
        m for m in models_data.get("models", [])
        if m.get("name", "").startswith("models/gemini-")
        and "generateContent" in m.get("supportedGenerationMethods", [])
        and not any(x in m["name"].lower() for x in ("image", "audio", "tts", "lite", "native-audio"))
    ]
    # Pick highest version pro model
    pro_models = [m for m in gemini_models if "pro" in m["name"].lower()]
    if pro_models:
        pro_models.sort(key=lambda m: m.get("name", ""), reverse=True)
        model = pro_models[0]["name"].removeprefix("models/")
    else:
        model = gemini_models[0]["name"].removeprefix("models/") if gemini_models else "gemini-pro"
    print(f"   Resolved: {model}")

    # Step 3: Build request
    url = f"{GEMINI_URL.format(model=model)}?key={api_key}"
    prompt = f"Review this spec for completeness, clarity, and potential issues:\n\n{content}"

    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 4096},
    }).encode()

    print(f"3. Calling {model}...")
    print(f"   URL: {url[:80]}...")

    # Step 4: Make the call — NO exception catching
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())

    # Step 5: Print response
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    print(f"4. Response ({len(text)} chars):\n")
    print(text[:2000])
    if len(text) > 2000:
        print(f"\n... ({len(text) - 2000} more chars)")

    print("\n5. SUCCESS — Gemini API works")


if __name__ == "__main__":
    main()
