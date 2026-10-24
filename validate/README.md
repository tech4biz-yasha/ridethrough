# Validation against the source

These scripts check the package against the published rule rather than
against itself. Run them from the repository root.

```
python validate/check_tables.py    # every table row, parsed from the source
python validate/check_scalars.py   # every constant, against a quoted sentence
```

`src_2_15.txt` and `src_2_6_4.txt` are the two sections of ERCOT Nodal
Operating Guide Section 2, file `02-080126.docx`, effective 1 August 2026,
extracted as plain text. `check_tables.py` parses Table A out of them and
asserts that the package returns the stated minimum ride-through time for
probe values at both edges of every band. `check_scalars.py` asserts that
each constant in `ridethrough/envelope.py` matches a sentence quoted from
the source, and that the six superseded draft values are absent.

`coverage.md` lists every clause of both sections and marks it graded,
declared out of scope, or a gap.

The point of keeping these in the repository is that anyone can rerun them.
A claim that the numbers come from the rule is worth less than a script
that checks it.
