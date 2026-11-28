"""Check ridethrough/prc029.py against the text of NERC PRC-029-2.

    python validate/check_prc029.py
    python validate/check_prc029.py --pdf prc-029-2.pdf

The first form parses the three tables out of validate/src_prc_029_2.txt,
works out which values each printed row covers, and asserts the package
returns that row's region and time at both ends of it. It then asserts each
constant against a sentence quoted from the same file.

The second form also checks the extract itself: every line of it must be
found in the text of the PDF you pass. It needs `pdftotext` from poppler.
"""
import hashlib
import re
import subprocess
import sys

sys.path.insert(0, ".")
from ridethrough import prc029 as P  # noqa: E402
from ridethrough.envelope import CONTINUOUS  # noqa: E402

SRC = "validate/src_prc_029_2.txt"
EPS = 1e-6
REGIONS = {
    "Mandatory": P.MANDATORY,
    "Continuous": P.CONTINUOUS_REGION,
    "Permissive": P.PERMISSIVE,
    "N/A": P.MAY_RIDE_THROUGH,
}
ROW = re.compile(
    r"^((?:[<>≥≤] [\d.]+)(?: and [<>≥≤] [\d.]+)?) "
    r"(?:(N/A)(?: \d+)?|(Mandatory|Continuous|Permissive) Operation Region)? ?"
    r"(N/A|May trip|Continuous|[\d.]+)$"
)


