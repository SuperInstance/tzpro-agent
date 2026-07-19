# 🦀 BOOT HERMIT — Vessel Launch Procedures

> *"The hermit crab doesn't own the shell. It moves into whichever repo needs it."*

This document covers booting the Hermit vessel (formerly A2A-native-notebookLM) and connecting tzpro-agent as a data source via the I2I bottle protocol.

---

## Quick Start

### Prerequisites

- Python 3.11+ (Hermit runs FastAPI + LangGraph)
- Node.js 18+ (Hermit's Next.js frontend — optional for headless mode)
- SurrealDB (or Docker for the DB container)
- tzpro-agent workspace at `C:\Users\casey\.openclaw\workspace\tzpro-agent`
- Hermit workspace at `C:\Users\casey\.openclaw\workspace\hermit`

### 1. Boot Hermit (Cognitive Command Center)

```powershell
# Option A: Docker (recommended for full stack)
cd C:\Users\casey\.openclaw\workspace\hermit
docker-compose up -d

# Option B: Headless (API only, no frontend)
cd C:\Users\casey\.openclaw\workspace\hermit
pip install -e .
python run_api.py
```

Hermit starts on `http://localhost:8000`. Verify:

```powershell
curl http://localhost:8000/.well-known/cortex.json
```

Should return the CORTEX manifest declaring identity and capabilities.

### 2. Connect tzpro-agent as a Data Source

```powershell
cd C:\Users\casey\.openclaw\workspace\tzpro-agent
python hermit_vessel.py
```

This script:
1. Reads Hermit's `CORTEX.json` to understand vessel identity
2. Creates the `.vessel/` directory structure in tzpro-agent
3. Writes a vessel identity bottle describing tzpro-agent's capabilities
4. Sends an I2I:ACK handshake bottle to Hermit
5. Sends a first capture analysis bottle to seed the connection

### 3. Verify the Connection

Check that the bottle was delivered:

```powershell
# Check outgoing bottles from tzpro-agent
ls C:\Users\casey\.openclaw\workspace\tzpro-agent\.vessel\bottles\outgoing\

# Check if Hermit picked it up (it moves processed bottles)
ls C:\Users\casey\.openclaw\workspace\hermit\.vessel\incoming\
```

If Hermit's `beachcomber` poller is running, it will detect the new bottle within 2 seconds and process it.

---

## The I2I Protocol in Detail

### Bottle Format

Every bottle is a JSON file following this schema:

```json
{
  "bottle": {
    "id": "unique-bottle-id",
    "sender": "tzpro-agent",
    "recipient": "hermit",
    "type": "I2I:BOTTLE | I2I:SYNTHESIS | I2I:ACK | I2I:CHALLENGE | I2I:CHECKPOINT | I2I:OBSERVATION | I2I:QUERY",
    "payload": { /* type-specific data */ },
    "context": { /* fleet metadata */ },
    "timestamp": "ISO-8601 UTC"
  },
  "signature": "sender@vessel",
  "routing": {
    "direction": "outgoing | incoming",
    "target_cortex": "../hermit/CORTEX.json",
    "requires_ack": true | false
  }
}
```

### Bottle Types

| Type | Purpose | Example |
|---|---|---|
| `I2I:BOTTLE` | Raw query or notification | "What species are in this sounder capture?" |
| `I2I:SYNTHESIS` | Combined findings from multiple agents | Consensus vote on species ID |
| `I2I:ACK` | Handshake acknowledgment | Vessel launch acknowledgment |
| `I2I:CHALLENGE` | Disagreement or reconsideration | "Kimi disagrees with Claude's species ID" |
| `I2I:CHECKPOINT` | State snapshot for pause/resume | Memory state at end of fishing trip |
| `I2I:OBSERVATION` | Sensor/capture data | OCR result from Garmin display |
| `I2I:QUERY` | Research question for Hermit | "Analyze catch patterns by tide phase" |
| `I2I:RESPONSE` | Answer to a query | Hermit's research results |
| `I2I:ALERT` | Urgent notification | "Anomalous GPS track detected" |

### File-Based Transport

Bottles are JSON files written to `.vessel/bottles/` directories:

```
tzpro-agent/.vessel/bottles/
├── incoming/    ← Hermit drops responses here
└── outgoing/    ← tzpro-agent drops queries here

hermit/.vessel/
├── incoming/    ← tzpro-agent bottles land here
└── outgoing/    ← Hermit drops responses here
```

**Why files?** They survive reboots. They're version-controllable. They require zero infrastructure. An agent with `touch` and `cat` is a full participant.

---

## Sending Your First Bottle

### Manual Bottle (for testing)

```powershell
# Write a query bottle directly
@"
{
  "bottle": {
    "id": "bottle-test-$(Get-Date -Format 'yyyyMMddHHmmss')",
    "sender": "tzpro-agent",
    "recipient": "hermit",
    "type": "I2I:QUERY",
    "payload": {
      "query": "Analyze the most common fish species seen in EILEEN's sounder captures this week",
      "context_window": "7d",
      "priority": "normal"
    },
    "context": {
      "vessel": "F/V EILEEN",
      "data_source": "captures.db",
      "record_count": 1247
    },
    "timestamp": "$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ssZ')"
  },
  "signature": "tzpro-agent@eileen",
  "routing": {
    "direction": "outgoing",
    "requires_ack": true
  }
}
"@ | Out-File -FilePath ".vessel\bottles\outgoing\I2I_QUERY_bottle-test.json" -Encoding utf8
```

### Python (using hermit_vessel.py)

```python
from hermit_vessel import HermitVessel

vessel = HermitVessel()

# Send a query
vessel.send_bottle(
    recipient="hermit",
    bottle_type="I2I:QUERY",
    payload={
        "query": "What patterns correlate with successful halibut sets?",
        "filters": {"species": "halibut", "lookback_days": 30}
    }
)

# Send a synthesis (multi-model consensus result)
vessel.send_bottle(
    recipient="hermit",
    bottle_type="I2I:SYNTHESIS",
    payload={
        "consensus": {
            "species": "chum_salmon",
            "confidence": 0.87,
            "models": ["kimi", "claude", "deepseek"],
            "votes": {"chum_salmon": 2, "pink_salmon": 1}
        },
        "raw_capture_ref": "capture_20260718_140522.png"
    }
)
```

---

## What to Expect

### Normal Operation Flow

```
tzpro-agent                    Hermit
    │                              │
    │── I2I:QUERY ────────────────→│  "Analyze this sounder capture"
    │                              │
    │                              │  LangGraph processes query
    │                              │  (strategy → search → synthesize)
    │                              │
    │←── I2I:RESPONSE ────────────│  "Species: chum salmon (87%)"
    │                              │
    │── I2I:ACK ─────────────────→│  "Received, logging for correlation"
```

### Troubleshooting

| Symptom | Check |
|---|---|
| Bottle not picked up | Is Hermit's `beachcomber` poller running? Check `docker ps` |
| Bottle format error | Validate JSON schema against bottle format above |
| No response | Check `.vessel/bottles/incoming/` in tzpro-agent |
| Duplicate bottles | Bottle IDs should be unique; use timestamps in IDs |
| SurrealDB not ready | `docker-compose logs surreal` |

### Manual Verification Commands

```powershell
# Check all vessel directories
ls C:\Users\casey\.openclaw\workspace\tzpro-agent\.vessel\bottles\outgoing\
ls C:\Users\casey\.openclaw\workspace\tzpro-agent\.vessel\bottles\incoming\
ls C:\Users\casey\.openclaw\workspace\hermit\.vessel\incoming\
ls C:\Users\casey\.openclaw\workspace\hermit\.vessel\outgoing\

# Read the latest bottle
$latest = Get-ChildItem .vessel\bottles\outgoing\ | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Get-Content $latest.FullName | ConvertFrom-Json | ConvertTo-Json -Depth 10
```

---

## Architecture: How It All Fits

```
┌─────────────────────────────────────────────────────────┐
│                     THE FLEET                            │
│                                                          │
│  ┌──────────────────┐       ┌──────────────────────────┐│
│  │   tzpro-agent    │ I2I   │       hermit             ││
│  │  (EILEEN's AI)   │◄─────►│  (Cognitive Command)     ││
│  │                  │bottles│                          ││
│  │  OCR pipeline    │       │  LangGraph workflows     ││
│  │  Species ID      │       │  SurrealDB vector store  ││
│  │  Memory tiers    │       │  18+ AI providers        ││
│  │  Catch logging   │       │  Podcast generation      ││
│  │  Fleet monitor   │       │  Content transforms      ││
│  └──────────────────┘       └──────────────────────────┘│
│           │                            │                 │
│           ▼                            ▼                 │
│  ┌──────────────────┐       ┌──────────────────────────┐│
│  │  Garmin/TZ Pro   │       │  Fleet Knowledge Base    ││
│  │  NMEA stream     │       │  Research synthesis      ││
│  │  catch logs      │       │  Multi-agent memory      ││
│  └──────────────────┘       └──────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

---

## The Name Is Final

The Captain's preferred name is **Hermit**. The repo has been renamed from `A2A-native-notebookLM` to `hermit`. See `_HERMIT_NAME.md` for the full naming rationale.

The hermit crab has found its shell. Let's go fishing. 🦀⚓
