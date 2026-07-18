#!/usr/bin/env python3
"""_apply_p0_fixes.py — Apply three production-blocking reliability fixes.

Fixes:
  1. ALERT DEDUP: NO_ANALYSIS trigger_data uses stable "dir=<path>" key
     instead of volatile "age_min=<N>" so that re-fires across daemon
     cycles are correctly deduplicated.
  2. SHIP LOG RETRY: _post_to_ship_log() gets a retry loop (3 attempts,
     exponential back-off) so transient Worker errors don't lose alerts.
  3. ATOMIC JSON WRITE: capture_v3.py JSON and .md file writes use
     write-to-.tmp-then-rename to prevent readers from seeing a
     half-written file mid-capture.

Usage:
    python _apply_p0_fixes.py          # apply all fixes (dry-run first)
    python _apply_p0_fixes.py --apply  # actually write changes
    python _apply_p0_fixes.py --check  # verify fixes are applied
"""

import os
import re
import sys
import textwrap
from pathlib import Path

WORKSPACE = Path(__file__).parent.resolve()
ALERTS_PATH = WORKSPACE / "alerts.py"
CAPTURE_V3_PATH = WORKSPACE / "capture_v3.py"


# ═══════════════════════════════════════════════════════════════════
#  Fix 1: Stable NO_ANALYSIS trigger_data
# ═══════════════════════════════════════════════════════════════════

def _fix_stale_trigger_data(content: str) -> str:
    """Replace the volatile age_minutes key with a stable dir-based key."""

    # The pattern to find: the trigger_data line with age_min in it
    old = textwrap.dedent("""\
            trigger_data = (
                f"last_file={newest_path.name}|age_min={age_minutes:.0f}|"
                f"threshold={STALE_MINUTES}"
            )""")

    new = textwrap.dedent("""\
            # Stable trigger_data — uses dir path so same stale condition
            # deduplicates correctly across daemon cycles.
            trigger_data = (
                f"dir={cap_dir}|reason=stale|"
                f"threshold={STALE_MINUTES}"
            )""")

    if old not in content:
        # Try with different indentation (tabs vs spaces)
        alt_old = textwrap.dedent("""\
        trigger_data = (
            f"last_file={newest_path.name}|age_min={age_minutes:.0f}|"
            f"threshold={STALE_MINUTES}"
        )""")
        alt_new = textwrap.dedent("""\
        # Stable trigger_data — uses dir path so same stale condition
        # deduplicates correctly across daemon cycles.
        trigger_data = (
            f"dir={cap_dir}|reason=stale|"
            f"threshold={STALE_MINUTES}"
        )""")
        if alt_old in content:
            print("  [FIX 1] Found alt-indented NO_ANALYSIS trigger_data")
            return content.replace(alt_old, alt_new)

        print("  [FIX 1] WARNING: Could not find exact trigger_data pattern;"
              " searching with regex…")
        # Fallback: regex-based replacement
        pattern = re.compile(
            r'(trigger_data\s*=\s*\(\s*\n\s*)'
            r'f"last_file=\{newest_path\.name\}\|age_min=\{age_minutes:\.0f\}\|"\s*\n\s*'
            r'f"threshold=\{STALE_MINUTES\}"\s*\n\s*\)',
            re.MULTILINE,
        )
        match = pattern.search(content)
        if match:
            replacement = (
                '# Stable trigger_data\n'
                '            trigger_data = (\n'
                '                f"dir={cap_dir}|reason=stale|"\n'
                '                f"threshold={STALE_MINUTES}"\n'
                '            )'
            )
            content = pattern.sub(replacement, content)
            print("  [FIX 1] Applied via regex fallback")
            return content
        else:
            print("  [FIX 1] ERROR: Could not find pattern to replace!")
            return content

    print("  [FIX 1] Replaced age_min with dir-based trigger_data")
    return content.replace(old, new)


# ═══════════════════════════════════════════════════════════════════
#  Fix 2: Retry loop in Ship Log POST
# ═══════════════════════════════════════════════════════════════════

