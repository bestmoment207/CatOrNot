#!/usr/bin/env python3
"""
encode_token.py — Encode data/youtube_token.json for use as a GitHub Secret.

Run this AFTER completing 'python main.py auth' on your local machine.
The output is a base64 string you paste as the YOUTUBE_TOKEN secret in GitHub.

Usage:
    python scripts/encode_token.py
"""
import base64
import sys
from pathlib import Path

TOKEN_PATH = Path(__file__).parent.parent / "data" / "youtube_token.json"

def main():
    if not TOKEN_PATH.exists():
        print("ERROR: data/youtube_token.json not found.")
        print()
        print("Run the following first to complete YouTube OAuth:")
        print("    python main.py auth")
        sys.exit(1)

    raw = TOKEN_PATH.read_bytes()
    if len(raw) < 50:
        print("ERROR: Token file looks empty or corrupt.")
        sys.exit(1)

    encoded = base64.b64encode(raw).decode()

    print()
    print("━" * 62)
    print("  ✓  YouTube token encoded successfully")
    print("━" * 62)
    print()
    print("Copy the string below and add it to your GitHub repository:")
    print("  Settings → Secrets and variables → Actions → New secret")
    print("  Name : YOUTUBE_TOKEN")
    print("  Value: (paste the string below)")
    print()
    print(encoded)
    print()
    print(f"  Token size : {len(raw)} bytes")
    print(f"  Encoded    : {len(encoded)} characters")
    print()
    print("━" * 62)
    print("  You only need to do this once.  The workflow will")
    print("  automatically refresh and re-save the token on each run.")
    print("━" * 62)
    print()

if __name__ == "__main__":
    main()
