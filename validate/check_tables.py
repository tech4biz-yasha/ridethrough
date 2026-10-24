"""PASS 2 - parse the source tables and assert the code matches, row by row."""
import re
import sys

sys.path.insert(0, ".")
from ridethrough.envelope import CONTINUOUS, ERCOT_FREQUENCY, ERCOT_VOLTAGE


def rows(path):
    out = []
    for line in open(path):
        if not line.startswith("ROW:"):
            continue
        cells = [c.strip() for c in line[5:].split("|")]
        header = "Minimum" in cells[1] if len(cells) == 2 else True
        if len(cells) == 2 and re.match(r"^[Vf0-9]", cells[0]) and not header:
            out.append(tuple(cells))
    return out

def parse_time(s):
    s = s.strip().lower()
    if "may ride" in s:
        return None
    if "continuous" in s:
        return CONTINUOUS
    return float(s)

def probes(cond):
    """Return representative values that must fall in this band."""
    cond = cond.replace("≤","<=").replace("≥",">=")
    m = re.match(r"^[Vf]\s*>\s*([\d.]+)$", cond)
    if m:
        return [float(m.group(1)) + 0.05, float(m.group(1)) + 1.0]
    m = re.match(r"^[Vf]\s*<\s*([\d.]+)$", cond)
    if m:
        return [float(m.group(1)) - 0.01, max(0.0, float(m.group(1)) - 0.2)]
    m = re.match(r"^([\d.]+)\s*<\s*[Vf]\s*<=\s*([\d.]+)$", cond)
    if m:
        return [float(m.group(1)) + 0.01, float(m.group(2))]
    m = re.match(r"^([\d.]+)\s*<=\s*[Vf]\s*<=\s*([\d.]+)$", cond)
    if m:
        return [float(m.group(1)), float(m.group(2))]
    m = re.match(r"^([\d.]+)\s*<=\s*[Vf]\s*<\s*([\d.]+)$", cond)
    if m:
        return [float(m.group(1)), float(m.group(2)) - 0.01]
    raise ValueError("unparsed condition: " + cond)

ok = True
for path, env, label in [("validate/src_2_15.txt", ERCOT_VOLTAGE, "VOLTAGE"),
                         ("validate/src_2_6_4.txt", ERCOT_FREQUENCY, "FREQUENCY")]:
    print(f"\n=== {label} ===")
    for cond, timetext in rows(path):
        want = parse_time(timetext)
        for probe in probes(cond):
            got = env.minimum_time(probe)
            match = (got == want) or (got is None and want is None)
            flag = "OK " if match else "MISMATCH"
            if not match:
                ok = False
            print(f"  {flag}  {cond:<20} probe={probe:<7.3f} want={want} got={got}")
print("\nALL TABLE ROWS MATCH" if ok else "\n*** TABLE MISMATCH ***")
sys.exit(0 if ok else 1)
