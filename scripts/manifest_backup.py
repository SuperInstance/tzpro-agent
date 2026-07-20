#!/usr/bin/env python3
"""manifest_backup.py - verified USB/cold backup for the vessel data twin.

Implements boat-agent docs/18, failure-mode F3 mitigation:
  * content-addressed manifests (sha256) per day (YYYY-MM-DD)
  * manifests are hash-chained across days
  * every copied file is re-hashed on the destination and verified
  * idempotent via size+mtime fast path, hash on doubt
  * warns loudly if destination filesystem is not NTFS (no exFAT archives)

Stdlib only. Python 3.10+.

Usage:
    python scripts/manifest_backup.py E:\\boat-backup
    python scripts/manifest_backup.py E:\\boat-backup --day 2026-07-19
    python scripts/manifest_backup.py E:\\boat-backup --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

DEFAULT_WORKSPACE = r"C:\Users\casey\.openclaw\workspace\tzpro-agent"
SOURCE_SUBDIRS = ("memory/blobs", "captures")
MANIFESTS_SUBDIR = "manifests"
HASH_CACHE_NAME = ".hashcache.json"

DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATE_TOKEN_RE = re.compile(r"(?:19|20)\d{2}-[01]\d-[0-3]\d")

HASH_CHUNK = 1 << 20  # 1 MiB

# Exit codes
EXIT_OK = 0
EXIT_VERIFY_FAILED = 1
EXIT_BAD_ARG = 2
EXIT_DEST_UNUSABLE = 3


# --------------------------------------------------------------------------- #
# Hashing
# --------------------------------------------------------------------------- #

def sha256_file(path: Path) -> str:
    """Stream sha256 of a file in 1 MiB chunks."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(HASH_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def load_hash_cache(manifests_dir: Path) -> dict:
    p = manifests_dir / HASH_CACHE_NAME
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_hash_cache(manifests_dir: Path, cache: dict) -> None:
    p = manifests_dir / HASH_CACHE_NAME
    try:
        p.write_text(json.dumps(cache, indent=2, sort_keys=True), "utf-8")
    except OSError as exc:
        print(f"  warn: could not write hash cache {p}: {exc}", file=sys.stderr)


def cached_sha256(path: Path, root: Path, cache: dict) -> str:
    """sha256 of path with size+mtime fast path; falls back to full hash."""
    rel = path.relative_to(root).as_posix()
    st = path.stat()
    entry = cache.get(rel)
    if (entry
            and entry.get("size") == st.st_size
            and int(entry.get("mtime", -1)) == int(st.st_mtime)):
        return entry["sha256"]
    digest = sha256_file(path)
    cache[rel] = {
        "mtime": int(st.st_mtime),
        "size": st.st_size,
        "sha256": digest,
    }
    return digest


# --------------------------------------------------------------------------- #
# Day classification
# --------------------------------------------------------------------------- #

def day_of(path: Path, root: Path) -> str:
    """Determine the YYYY-MM-DD a file belongs to.

    Prefer an explicit YYYY-MM-DD token found in the relative path
    (e.g. captures/v3/2026-07-19_.../foo.png); fall back to local mtime date.
    """
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        rel = path.as_posix()
    for m in DATE_TOKEN_RE.finditer(rel):
        cand = m.group(0)
        try:
            datetime.strptime(cand, "%Y-%m-%d")
            return cand
        except ValueError:
            continue
    mt = datetime.fromtimestamp(path.stat().st_mtime)
    return mt.strftime("%Y-%m-%d")


# --------------------------------------------------------------------------- #
# Manifest (hash-chained JSONL)
# --------------------------------------------------------------------------- #

def previous_manifest_sha256(manifests_dir: Path, current_day: str) -> str:
    """sha256 of the most recent manifest whose day is strictly < current_day.

    Returns "" when no earlier manifest exists (genesis of the chain).
    """
    candidates = []
    suffix = ".manifest.jsonl"
    for p in manifests_dir.glob(f"*{suffix}"):
        day = p.name[: -len(suffix)]
        if DAY_RE.match(day) and day < current_day:
            candidates.append((day, p))
    if not candidates:
        return ""
    candidates.sort(key=lambda t: t[0])
    return sha256_file(candidates[-1][1])


