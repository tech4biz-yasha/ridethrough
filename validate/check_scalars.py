"""PASS 3 - each constant must be justified by a sentence in the source."""
import sys

sys.path.insert(0, ".")
from ridethrough import envelope as E

SRC_V = open("validate/src_2_15.txt").read()
SRC_F = open("validate/src_2_6_4.txt").read()

CLAIMS = [
    (E.ERCOT_CURRENT_LIMIT, 1.50, SRC_V,
     "exceeds 150% of its maximum electric current consumption", "2.15(3)(d)"),
    (E.ERCOT_OVERCURRENT_MAX_SECONDS, 0.5, SRC_V,
     "duration not to exceed 0.5 seconds", "2.15(3)(d)"),
    (E.ERCOT_RECOVERY_FRACTION, 0.90, SRC_V,
     "return to at least 90% of its pre-disturbance consumption", "2.15(3)(c)"),
    (E.ERCOT_RECOVERY_SECONDS, 2.0, SRC_V,
     "within two seconds of voltage at the Service Delivery Point", "2.15(3)(c)"),
    (E.ERCOT_RECOVERY_VOLTAGE, 0.90, SRC_V,
     "returning to above 0.90 per unit", "2.15(3)(c)"),
    (E.ERCOT_TRANSFER_START_SECONDS, 0.25, SRC_V,
     "begins returning to the grid within 0.25 seconds", "2.15(3)(e)"),
    (E.ERCOT_TRANSFER_RECOVERY_SECONDS, 0.5, SRC_V,
     "consumption level within 0.5 seconds of voltage returning", "2.15(3)(e)"),
    (E.ERCOT_OVERVOLTAGE_SECONDS, 1.0, SRC_V,
     "remains below 1.2 per unit for less than 1.0 seconds", "2.15(3)(a)"),
    (E.ERCOT_COOLING_EXEMPT_BELOW_PU, 0.35, SRC_V,
     "voltage conditions are below 0.35 p.u. for any duration", "2.15(3)"),
    (E.ERCOT_HIGH_VOLTAGE_TRIP_PU, 1.08, SRC_V,
     "above 1.08 p.u. that persists for 5 seconds", "2.15(3)(f)"),
    (E.ERCOT_HIGH_VOLTAGE_TRIP_SECONDS, 5.0, SRC_V,
     "persists for 5 seconds or greater", "2.15(3)(f)"),
    (E.ERCOT_MIN_SAGS, 6, SRC_V,
     "minimum of six voltage sags or swells", "2.15(7)"),
    (E.ERCOT_MIN_SAGS_WINDOW_SECONDS, 90.0, SRC_V,
     "within a 90-second period", "2.15(7)"),
]

ok = True
for actual, expected, src, quote, clause in CLAIMS:
    in_code = (actual == expected)
    in_src = quote in src
    status = "OK " if (in_code and in_src) else "FAIL"
    if not (in_code and in_src):
        ok = False
    print(f"  {status}  {clause:<12} value={actual!r:<8} expected={expected!r:<8} "
          f"quote_found={in_src}")
    if not in_src:
        print(f"        MISSING QUOTE: {quote!r}")

# things that must NOT be in the source any more
GONE = ["125%", "0.20 ≤ V", "61.8", "57.0 ≤ f", "positive sequence", "one second"]
print("\n  draft values that must be absent from the approved text:")
for g in GONE:
    present = g in SRC_V or g in SRC_F
    if present:
        ok = False
    print(f"    {'OK ' if not present else 'FAIL'}  {g!r} present={present}")

print("\nALL SCALARS JUSTIFIED" if ok else "\n*** SCALAR PROBLEM ***")
sys.exit(0 if ok else 1)
