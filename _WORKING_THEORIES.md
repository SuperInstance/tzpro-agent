# Working Theories: Chum Trolling Underwater Dynamics

*Knowledge encoded from the Captain's observations and sounder analysis.*
*These are hypotheses being refined, not proven facts.*

---

## 1. Sounder Interference as a Signal

**Observation:** When other boats are near, their sounder transducers create vertical line artifacts on our display.

**What this means:** Every vertical line in the echogram is a data point — not noise. It's a "ping" from another boat's transducer. The pattern of these vertical lines (frequency, density, duration) tells us:
- How many other boats are in range
- How close they are (denser lines = closer)
- How long they've been near (line clusters over time)
- Whether they're approaching or leaving (increasing vs decreasing line density)

**System Implication:** The analyzer should NOT filter these out as artifacts. Instead, it should **detect and count** them as `boat_proximity` signals in the analysis JSON.

---

## 2. Temporal Context (Not Just Single Frames)

**Current analyzer behavior:** Analyzes one frame every 60s, produces a standalone description. No memory of what it said before.

**What's needed:** The analyzer must read its own prior descriptions (last 3-6 frames, ~30-60 min window) to build temporal perspective. This lets it say things like:

- "Boats have been near for the past 40 minutes (19, 21, 15, 22 vertical lines in last 4 frames)"
- "Vertical line density decreasing over last 3 frames — boats moving away"
- "Vertical line cluster peaked at 1420h, now declining — other boat likely passing through"
- "No boats detected for past 50 minutes — we're alone"

**Why it matters:** In chum trolling, boats come and go. A single frame says "there are 20 vertical lines." Four frames over 40 minutes say "boats are circling us" vs "a boat passed through."

---

## 3. Fleet Competition Dynamics

**The mechanism (working theory):**
1. Each boat in chum trolling builds a school following the boat
2. The school is attracted to the boat's presentation: speed, lure action, voltage in the water, engine noise, smell/chum slick
3. When two boats get close enough, the fish face a choice — they can follow boat A or boat B
4. **One boat takes from the other** — the boat with the better presentation wins the school (or part of it)
5. This isn't just about catching fish — it's about *keeping* the fish you've built vs having them stolen

**The sounder should show:**
- When another boat approaches, blobs decrease in front of us and increase toward them (fish shifting loyalty)
- When we pass a boat, a 5-15 min quiet period as the school adjusts
- In multi-boat clusters, the sounder looks chaotic with shifting returns

**What we can learn:**
- Which presentation factors matter most (speed? lure? engine noise?) by correlating catch rates with nearby boat characteristics
- How close is "too close" (threshold where fish transfer starts)
- Whether certain boats/rigs consistently "win" encounters

---

## 4. Presentation Factors (Things We Can Measure)

The Captain mentioned these factors that affect whether fish choose our boat vs another:

| Factor | Measurable? | How |
|--------|------------|-----|
| **Speed** | ✅ Yes | SOG from NMEA, trolling speed over ground |
| **Lure** | 🟡 Partially | Manual input (which lures deployed) |
| **Voltage in water** | 🟡 Partially | Need sensor; some boats measure trolling voltage |
| **Engine noise** | ❌ No | Subjective; varies by engine/load |
| **Smell/chum slick** | 🟡 Partially | Manual input (chumming schedule) |

**Immediate wins:** Speed is already logged via NMEA. We can correlate catch reports with speed changes. Next step: manual lure/gear notes in catch reports.

---

## 5. What "Good" Looks Like

The Captain's goal: **better per-hour catch rates** through analytical help.

The system should eventually be able to advise:
- "The last time you caught chum at this depth with this many nearby boats, your speed was 2.0-2.2 kts"
- "Boat proximity is increasing — expect a 15-min dip in bite rate"
- "You've been alone for 2 hours, chum school should be built steady — good time for gear change experiment"
- "Historically, X blobs in the mid zone at Y vertical lines predicts Z fish in the next haul"


## 6. HF Shallow Haze = Feed/Plankton (08:18 Captains Observation)

**Observation:** Steering west of normal drag into deeper water, the HF band shows a granular haze at 3-10 fm that increased over 15 min. The LF band below it (20-40 fm) shows a constant dense cloud.

**Interpretation (working theory):**
- HF shallow haze = plankton/krill/baitfish concentrated in the top 10 fm
- LF cloud below = the chum school holding beneath the feed layer
- The haze increased when the boat moved to a new area - feed patches vary by location
- The school size (LF cloud) stayed constant even as feed changed - school may be following the boat, not the feed patch

**What the analyzer should look for:**
- HF surface/upper zone: count of SMALL faint blobs vs large blobs (haze = many small)
- HF mean intensity in surface zone (3-10 fm) - rapid increase = moving into feed
- Correlation: does HF feed presence predict LF school staying or leaving?
- Ratio: HF shallow blob count / LF mid blob count
