"""tzpro-agent/panel — three-panel day console.

* Panel 1: M1 delta notes (transient, no images).
* Panel 2: M10 records — kept 10-min canonical frames + per-record analysis.
* Panel 3: H1 hourly briefings + D1 daily briefs — human MD + agentic JSON.

Talks to the cascade_out/ tree directly (the cascade is its source of
truth for what happened; the twin is a sidecar). Same stdlib-only
discipline as scrubber/serve.py — no third-party deps.
"""