def write_manifest(manifests_dir: Path, day: str, prev_sha: str,
                   entries: list[dict]) -> Path:
    """Write <day>.manifest.jsonl. Line 1 is the hash-chain header."""
    manifests_dir.mkdir(parents=True, exist_ok=True)
    out = manifests_dir / f"{day}.manifest.jsonl"
    lines = [
        json.dumps(
            {"prev_manifest_sha256": prev_sha},
            separators=(",", ":"),
        )
    ]
    for e in entries:
        lines.append(json.dumps(e, separators=(",", ":"), sort_keys=True))
    out.write_text("\n".join(lines) + "\n", "utf-8")
    return out


def read_manifest_entries(manifest_path: Path) -> list[dict]:
    """Return the file entries of a manifest (skipping the chain header)."""
    out = []
    for line in manifest_path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if "prev_manifest_sha256" in obj:
            continue
        out.append(obj)
    return out


# --------------------------------------------------------------------------- #
# Copy + verify
# --------------------------------------------------------------------------- #

def sync_file(src: Path, dest_root: Path, root: Path, src_digest: str) -> str:
    """Ensure dest mirrors src. Returns 'skipped', 'repaired', or 'copied'.

    Fast path: identical size + mtime -> skipped.
    Doubt path (size matches, mtime drifts): hash compare; if equal, just
    repair mtime. Otherwise copy.
    """
    rel = src.relative_to(root)
    dest = dest_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    sst = src.stat()
    if dest.exists():
        try:
            dst = dest.stat()
        except OSError:
            dst = None
        if dst is not None and dst.st_size == sst.st_size:
            if int(dst.st_mtime) == int(sst.st_mtime):
                return "skipped"
            # doubt: same size, drift on mtime -> hash to decide
            if sha256_file(dest) == src_digest:
                try:
                    os.utime(dest, (sst.st_atime, sst.st_mtime))
                except OSError:
                    pass
                return "repaired"
    shutil.copy2(src, dest)
    return "copied"


def verify_day(dest_root: Path, manifest_path: Path) -> dict:
    """Re-hash every file on destination against the manifest."""
    entries = read_manifest_entries(manifest_path)
    ok = 0
    failed = []
    for e in entries:
        rel = e["relpath"]
        expected = e["sha256"]
        dest = dest_root / Path(rel)
        if not dest.exists():
            failed.append({
                "relpath": rel,
                "reason": "missing",
                "expected_sha256": expected,
                "expected_bytes": e.get("bytes"),
            })
            continue
        try:
            actual = sha256_file(dest)
            actual_bytes = dest.stat().st_size
        except OSError as exc:
            failed.append({
                "relpath": rel,
                "reason": f"read_error: {exc}",
                "expected_sha256": expected,
            })
            continue
        if actual == expected:
            ok += 1
        else:
            failed.append({
                "relpath": rel,
                "reason": "hash_mismatch",
                "expected_sha256": expected,
                "actual_sha256": actual,
                "expected_bytes": e.get("bytes"),
                "actual_bytes": actual_bytes,
            })
    return {"files": len(entries), "ok": ok, "failed": failed}


# --------------------------------------------------------------------------- #
# Filesystem detection (NTFS warning)
# --------------------------------------------------------------------------- #