def _fix_ship_log_retry(content: str) -> str:
    """Add retry loop to _post_to_ship_log in alerts.py."""

    old_func = textwrap.dedent("""\
def _post_to_ship_log(
    alert_type: str,
    severity: str,
    message: str,
    details: dict,
) -> None:
    \"\"\"POST alert metadata to Ship Log Search for semantic browsing.\"\"\"
    try:
        payload = {
            "text": message,
            "category": "observation",
            "subcategory": "alert",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "alert_type": alert_type,
                "severity": severity,
                "trigger_data": details,
            },
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            SHIP_LOG_URL,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36"
                ),
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=SHIP_LOG_TIMEOUT_S)
        log.info("Alert posted to Ship Log: %s", alert_type)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        log.warning("Ship Log alert post failed (non-blocking): %s", e)""")

    new_func = textwrap.dedent("""\
def _post_to_ship_log(
    alert_type: str,
    severity: str,
    message: str,
    details: dict,
) -> None:
    \"\"\"POST alert metadata to Ship Log Search for semantic browsing.

    Retries up to 3 times with exponential back-off on transient failures.
    \"\"\"
    payload = {
        "text": message,
        "category": "observation",
        "subcategory": "alert",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": {
            "alert_type": alert_type,
            "severity": severity,
            "trigger_data": details,
        },
    }
    data = json.dumps(payload).encode("utf-8")

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(
                SHIP_LOG_URL,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36"
                    ),
                },
                method="POST",
            )
            urllib.request.urlopen(req, timeout=SHIP_LOG_TIMEOUT_S)
            log.info("Alert posted to Ship Log: %s", alert_type)
            return
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            if attempt < max_retries:
                backoff = 2 ** (attempt - 1)  # 1s, 2s, 4s
                log.warning(
                    "Ship Log POST attempt %d/%d failed: %s — retrying in %ds",
                    attempt, max_retries, e, backoff,
                )
                time.sleep(backoff)
            else:
                log.warning(
                    "Ship Log POST failed after %d attempts (non-blocking): %s",
                    max_retries, e,
                )""")

    if old_func in content:
        result = content.replace(old_func, new_func)
        print("  [FIX 2] Added retry loop to _post_to_ship_log")
        return result

    print("  [FIX 2] WARNING: Could not find _post_to_ship_log function")
    return content


# ═══════════════════════════════════════════════════════════════════
#  Fix 3: Atomic write for capture_v3.py JSON / MD
# ═══════════════════════════════════════════════════════════════════

def _fix_capture_atomic_writes(content: str) -> str:
    """Replace direct write_text calls with atomic .tmp → rename."""

    # --- JSON write ---
    old_json = 'saved.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")'

    new_json = textwrap.dedent("""\
        # Atomic write: write to .tmp first, then rename — prevents readers
        # from seeing a half-written file if the process crashes mid-write.
        _json_path = saved.with_suffix(".json")
        _json_tmp = _json_path.with_suffix(".json.tmp")
        _json_tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        _json_tmp.replace(_json_path)""")

    if old_json not in content:
        print("  [FIX 3] WARNING: JSON write_text line not found")
    else:
        content = content.replace(old_json, new_json)
        print("  [FIX 3] Atomic JSON write applied")

    # --- MD write ---
    old_md_line = 'saved.with_suffix(".md").write_text("\\n".join(md_lines), encoding="utf-8")'

    new_md_block = textwrap.dedent("""\
        # Atomic write for markdown
        _md_path = saved.with_suffix(".md")
        _md_tmp = _md_path.with_suffix(".md.tmp")
        _md_tmp.write_text("\\n".join(md_lines), encoding="utf-8")
        _md_tmp.replace(_md_path)""")

    if old_md_line not in content:
        print("  [FIX 3] WARNING: MD write_text line not found")
    else:
        content = content.replace(old_md_line, new_md_block)
        print("  [FIX 3] Atomic MD write applied")

    return content


# ═══════════════════════════════════════════════════════════════════
#  Driver
# ═══════════════════════════════════════════════════════════════════

