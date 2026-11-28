# Validation against the source

These scripts check the package against the published rule rather than
against itself. Run them from the repository root.

```
python validate/check_tables.py    # every table row, parsed from the source
python validate/check_scalars.py   # each 2.15 and 2.6.4 constant, against a quoted sentence
python validate/check_prc029.py    # the PRC-029-2 tables and constants
```

`src_2_15.txt` and `src_2_6_4.txt` are the two sections of ERCOT Nodal
Operating Guide Section 2, file `02-080126.docx`, effective 1 August 2026,
extracted as plain text. `check_tables.py` parses Table A out of them and
asserts that the package returns the stated minimum ride-through time for
probe values at both edges of every band. `check_scalars.py` asserts that
each ERCOT constant from Sections 2.15 and 2.6.4 in `ridethrough/envelope.py`
matches a sentence quoted from the source, and that the six superseded draft
values are absent. The two definition thresholds from Nodal Protocols Section
2.1 and the Energinet values are not covered by these scripts.

`coverage.md` lists every clause of both sections and marks it graded,
declared out of scope, or a gap.

`src_prc_029_2.txt` is an extract of NERC Reliability Standard PRC-029-2:
its three tables and a selection of its sentences, each with its page
number. `check_prc029.py` parses the tables out of it, works out from the
printed signs which values each row covers, and asserts that
`ridethrough/prc029.py` returns that row's region and time at both ends of
it. It then asserts each constant against a sentence in the extract. Run
with `--pdf` and a copy of the standard, it also checks that every line of
the extract is found on its stated page of the PDF. That form needs
`pdftotext` from poppler.

The point of keeping these in the repository is that anyone can rerun them.
A claim that the numbers come from the rule is worth less than a script
that checks it.