def detect_filesystem(dest_root: Path) -> str | None:
    """Best-effort filesystem name for dest_root. None if unknown."""
    cur = dest_root.resolve()
    while not cur.exists() and cur != cur.parent:
        cur = cur.parent
    if os.name == "nt":
        anchor = cur.anchor
        if not anchor:
            return None
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(256)
            ok = ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(anchor), None, 0,
                None, None, None, buf, ctypes.sizeof(buf),
            )
            if ok:
                return buf.value or None
        except Exception:
            return None
        return None
    # POSIX best-effort via df(1)
    try:
        out = subprocess.run(
            ["df", "-PT", str(cur)],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if out.returncode == 0:
            rows = out.stdout.strip().splitlines()
            if len(rows) >= 2:
                fields = rows[-1].split()
                if len(fields) >= 2:
                    return fields[1]
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------- #
# Workspace + source enumeration
# --------------------------------------------------------------------------- #

def workspace_root(cli_ws: str | None) -> Path:
    ws = cli_ws or os.environ.get("TZPRO_WORKSPACE") or DEFAULT_WORKSPACE
    return Path(ws).expanduser().resolve()


def enumerate_sources(root: Path) -> list[Path]:
    """All files under any SOURCE_SUBDIR that exists."""
    files: list[Path] = []
    for sub in SOURCE_SUBDIRS:
        sub_path = root / sub
        if not sub_path.exists():
            print(f"  note: source subdir not present, skipping: {sub_path}")
            continue
        if sub_path.is_file():
            files.append(sub_path)
            continue
        for p in sub_path.rglob("*"):
            if p.is_file():
                files.append(p)
    return files


# --------------------------------------------------------------------------- #
# Main flow
# --------------------------------------------------------------------------- #

def parse_days(args) -> list[str]:
    if args.day:
        if not DAY_RE.match(args.day):
            raise ValueError(f"--day must be YYYY-MM-DD, got {args.day!r}")
        datetime.strptime(args.day, "%Y-%m-%d")  # raises ValueError if invalid
        return [args.day]
    today = date.today()
    return [
        (today - timedelta(days=1)).strftime("%Y-%m-%d"),
        today.strftime("%Y-%m-%d"),
    ]


def run(args) -> int:
    root = workspace_root(args.workspace)
    manifests_dir = root / MANIFESTS_SUBDIR
    manifests_dir.mkdir(parents=True, exist_ok=True)

    try:
        days = parse_days(args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_BAD_ARG
    days.sort()

    dest_root = Path(args.destination).expanduser().resolve()

    # NTFS warning (before we create anything so the drive root is intact)
    fs = detect_filesystem(dest_root)
    ntfs_warned = False
    if fs and fs.upper() != "NTFS":
        ntfs_warned = True
        bar = "!" * 72
        print(bar, file=sys.stderr)
        print("!!! WARNING: destination filesystem is NOT NTFS.", file=sys.stderr)
        print(f"!!! Detected: {fs}    Path: {dest_root}", file=sys.stderr)
        print("!!! docs/18 F3: do NOT use exFAT/FAT32 for cold archives", file=sys.stderr)
        print("!!!   (no journaling, mtime drift, silent corruption risk).", file=sys.stderr)
        print("!!! Continuing anyway - verify results carefully.", file=sys.stderr)
        print(bar, file=sys.stderr)

    # Make sure destination is usable.
    try:
        dest_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"ERROR: cannot create destination {dest_root}: {exc}",
              file=sys.stderr)
        return EXIT_DEST_UNUSABLE

    print(f"workspace:   {root}")
    print(f"destination: {dest_root}  (fs={fs or 'unknown'})")
    print(f"days:        {', '.join(days)}")
    if args.dry_run:
        print("mode:        DRY RUN (no writes)")

    # Enumerate + bucket by day
    src_files = enumerate_sources(root)
    by_day: dict[str, list[Path]] = {}
    for p in src_files:
        by_day.setdefault(day_of(p, root), []).append(p)

    cache = load_hash_cache(manifests_dir)
    summary: list[dict] = []
    overall_ok = True

    for day in days:
        files = sorted(by_day.get(day, []),
                       key=lambda p: p.relative_to(root).as_posix())
        if not files:
            print(f"[{day}] no source files for this day - skipped")
            summary.append({"day": day, "files": 0, "copied": 0,
                            "repaired": 0, "ok": 0, "failed": 0})
            continue

        entries: list[dict] = []
        copied = repaired = skipped = 0
        for src in files:
            rel = src.relative_to(root).as_posix()
            digest = cached_sha256(src, root, cache)
            entries.append({
                "sha256": digest,
                "relpath": rel,
                "bytes": src.stat().st_size,
            })
            if args.dry_run:
                continue
            outcome = sync_file(src, dest_root, root, digest)
            if outcome == "copied":
                copied += 1
            elif outcome == "repaired":
                repaired += 1
            else:
                skipped += 1

        if args.dry_run:
            total = len(entries)
            newish = total - skipped  # approximate; skipped only set when not dry
            print(f"[{day}] DRY RUN: {total} files in manifest; "
                  f"manifest and verification not written")
            summary.append({"day": day, "files": total, "copied": 0,
                            "repaired": 0, "ok": 0, "failed": 0})
            continue

        # Write hash-chained manifest
        prev_sha = previous_manifest_sha256(manifests_dir, day)
        manifest_path = write_manifest(manifests_dir, day, prev_sha, entries)

        # Verify on destination
        report = verify_day(dest_root, manifest_path)
        verified_path = manifests_dir / f"{day}.verified.json"
        verified_path.write_text(json.dumps(report, indent=2), "utf-8")

        status = "OK" if not report["failed"] else "FAILED"
        unchanged = skipped
        print(f"[{day}] files={len(entries)}  copied={copied}  "
              f"repaired={repaired}  unchanged={unchanged}  "
              f"verified={report['ok']}/{report['files']}  {status}")
        print(f"          manifest: {manifest_path}")
        print(f"          report:   {verified_path}")
        if report["failed"]:
            overall_ok = False
            for f in report["failed"][:10]:
                print(f"            - {f['relpath']}  ({f.get('reason', 'mismatch')})")
            if len(report["failed"]) > 10:
                print(f"            ... and "
                      f"{len(report['failed']) - 10} more")

        summary.append({
            "day": day,
            "files": len(entries),
            "copied": copied,
            "repaired": repaired,
            "ok": report["ok"],
            "failed": len(report["failed"]),
        })

    save_hash_cache(manifests_dir, cache)

    # Final summary
    tot_files = sum(s["files"] for s in summary)
    tot_copied = sum(s["copied"] for s in summary)
    tot_repaired = sum(s["repaired"] for s in summary)
    tot_ok = sum(s["ok"] for s in summary)
    tot_failed = sum(s["failed"] for s in summary)

    print("-" * 72)
    print("SUMMARY")
    print(f"  workspace:          {root}")
    print(f"  destination:        {dest_root}  (fs={fs or 'unknown'})")
    print(f"  days processed:     {len(summary)}")
    print(f"  files in manifests: {tot_files}")
    print(f"  files copied:       {tot_copied}")
    print(f"  files repaired:     {tot_repaired}")
    print(f"  files verified ok:  {tot_ok}")
    print(f"  files failed:       {tot_failed}")
    if ntfs_warned:
        print("  NTFS WARNING was issued above - consider reformatting "
              "the destination drive.")
    print("  RESULT: " + ("ALL VERIFIED" if overall_ok else "VERIFICATION FAILED"))
    return EXIT_OK if overall_ok else EXIT_VERIFY_FAILED


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="manifest_backup.py",
        description=(
            "Verified USB/cold backup for the vessel data twin. "
            "Content-addressed (sha256), hash-chained daily manifests, "
            "with on-disk verification of every copied file."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python scripts/manifest_backup.py E:\\boat-backup\n"
            "      Back up yesterday + today to E:\\boat-backup, verify, "
            "exit 0 on success.\n\n"
            "  python scripts/manifest_backup.py E:\\boat-backup --day 2026-07-19\n"
            "      Back up a single day only.\n\n"
            "  python scripts/manifest_backup.py E:\\boat-backup --dry-run\n"
            "      Show what would happen; write nothing.\n\n"
            "environment:\n"
            "  TZPRO_WORKSPACE   Override source workspace root\n"
            f"                    (default: {DEFAULT_WORKSPACE})\n\n"
            "exit codes:\n"
            f"  {EXIT_OK} = all files verified   "
            f"{EXIT_VERIFY_FAILED} = verification failed   "
            f"{EXIT_BAD_ARG} = bad arguments   "
            f"{EXIT_DEST_UNUSABLE} = destination unusable\n"
        ),
    )
    p.add_argument("destination",
                   help="Destination drive/dir, e.g. E:\\boat-backup")
    p.add_argument("--day", metavar="YYYY-MM-DD",
                   help="Back up a single day (default: yesterday and today)")
    p.add_argument("--workspace",
                   help="Override source workspace root (env: TZPRO_WORKSPACE)")
    p.add_argument("--dry-run", action="store_true",
                   help="Compute manifests and report; do not copy or write "
                        "manifest / verification files")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