def apply_fixes(dry_run: bool = True):
    """Apply all three fixes. dry_run=True only prints what would change."""
    fixes_applied = 0

    # ── alerts.py ──────────────────────────────────────────────────
    if ALERTS_PATH.exists():
        content = ALERTS_PATH.read_text(encoding="utf-8")
        original = content

        content = _fix_stale_trigger_data(content)
        content = _fix_ship_log_retry(content)

        if content != original:
            fixes_applied += 1
            if not dry_run:
                ALERTS_PATH.write_text(content, encoding="utf-8")
                print("  [OK] Wrote alerts.py")
            else:
                print("  [DRY RUN] Would write alerts.py")
        else:
            print("  No changes to alerts.py")
    else:
        print(f"  ERROR: {ALERTS_PATH} not found!")

    # ── capture_v3.py ──────────────────────────────────────────────
    if CAPTURE_V3_PATH.exists():
        content = CAPTURE_V3_PATH.read_text(encoding="utf-8")
        original = content

        content = _fix_capture_atomic_writes(content)

        if content != original:
            fixes_applied += 1
            if not dry_run:
                CAPTURE_V3_PATH.write_text(content, encoding="utf-8")
                print("  [OK] Wrote capture_v3.py")
            else:
                print("  [DRY RUN] Would write capture_v3.py")
        else:
            print("  No changes to capture_v3.py")
    else:
        print(f"  ERROR: {CAPTURE_V3_PATH} not found!")

    return fixes_applied


def check_fixes():
    """Verify all three fixes are present in the source files."""
    all_ok = True

    print("=== Checking alerts.py ===")
    if ALERTS_PATH.exists():
        content = ALERTS_PATH.read_text(encoding="utf-8")

        # Check 1: No age_min in trigger_data
        if 'age_min=' in content:
            print("  ✗ FAIL: trigger_data still contains age_min=")
            all_ok = False
        elif 'dir=' in content and 'reason=stale' in content:
            print("  ✓ PASS: stable dir-based trigger_data present")
        else:
            print("  ? UNKNOWN: need manual review of trigger_data")

        # Check 2: Retry loop
        if 'max_retries' in content:
            print("  ✓ PASS: retry loop present in _post_to_ship_log")
        else:
            print("  ✗ FAIL: no retry loop in _post_to_ship_log")
            all_ok = False
    else:
        print("  ✗ alerts.py not found!")

    print("=== Checking capture_v3.py ===")
    if CAPTURE_V3_PATH.exists():
        content = CAPTURE_V3_PATH.read_text(encoding="utf-8")

        # Check 3: Atomic JSON write
        if '.json.tmp' in content or '_json_tmp' in content:
            print("  ✓ PASS: atomic JSON write present")
        else:
            print("  ✗ FAIL: no atomic JSON write")
            all_ok = False

        # Check 3b: Atomic MD write
        if '.md.tmp' in content or '_md_tmp' in content:
            print("  ✓ PASS: atomic MD write present")
        else:
            print("  ✗ FAIL: no atomic MD write")
            all_ok = False
    else:
        print("  ✗ capture_v3.py not found!")

    if all_ok:
        print("\n✓ All fixes verified.")
        return 0
    else:
        print("\n✗ Some fixes not applied. Run --apply first.")
        return 1


def main():
    if len(sys.argv) < 2 or "--help" in sys.argv:
        print(__doc__)
        print("Modes: --check | --apply")
        return 0

    if "--check" in sys.argv:
        return check_fixes()

    dry_run = "--apply" not in sys.argv
    if dry_run:
        print("=== DRY RUN (--apply not specified) ===\n")

    print(f"Processing: {WORKSPACE}")
    print(f"  alerts.py:  {ALERTS_PATH}")
    print(f"  capture_v3: {CAPTURE_V3_PATH}\n")

    fixes = apply_fixes(dry_run=dry_run)

    print(f"\n=== {'Dry run complete' if dry_run else 'Fix applied'} "
          f"({fixes} file(s) changed) ===")

    if dry_run and fixes > 0:
        print("Run with --apply to write changes to disk.")


if __name__ == "__main__":
    sys.exit(main())
