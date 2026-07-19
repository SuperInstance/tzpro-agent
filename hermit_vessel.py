#!/usr/bin/env python3
"""
hermit_vessel.py — I2I Vessel Bridge between tzpro-agent and Hermit

The Hermit notebook (formerly A2A-native-notebookLM) is the fleet's cognitive
command center. This module connects tzpro-agent (EILEEN's fishing intelligence)
as a first-class fleet data source via the I2I bottle protocol.

Architecture:
    tzpro-agent ──[I2I bottles]──> hermit/.vessel/incoming/
    tzpro-agent <──[I2I bottles]── hermit/.vessel/outgoing/

Bottle types: I2I:BOTTLE, I2I:SYNTHESIS, I2I:ACK, I2I:CHALLENGE,
              I2I:CHECKPOINT, I2I:OBSERVATION, I2I:QUERY, I2I:RESPONSE, I2I:ALERT

Usage:
    python hermit_vessel.py              # Full vessel launch
    python hermit_vessel.py --status     # Check connection status
    python hermit_vessel.py --send-query "What fish species in today's captures?"
    python hermit_vessel.py --ingest-captures --limit 10  # Send captures to Hermit
"""

import json
import os
import sys
import uuid
import sqlite3
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any


# ── Paths ────────────────────────────────────────────────────────────────────

HERE = Path(__file__).parent.resolve()
WORKSPACE = HERE.parent
HERMIT_REPO = WORKSPACE / "hermit"
VESSEL_DIR = HERE / ".vessel"
BOTTLES_IN = VESSEL_DIR / "bottles" / "incoming"
BOTTLES_OUT = VESSEL_DIR / "bottles" / "outgoing"
VESSEL_CONFIG = VESSEL_DIR / "config.json"
CAPTURES_DB = HERE / "captures.db"


# ── Identity ─────────────────────────────────────────────────────────────────

VESSEL_IDENTITY = {
    "name": "tzpro-agent",
    "display_name": "TZPro Agent — F/V EILEEN Fishing Intelligence",
    "version": "2.0.0",
    "agent_type": "fishing-intelligence",
    "host_vessel": "F/V EILEEN",
    "homeport": "Southeast Alaska",
    "description": (
        "Real-time fishing vessel intelligence: OCR capture pipeline, "
        "species classification, tide-aware memory, bathymetric analysis, "
        "multi-model consensus, and fleet communication."
    ),
}


# ── Bottle Protocol ──────────────────────────────────────────────────────────

BOTTLE_TYPES = {
    "I2I:BOTTLE": "Raw query, task, or notification",
    "I2I:SYNTHESIS": "Combined findings from multiple agents/models",
    "I2I:ACK": "Handshake or progress acknowledgment",
    "I2I:CHALLENGE": "Disagreement or reconsideration request",
    "I2I:CHECKPOINT": "State snapshot for pause/resume",
    "I2I:OBSERVATION": "Sensor/capture data from vessel instruments",
    "I2I:QUERY": "Research question for the cognitive command center",
    "I2I:RESPONSE": "Answer to a query",
    "I2I:ALERT": "Urgent notification requiring attention",
}


