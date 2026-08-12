"""Generate a human worklog for a code backup.

Usage: python -m app.services.worklog <new_archive> [<prev_archive>]

Compares the new archive against the previous one to find which files changed,
builds a capped unified diff as INPUT for IRIS (never persisted as code), asks
IRIS for a human-language summary, and writes <new_archive>.worklog.json.

The worklog the user sees is the IRIS summary (bullets) — no code is shown.
If NOVA is not configured, summary stays empty and the UI shows the file list.
"""
import sys
import os
import json
import hashlib
import tarfile
import tempfile
import shutil
import difflib
from datetime import datetime, timezone

TEXT_EXT = {".py", ".html", ".js", ".css", ".sh", ".sql", ".md", ".txt",
            ".json", ".cfg", ".ini", ".service", ".timer", ".toml", ".yaml", ".yml"}
DIFF_CAP = 60000  # chars sent to IRIS


def _safe_members(tf, dest):
    """Yield tarfile members that don't escape the destination directory."""
    dest = os.path.realpath(dest)
    for m in tf.getmembers():
        target = os.path.realpath(os.path.join(dest, m.name))
        if target.startswith(dest + os.sep) or target == dest:
            yield m


def _extract(archive: str) -> str:
    d = tempfile.mkdtemp(prefix="mg_wl_")
    with tarfile.open(archive, "r:gz") as t:
        t.extractall(d, members=_safe_members(t, d))
    return d


def _tree(root: str) -> dict:
    """Map rel-path -> (sha256, abs-path) for all files under root."""
    out = {}
    for base, _dirs, files in os.walk(root):
        for f in files:
            ap = os.path.join(base, f)
            rel = os.path.relpath(ap, root).lstrip("./")
            try:
                with open(ap, "rb") as fh:
                    out[rel] = (hashlib.sha256(fh.read()).hexdigest(), ap)
            except Exception:
                continue
    return out


def _read_lines(path: str):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines(keepends=True)
    except Exception:
        return None


def _is_text(rel: str) -> bool:
    return os.path.splitext(rel)[1].lower() in TEXT_EXT


def _build_diff(added, modified, removed, new_tree, prev_tree) -> str:
    chunks = []
    for rel in sorted(modified):
        if not _is_text(rel):
            chunks.append(f"### modificat (binar): {rel}\n")
            continue
        a = _read_lines(prev_tree[rel][1]) or []
        b = _read_lines(new_tree[rel][1]) or []
        d = difflib.unified_diff(a, b, fromfile=f"old/{rel}", tofile=f"new/{rel}", n=2)
        chunks.append("".join(d))
    for rel in sorted(added):
        if _is_text(rel):
            body = "".join((_read_lines(new_tree[rel][1]) or [])[:60])
            chunks.append(f"### adăugat: {rel}\n{body}\n")
        else:
            chunks.append(f"### adăugat (binar): {rel}\n")
    for rel in sorted(removed):
        chunks.append(f"### șters: {rel}\n")
    return ("".join(chunks))[:DIFF_CAP]


def _meta(new_archive: str) -> dict:
    try:
        with open(new_archive + ".meta", "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def main():
    if len(sys.argv) < 2:
        print("usage: worklog.py <new_archive> [<prev_archive>]", file=sys.stderr)
        return 2
    new_archive = sys.argv[1]
    prev_archive = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else ""

    new_dir = _extract(new_archive)
    prev_dir = _extract(prev_archive) if prev_archive and os.path.isfile(prev_archive) else None
    try:
        new_tree = _tree(new_dir)
        prev_tree = _tree(prev_dir) if prev_dir else {}

        added = [f for f in new_tree if f not in prev_tree]
        removed = [f for f in prev_tree if f not in new_tree]
        modified = [f for f in new_tree if f in prev_tree and new_tree[f][0] != prev_tree[f][0]]
        files_changed = sorted(set(added) | set(modified) | set(removed))

        summary = []
        if files_changed:
            diff_text = _build_diff(added, modified, removed, new_tree, prev_tree)
            try:
                from app.services import nova_llm
                summary = nova_llm.summarize(diff_text, files_changed)
            except Exception:
                summary = []

        meta = _meta(new_archive)
        worklog = {
            "archive": os.path.basename(new_archive),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "reason": meta.get("reason"),
            "note": meta.get("note"),
            "first_backup": prev_dir is None,
            "files_added": sorted(added),
            "files_modified": sorted(modified),
            "files_removed": sorted(removed),
            "files_changed": files_changed,
            "summary": summary,
            "summary_status": "ok" if summary else "unavailable",
        }
        with open(new_archive + ".worklog.json", "w", encoding="utf-8") as fh:
            json.dump(worklog, fh, ensure_ascii=False, indent=2)
        os.chmod(new_archive + ".worklog.json", 0o600)
        print(f"worklog: {len(files_changed)} changed, summary={'yes' if summary else 'no'}")
        return 0
    finally:
        shutil.rmtree(new_dir, ignore_errors=True)
        if prev_dir:
            shutil.rmtree(prev_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