def source_lines(path=SRC):
    """(page, text) for every line of the extract that is not a comment."""
    out = []
    for line in open(path, encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        page, text = line.rstrip("\n").split(": ", 1)
        out.append((int(page[1:]), text))
    return out


def tables(lines):
    """The printed rows of each table, in the order printed."""
    found, current = {}, None
    for _, text in lines:
        title = re.match(r"^Table (\d):", text)
        if title:
            current = int(title.group(1))
            found[current] = []
            continue
        row = ROW.match(text)
        if current and row:
            condition, na, region, time = row.groups()
            found[current].append((condition, na or region, time))
        elif current and found[current]:
            current = None
    return found


def seconds(text):
    if text in ("N/A", "May trip"):
        return None
    if text == "Continuous":
        return CONTINUOUS
    return float(text)


def probes(rows, i):
    """Values at both ends of what printed row i covers.

    A row printed "< x" covers from x down to the next lower threshold. A
    row printed "> x" or "≥ x" covers from x up to the next higher one. The
    signs printed on the neighbouring rows decide which row owns a
    threshold itself.
    """
    condition = rows[i][0]
    both = re.match(r"^≤ ([\d.]+) and ≥ ([\d.]+)$", condition)
    if both:
        return [float(both.group(2)), float(both.group(1))]
    sign, x = condition.split()
    x = float(x)
    if sign == "<":
        if i + 1 < len(rows):
            return [x - EPS, float(rows[i + 1][0].split()[1])]
        return [x - EPS, 0.0]
    near = x if sign == "≥" else x + EPS
    if i == 0:
        return [near, x * 2.0]
    upper_sign, upper = rows[i - 1][0].split()
    upper = float(upper)
    return [near, upper if upper_sign == ">" else upper - EPS]


def check_tables(lines):
    ok = True
    printed = tables(lines)
    for number, table in ((1, P.PRC029_TABLE_1_WIND),
                          (2, P.PRC029_TABLE_2_OTHER),
                          (3, P.PRC029_TABLE_3_FREQUENCY)):
        rows = printed.get(number, [])
        print(f"\n=== TABLE {number}: {len(rows)} rows in the source, "
              f"{len(table.rows)} in the package ===")
        if len(rows) != len(table.rows):
            ok = False
            print("  MISMATCH  row count")
        if [r[0] for r in rows] != [r.printed for r in table.rows]:
            ok = False
            print("  MISMATCH  printed conditions differ")
        for i, (condition, region, time) in enumerate(rows):
            want_time = seconds(time)
            want_region = REGIONS.get(region) if region else None
            for probe in probes(rows, i):
                row = table.row_for(probe)
                match = (row.minimum_time == want_time
                         and row.region == want_region
                         and row.printed == condition)
                if not match:
                    ok = False
                print(f"  {'OK ' if match else 'MISMATCH'}  {condition:<18} "
                      f"probe={probe:<11.6f} want={want_time} "
                      f"got={row.minimum_time}")
    return ok


CLAIMS = [
    (P.PRC029_MIN_MVA, 20.0,
     "aggregate nameplate capacity of greater than or equal to 20 MVA", "4.2.2"),
    (P.PRC029_MIN_KV, 60.0,
     "at a voltage greater than or equal to 60 kV", "4.2.2"),
    (P.PRC029_PHASE_JUMP_DEGREES, 25.0,
     "phase angle change is more than 25 electrical degrees", "R1"),
    (P.PRC029_VHZ_PU, 1.1,
     "exceed 1.1 per unit for longer than 45 seconds", "R1"),
    (P.PRC029_VHZ_SECONDS, 45.0,
     "exceed 1.1 per unit for longer than 45 seconds", "R1"),
    (P.PRC029_VHZ_HIGH_PU, 1.18,
     "exceed 1.18 per unit for longer than 2 seconds", "R1"),
    (P.PRC029_VHZ_HIGH_SECONDS, 2.0,
     "exceed 1.18 per unit for longer than 2 seconds", "R1"),
    (P.PRC029_PRIORITY_BELOW_PU, 0.95,
     "when the voltage is less than 0.95 per unit", "R2.1.3"),
    (P.PRC029_RESTART_CYCLES, 5,
     "restart current exchange in less than or equal to five cycles", "R2.3.1"),
    (P.PRC029_RECOVERY_SECONDS, 1.0,
     "(whichever is lesser) within 1.0 second", "R2.5"),
    (P.PRC029_ROCOF_HZ_PER_SECOND, 5.0,
     "magnitude is less than or equal to 5 Hz/second", "R3"),
    (P.PRC029_ROCOF_MIN_PERIOD_SECONDS, 0.1,
     "a time period of greater than or equal to 0.1 second", "footnote 9"),
    (P.PRC029_VOLTAGE_WINDOW_SECONDS, 10.0,
     "within each band of Tables 1 and 2 over any 10 second time period",
     "Att. 1 item 7"),
    (P.PRC029_VOLTAGE_WINDOW_SECONDS, 10.0,
     "cumulative over one or more disturbances within any 10 second time period",
     "Att. 1 item 8"),
    (P.PRC029_MAX_DEVIATIONS, 4,
     "may trip for more than four deviations of the applicable voltage",
     "Att. 1 item 9"),
    (P.PRC029_FREQUENCY_WINDOW_SECONDS, 600.0,
     "cumulative over one or more disturbances within a 10-minute time period",
     "Att. 2 item 5"),
]


def check_constants(lines):
    text = "\n".join(t for _, t in lines)
    ok = True
    print("\n=== CONSTANTS ===")
    for actual, expected, quote, clause in CLAIMS:
        in_code = actual == expected
        in_src = quote in text
        if not (in_code and in_src):
            ok = False
        print(f"  {'OK ' if in_code and in_src else 'FAIL'}  {clause:<14} "
              f"value={actual!r:<7} expected={expected!r:<7} quote_found={in_src}")
        if not in_src:
            print(f"        MISSING QUOTE: {quote!r}")
    return ok


def missing_from(lines, pages):
    """Extract lines not found on their stated page of the PDF text."""
    return [(page, text) for page, text in lines
            if page > len(pages) or text not in pages[page - 1]]


def check_pdf(lines, pdf):
    raw = subprocess.run(["pdftotext", "-layout", pdf, "-"],
                         capture_output=True, text=True, check=True).stdout
    pages = [re.sub(r"\s+", " ", page).strip() for page in raw.split("\f")]
    sha = hashlib.sha256(open(pdf, "rb").read()).hexdigest()
    recorded = re.search(r"sha256 ([0-9a-f]{64})",
                         open(SRC, encoding="utf-8").read()).group(1)
    print(f"\n=== EXTRACT AGAINST {pdf} ===")
    if sha == recorded:
        print("  OK   this is the file the extract was read from")
    else:
        print("  NOTE this is a different file from the one the extract was "
              "read from; its lines are still checked")
    gone = missing_from(lines, pages)
    for page, text in gone:
        print(f"  FAIL page {page}: {text[:70]}")
    print(f"  {len(lines) - len(gone)} of {len(lines)} lines found in the PDF")
    return not gone


def main(argv):
    lines = source_lines()
    ok = check_tables(lines)
    ok = check_constants(lines) and ok
    if "--pdf" in argv:
        ok = check_pdf(lines, argv[argv.index("--pdf") + 1]) and ok
    print("\nALL PRC-029-2 ROWS AND CONSTANTS MATCH" if ok
          else "\n*** PRC-029-2 MISMATCH ***")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