def make_bottle_id(prefix: str = "bottle") -> str:
    """Generate a unique bottle ID with timestamp and short UUID."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short_id = uuid.uuid4().hex[:8]
    return f"{prefix}-{ts}-{short_id}"


def make_bottle(
    recipient: str,
    bottle_type: str,
    payload: dict,
    context: Optional[dict] = None,
    requires_ack: bool = False,
) -> dict:
    """Create a well-formed I2I bottle."""
    if bottle_type not in BOTTLE_TYPES:
        raise ValueError(
            f"Unknown bottle type: {bottle_type}. "
            f"Use one of: {list(BOTTLE_TYPES.keys())}"
        )

    bottle_id = make_bottle_id(bottle_type.replace(":", "-").lower())
    return {
        "bottle": {
            "id": bottle_id,
            "sender": "tzpro-agent",
            "recipient": recipient,
            "type": bottle_type,
            "payload": payload,
            "context": context or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "signature": "tzpro-agent@eileen",
        "routing": {
            "direction": "outgoing",
            "target_cortex": "../hermit/CORTEX.json",
            "requires_ack": requires_ack,
        },
    }


def write_bottle(bottle: dict, target_dir: Path) -> Path:
    """Write a bottle to a vessel directory."""
    target_dir.mkdir(parents=True, exist_ok=True)
    bottle_type = bottle["bottle"]["type"].replace(":", "_")
    bottle_id = bottle["bottle"]["id"]
    filename = f"{bottle_type}_{bottle_id}.json"
    filepath = target_dir / filename
    filepath.write_text(
        json.dumps(bottle, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return filepath


# ── HermitVessel Class ───────────────────────────────────────────────────────

class HermitVessel:
    """
    Bridge between tzpro-agent and Hermit cognitive command center.

    Handles bottle creation, vessel directory management, and capture
    data serialization for the I2I protocol.
    """

    def __init__(self):
        self.cortex: Optional[dict] = None
        self._ensure_dirs()

    def _ensure_dirs(self):
        """Create vessel directory structure if it doesn't exist."""
        BOTTLES_IN.mkdir(parents=True, exist_ok=True)
        BOTTLES_OUT.mkdir(parents=True, exist_ok=True)

    # ── Cortex Discovery ─────────────────────────────────────────────────

    def discover_hermit(self) -> dict:
        """
        Read Hermit's CORTEX.json to discover its identity and capabilities.

        Returns the parsed CORTEX manifest or raises FileNotFoundError.
        """
        cortex_path = HERMIT_REPO / "CORTEX.json"
        if not cortex_path.exists():
            raise FileNotFoundError(
                f"Hermit CORTEX not found at {cortex_path}. "
                f"Is the hermit repo cloned at {HERMIT_REPO}?"
            )
        self.cortex = json.loads(cortex_path.read_text(encoding="utf-8"))
        return self.cortex

    def hermit_identity(self) -> dict:
        """Get Hermit's identity block from its CORTEX manifest."""
        if not self.cortex:
            self.discover_hermit()
        return self.cortex.get("identity", {})

    def hermit_capabilities(self) -> list:
        """Get Hermit's declared capabilities."""
        if not self.cortex:
            self.discover_hermit()
        return self.cortex.get("capabilities", [])

    def is_hermit_available(self) -> bool:
        """Check if the Hermit repo exists and has a CORTEX manifest."""
        return (HERMIT_REPO / "CORTEX.json").exists()

    # ── Bottle Operations ────────────────────────────────────────────────

    def send_bottle(
        self,
        recipient: str = "hermit",
        bottle_type: str = "I2I:BOTTLE",
        payload: Optional[dict] = None,
        context: Optional[dict] = None,
        requires_ack: bool = False,
    ) -> Path:
        """
        Create and write a bottle to the outgoing directory.

        Args:
            recipient: Target agent name (default: "hermit")
            bottle_type: I2I bottle type string
            payload: Bottle-specific data payload
            context: Fleet metadata context
            requires_ack: Whether this bottle requires acknowledgment

        Returns:
            Path to the written bottle file
        """
        bottle = make_bottle(
            recipient=recipient,
            bottle_type=bottle_type,
            payload=payload or {},
            context=context or {"fleet": "tzpro-hermit-dual-instance"},
            requires_ack=requires_ack,
        )
        return write_bottle(bottle, BOTTLES_OUT)

    def send_ack(self, message: str, extra: Optional[dict] = None) -> Path:
        """Send an I2I:ACK acknowledgment bottle."""
        payload = {"message": message}
        if extra:
            payload.update(extra)
        return self.send_bottle(
            bottle_type="I2I:ACK",
            payload=payload,
            requires_ack=False,
        )

    def send_query(self, query: str, filters: Optional[dict] = None) -> Path:
        """Send an I2I:QUERY research question to Hermit."""
        return self.send_bottle(
            bottle_type="I2I:QUERY",
            payload={
                "query": query,
                "filters": filters or {},
            },
            requires_ack=True,
        )

    def send_observation(self, observation: dict) -> Path:
        """Send an I2I:OBSERVATION (sensor/capture data) to Hermit."""
        return self.send_bottle(
            bottle_type="I2I:OBSERVATION",
            payload=observation,
            requires_ack=False,
        )

    def send_synthesis(self, synthesis: dict) -> Path:
        """Send an I2I:SYNTHESIS (consensus/multi-model result)."""
        return self.send_bottle(
            bottle_type="I2I:SYNTHESIS",
            payload=synthesis,
            requires_ack=False,
        )

    def send_alert(self, alert: dict) -> Path:
        """Send an I2I:ALERT (urgent notification)."""
        return self.send_bottle(
            bottle_type="I2I:ALERT",
            payload=alert,
            requires_ack=True,
        )

    def send_checkpoint(self, state: dict) -> Path:
        """Send an I2I:CHECKPOINT (state snapshot)."""
        return self.send_bottle(
            bottle_type="I2I:CHECKPOINT",
            payload=state,
            requires_ack=False,
        )

    # ── Bottle Reception ─────────────────────────────────────────────────

    def read_incoming(self) -> list[dict]:
        """Read all incoming bottles from Hermit."""
        bottles = []
        if BOTTLES_IN.exists():
            for f in sorted(BOTTLES_IN.glob("*.json")):
                try:
                    bottles.append(json.loads(f.read_text(encoding="utf-8")))
                except json.JSONDecodeError:
                    pass
        return bottles

    def read_latest_incoming(self) -> Optional[dict]:
        """Read the most recent incoming bottle."""
        bottles = self.read_incoming()
        return bottles[-1] if bottles else None

    # ── Vessel Identity ──────────────────────────────────────────────────

    def write_vessel_identity(self) -> Path:
        """Write the .vessel/config.json identity manifest."""
        VESSEL_CONFIG.parent.mkdir(parents=True, exist_ok=True)

        config = {
            "api_version": "v2.1",
            "vessel": VESSEL_IDENTITY,
            "capabilities": [
                {"name": "screen-capture", "version": "3.0"},
                {"name": "species-classification", "version": "2.0"},
                {"name": "tide-aware-memory", "version": "1.0"},
                {"name": "bathymetric-analysis", "version": "1.0"},
                {"name": "multi-model-consensus", "version": "2.0"},
                {"name": "catch-logging", "version": "2.0"},
                {"name": "fleet-monitor", "version": "1.0"},
                {"name": "i2i-chat", "version": "2.1"},
                {"name": "anomaly-detection", "version": "1.0"},
            ],
            "i2i_protocol": {
                "version": "2.1",
                "bottle_dir": ".vessel/bottles",
                "supported_types": list(BOTTLE_TYPES.keys()),
                "transport": "filesystem",
                "poll_interval_ms": 2000,
            },
            "endpoints": {
                "cortex": ".vessel/config.json",
                "bottle_ingress": ".vessel/bottles/incoming/",
                "bottle_egress": ".vessel/bottles/outgoing/",
            },
            "fleet_peers": [
                {
                    "name": "hermit",
                    "path": "../hermit",
                    "role": "cognitive-command-center",
                    "cortex": "../hermit/CORTEX.json",
                }
            ],
        }

        VESSEL_CONFIG.write_text(
            json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return VESSEL_CONFIG

    # ── Capture Data Ingestion ───────────────────────────────────────────

    def _get_captures_db(self) -> sqlite3.Connection:
        """Open the captures database."""
        if not CAPTURES_DB.exists():
            raise FileNotFoundError(
                f"Captures database not found at {CAPTURES_DB}. "
                "Ensure the OCR capture pipeline has been running."
            )
        conn = sqlite3.connect(str(CAPTURES_DB))
        conn.row_factory = sqlite3.Row
        return conn

    def get_recent_captures(self, limit: int = 5) -> list[dict]:
        """
        Get recent capture records from the database.

        The captures table stores sounder capture metadata: GPS position,
        depth readings, blob counts, bottom classification, and timestamps.

        Returns a list of capture dictionaries suitable for I2I bottles.
        """
        conn = self._get_captures_db()
        try:
            cursor = conn.execute(
                """
                SELECT capture_id, ts_utc, ts_local, lat, lon,
                       sog_kts, cog_deg, depth_max_fm, schema_version,
                       mid_zone_mean, mid_zone_peak, blob_count,
                       thermocline_count, bottom_depth_fm, bottom_confidence,
                       caption, day_folder, analyzed_at, file_size_bytes
                FROM captures
                ORDER BY ts_utc DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            captures = []
            for row in rows:
                captures.append({
                    "capture_id": row[0],
                    "ts_utc": row[1],
                    "ts_local": row[2],
                    "lat": row[3],
                    "lon": row[4],
                    "sog_kts": row[5],
                    "cog_deg": row[6],
                    "depth_max_fm": row[7],
                    "schema_version": row[8],
                    "mid_zone_mean": row[9],
                    "mid_zone_peak": row[10],
                    "blob_count": row[11],
                    "thermocline_count": row[12],
                    "bottom_depth_fm": row[13],
                    "bottom_confidence": row[14],
                    "caption": row[15],
                    "day_folder": row[16],
                    "analyzed_at": row[17],
                    "file_size_bytes": row[18],
                })
            return captures
        finally:
            conn.close()

    def get_capture_stats(self) -> dict:
        """Get aggregate capture statistics across time windows."""
        conn = self._get_captures_db()
        try:
            stats = {}

            # Total captures
            cursor = conn.execute("SELECT COUNT(*) FROM captures")
            row = cursor.fetchone()
            if row:
                stats["total_captures"] = row[0]

            # Today's captures
            cursor = conn.execute(
                """
                SELECT COUNT(*) FROM captures
                WHERE date(ts_local) = date('now', 'localtime')
                """
            )
            row = cursor.fetchone()
            if row:
                stats["captures_today"] = row[0]

            # Depth distribution
            cursor = conn.execute(
                """
                SELECT
                    ROUND(AVG(bottom_depth_fm), 1) as avg_depth,
                    MIN(bottom_depth_fm) as min_depth,
                    MAX(bottom_depth_fm) as max_depth,
                    ROUND(AVG(blob_count), 1) as avg_blobs,
                    MAX(blob_count) as max_blobs
                FROM captures
                """
            )
            row = cursor.fetchone()
            if row:
                stats["depth_stats"] = {
                    "avg_fm": row[0],
                    "min_fm": row[1],
                    "max_fm": row[2],
                }
                stats["blob_stats"] = {
                    "avg_per_capture": row[3],
                    "max_in_capture": row[4],
                }

            # Bottom confidence distribution
            cursor = conn.execute(
                """
                SELECT bottom_confidence, COUNT(*) as count
                FROM captures
                WHERE bottom_confidence IS NOT NULL
                GROUP BY bottom_confidence
                ORDER BY count DESC
                """
            )
            rows = cursor.fetchall()
            if rows:
                stats["bottom_types"] = {r[0]: r[1] for r in rows}

            return stats
        finally:
            conn.close()

    def capture_to_observation(self, capture: dict) -> dict:
        """
        Convert a capture DB row into an I2I:OBSERVATION payload.

        The captures table stores sounder capture metadata from the OCR
        pipeline: GPS position, depth, blob counts, bottom classification.
        Standardizes for consumption by Hermit's research workflows.
        """
        return {
            "source": "tzpro-agent-sounder-capture",
            "capture_id": capture.get("capture_id"),
            "timestamp_utc": capture.get("ts_utc"),
            "position": {
                "lat": capture.get("lat"),
                "lon": capture.get("lon"),
                "sog_kts": capture.get("sog_kts"),
                "cog_deg": capture.get("cog_deg"),
            },
            "depth": {
                "max_fm": capture.get("depth_max_fm"),
                "bottom_depth_fm": capture.get("bottom_depth_fm"),
                "bottom_confidence": capture.get("bottom_confidence"),
            },
            "sounder_returns": {
                "blob_count": capture.get("blob_count"),
                "mid_zone_mean": capture.get("mid_zone_mean"),
                "mid_zone_peak": capture.get("mid_zone_peak"),
                "thermocline_count": capture.get("thermocline_count"),
            },
            "metadata": {
                "caption": capture.get("caption"),
                "day_folder": capture.get("day_folder"),
                "schema_version": capture.get("schema_version"),
                "file_size_bytes": capture.get("file_size_bytes"),
                "analyzed_at": capture.get("analyzed_at"),
            },
        }

    def ingest_captures(
        self, limit: int = 5, send_as: str = "I2I:OBSERVATION"
    ) -> list[Path]:
        """
        Read recent captures from the database and send them as I2I bottles.

        Args:
            limit: Maximum number of captures to send
            send_as: Bottle type to use (default: I2I:OBSERVATION)

        Returns:
            List of Paths to the written bottle files
        """
        captures = self.get_recent_captures(limit)
        paths = []

        for cap in captures:
            observation = self.capture_to_observation(cap)
            bottle_path = self.send_bottle(
                bottle_type=send_as,
                payload=observation,
                context={
                    "fleet": "tzpro-hermit-dual-instance",
                    "data_source": "captures.db",
                    "pipeline": "ocr-capture-v3",
                },
            )
            paths.append(bottle_path)

        return paths

    # ── Status ───────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return comprehensive vessel connection status."""
        status = {
            "vessel": VESSEL_IDENTITY["name"],
            "version": VESSEL_IDENTITY["version"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "hermit_available": self.is_hermit_available(),
            "vessel_config": VESSEL_CONFIG.exists(),
            "outgoing_bottles": (
                len(list(BOTTLES_OUT.glob("*.json")))
                if BOTTLES_OUT.exists()
                else 0
            ),
            "incoming_bottles": (
                len(list(BOTTLES_IN.glob("*.json")))
                if BOTTLES_IN.exists()
                else 0
            ),
            "captures_db": CAPTURES_DB.exists(),
        }

        if status["hermit_available"]:
            try:
                self.discover_hermit()
                status["hermit_identity"] = self.hermit_identity()
                status["hermit_capabilities"] = [
                    c["name"] for c in self.hermit_capabilities()
                ]
            except Exception as e:
                status["hermit_error"] = str(e)

        if status["captures_db"]:
            try:
                status["capture_stats"] = self.get_capture_stats()
            except Exception as e:
                status["capture_stats_error"] = str(e)

        return status

    # ── Vessel Launch ────────────────────────────────────────────────────

    def launch(self, ingest_captures: bool = True) -> dict:
        """
        Full vessel launch sequence.

        1. Discover Hermit's CORTEX manifest
        2. Write tzpro-agent's vessel identity config
        3. Send handshake ACK bottle to Hermit
        4. Optionally ingest recent captures as observation bottles
        5. Return launch report

        Returns:
            Launch report dict with paths and status
        """
        report = {
            "operation": "vessel_launch",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "vessel": VESSEL_IDENTITY["name"],
            "steps": [],
        }

        # Step 1: Discover Hermit
        try:
            cortex = self.discover_hermit()
            report["steps"].append({
                "step": "discover_hermit",
                "status": "ok",
                "hermit_name": cortex["identity"]["name"],
                "hermit_version": cortex["identity"]["version"],
            })
        except FileNotFoundError as e:
            report["steps"].append({
                "step": "discover_hermit",
                "status": "warning",
                "message": str(e),
            })

        # Step 2: Write vessel identity
        config_path = self.write_vessel_identity()
        report["steps"].append({
            "step": "write_vessel_identity",
            "status": "ok",
            "path": str(config_path),
        })

        # Step 3: Send handshake ACK
        ack_path = self.send_ack(
            message="VESSEL LAUNCH: tzpro-agent online and connected to Hermit fleet",
            extra={
                "sender_identity": VESSEL_IDENTITY,
                "memory_architecture": "tide_pool → stipes → holdfast",
                "data_sources": [
                    "Garmin sounder captures (OCR pipeline v3)",
                    "TZ Pro navigation display captures",
                    "GPS/NMEA position stream",
                    "Catch logs with species/gear/depth correlation",
                ],
                "handshake_token": make_bottle_id("handshake"),
            },
        )
        report["steps"].append({
            "step": "send_handshake_ack",
            "status": "ok",
            "bottle_path": str(ack_path),
        })

        # Step 4: Ingest recent captures
        if ingest_captures:
            try:
                capture_paths = self.ingest_captures(limit=5)
                report["steps"].append({
                    "step": "ingest_captures",
                    "status": "ok",
                    "count": len(capture_paths),
                    "bottle_paths": [str(p) for p in capture_paths],
                })
            except FileNotFoundError as e:
                report["steps"].append({
                    "step": "ingest_captures",
                    "status": "skipped",
                    "message": str(e),
                })
            except Exception as e:
                report["steps"].append({
                    "step": "ingest_captures",
                    "status": "error",
                    "message": str(e),
                })

        # Summary
        all_ok = all(s["status"] in ("ok", "skipped") for s in report["steps"])
        report["launch_successful"] = all_ok

        return report


# ── CLI ──────────────────────────────────────────────────────────────────────

def print_launch_report(report: dict):
    """Pretty-print a launch report."""
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  🦀  HERMIT VESSEL LAUNCH                               ║")
    print("╠══════════════════════════════════════════════════════════╣")
    print(f"║  Vessel:  {report['vessel']:<46s}║")
    print(f"║  Status:  {'SUCCESS' if report['launch_successful'] else 'WARNING':<46s}║")
    print("╠══════════════════════════════════════════════════════════╣")
    for step in report["steps"]:
        icon = {"ok": "✅", "warning": "⚠️", "error": "❌", "skipped": "⏭️"}.get(
            step["status"], "  "
        )
        step_name = step["step"].replace("_", " ").title()
        print(f"║  {icon} {step_name:<48s}║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    if report["launch_successful"]:
        print("The Hermit vessel is online. 🦀")
        print(f"  Bottles will flow to: hermit/.vessel/incoming/")
        print(f"  Responses arrive at:  tzpro-agent/.vessel/bottles/incoming/")
        print()
        print("Next: Start Hermit's beachcomber poller to process incoming bottles.")
        print("  cd ../hermit && docker-compose up -d")
    else:
        print("Some steps had issues. See report above for details.")


def main():
    vessel = HermitVessel()

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "--status" or cmd == "-s":
            status = vessel.status()
            print(json.dumps(status, indent=2, default=str))
            return

        if cmd == "--send-query" and len(sys.argv) > 2:
            query = " ".join(sys.argv[2:])
            path = vessel.send_query(query)
            print(f"Query sent: {path}")
            print(f"Bottle ID: {path.stem}")
            return

        if cmd == "--ingest-captures":
            limit = 5
            if len(sys.argv) > 2 and sys.argv[2] == "--limit":
                limit = int(sys.argv[3]) if len(sys.argv) > 3 else 5
            paths = vessel.ingest_captures(limit=limit)
            print(f"Sent {len(paths)} capture observation bottles:")
            for p in paths:
                print(f"  {p}")
            return

        if cmd == "--read-incoming":
            bottles = vessel.read_incoming()
            if bottles:
                for b in bottles:
                    print(json.dumps(b, indent=2, default=str))
                    print("---")
            else:
                print("No incoming bottles.")
            return

        if cmd == "--help" or cmd == "-h":
            print(__doc__)
            print("Commands:")
            print("  (none)              Full vessel launch")
            print("  --status, -s        Check connection status")
            print("  --send-query <q>    Send a research query to Hermit")
            print("  --ingest-captures   Send recent captures as observations")
            print("  --read-incoming     Read bottles from Hermit")
            print("  --help, -h          Show this help")
            return

        print(f"Unknown command: {cmd}")
        print("Use --help for available commands.")
        return

    # Default: full launch
    try:
        report = vessel.launch(ingest_captures=True)
        print_launch_report(report)

        # Also dump full report as JSON for programmatic consumption
        report_path = HERE / ".launch_report.json"
        report_path.write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )
        print(f"Full launch report saved to: {report_path}")

    except Exception as e:
        print(f"\n❌ Launch failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
