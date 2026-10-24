from ridethrough.grade import Trace, grade

# A 0.65 pu sag held 400 ms. Inside the ERCOT envelope, so ride-through is required.
voltage   = Trace([0.0, 1.0, 1.4, 5.0], [1.00, 0.65, 1.00, 1.00])
connected = Trace([0.0, 5.0], [1.0, 1.0])
power     = Trace([0.0, 1.0, 1.4, 1.7, 5.0], [100.0, 60.0, 60.0, 98.0, 100.0])
current   = Trace([0.0, 1.0, 1.4, 5.0], [1.00, 1.15, 1.00, 1.00])

r = grade(voltage, connected, power, current,
          pre_disturbance_power=100.0, max_normal_current=1.0)

print(f"verdict: {r.verdict}")
for c in r.checks:
    mark = {True: "pass", False: "FAIL", None: "n/a "}[c.passed]
    print(f"  [{mark}] {c.name}: {c.detail}")

print()
# Same facility, same sag, but the UPS pulls 1.6x current.
hot = Trace([0.0, 1.0, 1.4, 5.0], [1.00, 1.60, 1.00, 1.00])
r2 = grade(voltage, connected, power, hot,
           pre_disturbance_power=100.0, max_normal_current=1.0)
print(f"verdict: {r2.verdict}  (driver: {r2.trip_driver})")
for c in r2.checks:
    mark = {True: "pass", False: "FAIL", None: "n/a "}[c.passed]
    print(f"  [{mark}] {c.name}: {c.detail}")
