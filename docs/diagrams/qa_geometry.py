"""Geometry QA for the excalidraw JSON: text overflow, container overflow, overlaps, arrow landings."""
import json, sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else r"D:\Code\EcoGain\docs\diagrams\system-architecture.excalidraw")
data = json.loads(path.read_text(encoding="utf-8"))
els = [e for e in data["elements"] if not e.get("isDeleted")]

by_id = {e["id"]: e for e in els}
rects = [e for e in els if e["type"] == "rectangle"]
texts = [e for e in els if e["type"] == "text"]

# Estimate rendered text size: width already stored; check against container if bound
problems = []

# 1) Bound-text overflow (declared width vs container width) — excalidraw stores text width from font metrics
for t in texts:
    cid = t.get("containerId")
    if cid and cid in by_id:
        c = by_id[cid]
        if t["x"] < c["x"] - 2 or t["x"] + t["width"] > c["x"] + c["width"] + 2:
            problems.append(f"[text-overflow] '{t['text'][:24]}' x-overflow container '{cid}'")
        if t["y"] < c["y"] - 2 or t["y"] + t["height"] > c["y"] + c["height"] + 2:
            problems.append(f"[text-overflow] '{t['text'][:24]}' y-overflow container '{cid}'")

# 2) Unbound text vs unrelated rectangles overlap (text landing on a box it doesn't belong to)
def overlap(a, b):
    return not (a["x"] + a["width"] <= b["x"] or b["x"] + b["width"] <= a["x"]
                or a["y"] + a["height"] <= b["y"] or b["y"] + b["height"] <= a["y"])

for t in texts:
    if t.get("containerId"):
        continue
    for r in rects:
        # Skip if this text is the label of the rect (boundElements) or rect is a dark evidence box meant to host text
        if r.get("boundElements") and any(be["id"] == t["id"] for be in r["boundElements"]):
            continue
        if r.get("backgroundColor") == "#1e293b":
            continue
        if overlap(t, r):
            problems.append(f"[free-text-overlap] '{t['text'][:28]}' overlaps rect '{r['id']}'")

# 3) Arrow endpoints: each end should land near some non-arrow element (within 30px), else flag
others = [e for e in els if e["type"] not in ("arrow",)]
def near(p, e, tol=34):
    px, py = p
    ex, ey, ew, eh = e["x"], e["y"], e.get("width", 0), e.get("height", 0)
    return (ex - tol) <= px <= (ex + ew + tol) and (ey - tol) <= py <= (ey + eh + tol)

for a in els:
    if a["type"] != "arrow":
        continue
    x, y = a["x"], a["y"]
    pts = a["points"]
    start = (x + pts[0][0], y + pts[0][1])
    end = (x + pts[-1][0], y + pts[-1][1])
    for label, p in (("start", start), ("end", end)):
        if not any(near(p, o) for o in others if o is not a):
            problems.append(f"[arrow-dangling] '{a['id']}' {label} at ({p[0]:.0f},{p[1]:.0f}) lands on nothing")

# 4) Elements outside canvas bbox sanity (negative far coords)
for e in els:
    if e["x"] < -5 or e["y"] < -5:
        problems.append(f"[offcanvas] '{e['id']}' at ({e['x']},{e['y']})")

print(f"Checked {len(els)} elements: {len(rects)} rects, {len(texts)} texts, {sum(1 for e in els if e['type']=='arrow')} arrows")
if problems:
    print(f"{len(problems)} issue(s):")
    for p in problems:
        print(" -", p)
else:
    print("No geometry issues found.")
