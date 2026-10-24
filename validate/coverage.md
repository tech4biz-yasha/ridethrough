# Clause coverage, Section 2.15 and 2.6.4 of 02-080126.docx

G = graded   S = declared out of scope   X = GAP, not handled and not declared

## 2.15 Voltage
G  (3)       Table A, and "shall remain connected"
G  (3)       cooling or mechanical load may trip below 0.35 pu
G  (3)(a)    overvoltage hold, 1.0 s
G  (3)(b)    0.80-0.90 keep consuming, 90% in 2 s
G  (3)(c)    below 0.80, 90% in 2 s, cooling subtracted
X  (3)(c)(i) reduction "proportional to the voltage drop ... if capable"
G  (3)(c)(ii) post-2028 continue consuming 0.80-0.50
G  (3)(d)    150% ceiling
G  (3)(d)    overcurrent duration 0.5 s (reported, unscored)
G  (3)(e)    transfer route 0.25 s / 0.5 s
X  (3)(e)(i) one action per device per disturbance event
X  (3)(f)    may trip above 1.08 pu persisting 5 s, before 2028
S  (4)       nothing requires tripping - not an obligation
S  (5)       protection must permit ride-through to equipment capability
S  (6)       filtered quantities, one-cycle measurement window
G  (7)       no sag counting; six sags in 90 s
S  (8)       failure investigation process
S  (1),(2)   exemption criteria - contracts, dates, attestations

## 2.6.4 Frequency
X  (3)       Table A present in the package but never graded
S  (3)       UFLS and Ancillary Service carve-out
X  (5)       keep consuming, and "should" stay within 10% of pre-disturbance
X  (6)       frequency transfer route, 90% within 2 s
S  (4),(7),(8),(9)  not obligations, or settings, or process
S  (1),(2)   exemption criteria
