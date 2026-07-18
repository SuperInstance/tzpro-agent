"""Quick smoke tests for voice_catch.py – run manually if desired."""
import json
from voice_catch import parse_catch


def run():
    cases = [
        ("chum at 35 fm 15 fish",
         {"species": "chum", "count": 15, "depth_fm": 35}),
        ("12 pound chum at 30 fathoms",
         {"species": "chum", "weight_lb": 12.0, "depth_fm": 30}),
        ("chum at 35 on green flasher, 15 fish",
         {"species": "chum", "count": 15, "depth_fm": 35,
          "gear": "green flasher"}),
        ("coho at 50 fm on herring, 3 fish",
         {"species": "coho", "count": 3, "depth_fm": 50,
          "gear": "herring"}),
        ("king salmon 25 pound at 80 fm on spoon",
         {"species": "king", "weight_lb": 25.0, "depth_fm": 80,
          "gear": "spoon"}),
        ("silver at 20 fm",
         {"species": "coho", "depth_fm": 20}),
        ("got 6 halibut at 120 fm",
         {"species": "halibut", "count": 6, "depth_fm": 120}),
        ("ling cod at 40 fm on jig",
         {"species": "lingcod", "depth_fm": 40, "gear": "jig"}),
        ("one chum on green flasher at 35 fathom",
         {"species": "chum", "depth_fm": 35, "gear": "green flasher"}),
    ]

    ok = 0
    for text, expected in cases:
        r = parse_catch(text)
        for key, want in expected.items():
            got = r.get(key)
            if got != want:
                print(f"FAIL [{text!r}]\n"
                      f"  field={key}  expected={want!r}  got={got!r}\n")
                break
        else:
            ok += 1
            print(f"  OK  {text!r}")

    print(f"\n{ok}/{len(cases)} passed")
    return ok == len(cases)


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
