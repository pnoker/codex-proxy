#!/usr/bin/env python3
"""Inject custom model metadata into Codex CLI's models_cache.json.

Codex CLI only ships metadata for official OpenAI models. When using third-party
providers via codex-proxy, Codex falls back to conservative defaults which can
degrade performance. This script patches the cache with accurate metadata for
the models you actually use.

Usage:
    python scripts/inject_models.py              # inject defaults
    python scripts/inject_models.py --dry-run    # preview changes only
    python scripts/inject_models.py --list       # show current cache contents

The cache file lives at ~/.codex/models_cache.json by default.
Override with CODEX_CACHE_PATH environment variable.
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_CUSTOM_MODELS_FILE = _SCRIPT_DIR / "custom_models.json"


def _load_custom_models() -> list[dict]:
    if not _CUSTOM_MODELS_FILE.exists():
        print(
            f"Error: custom models file not found: {_CUSTOM_MODELS_FILE}",
            file=sys.stderr,
        )
        sys.exit(1)
    with open(_CUSTOM_MODELS_FILE, "r") as f:
        return json.load(f)


def default_cache_path() -> Path:
    return Path(os.environ.get(
        "CODEX_CACHE_PATH",
        Path.home() / ".codex" / "models_cache.json",
    ))


def load_cache(path: Path) -> dict:
    if not path.exists():
        print(f"Error: cache file not found: {path}", file=sys.stderr)
        print("Hint: run Codex CLI once first to generate it.", file=sys.stderr)
        sys.exit(1)
    with open(path, "r") as f:
        return json.load(f)


def save_cache(path: Path, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def list_models(cache_path: Path) -> None:
    custom_models = _load_custom_models()
    data = load_cache(cache_path)
    custom_slugs = {m["slug"] for m in custom_models}
    print(f"Cache: {cache_path}\n")
    print(f"{'slug':<25s} {'reasoning':>10s} {'parallel':>9s} {'ctx':>8s}  source")
    print("-" * 75)
    for m in data["models"]:
        src = "injected" if m["slug"] in custom_slugs else "official"
        print(
            f"{m['slug']:<25s} {str(m.get('supports_reasoning_summaries', '?')):>10s}"
            f" {str(m.get('supports_parallel_tool_calls', '?')):>9s}"
            f" {m.get('context_window', '?'):>8}  {src}"
        )
    print(f"\nTotal: {len(data['models'])} models")


def inject(cache_path: Path, dry_run: bool = False) -> None:
    custom_models = _load_custom_models()
    data = load_cache(cache_path)
    existing = {m["slug"] for m in data["models"]}

    added, updated = 0, 0
    for cm in custom_models:
        if cm["slug"] in existing:
            for i, m in enumerate(data["models"]):
                if m["slug"] == cm["slug"]:
                    data["models"][i] = cm
                    updated += 1
                    break
        else:
            data["models"].append(cm)
            added += 1

    if dry_run:
        print("[DRY RUN] No changes written.")
        print(f"  Would add: {added}, update: {updated}")
        print(f"  Resulting total: {len(data['models'])} models")
        return

    # Backup before writing
    backup = cache_path.with_suffix(".json.bak")
    shutil.copy2(cache_path, backup)

    save_cache(cache_path, data)
    print(f"Backup: {backup}")
    print(f"Written: {cache_path}")
    print(f"  Added: {added}, Updated: {updated}, Total: {len(data['models'])}")
    for cm in custom_models:
        print(
            f"  {cm['slug']:<20s} reasoning={str(cm.get('supports_reasoning_summaries', '?')):5s}"
            f"  parallel={str(cm.get('supports_parallel_tool_calls', '?')):5s}"
            f"  ctx={cm.get('context_window', '?')}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Inject custom model metadata into Codex CLI's models_cache.json",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview changes without writing to disk",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List all models in the cache with their source",
    )
    args = parser.parse_args()

    cache_path = default_cache_path()

    if args.list:
        list_models(cache_path)
    else:
        inject(cache_path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
