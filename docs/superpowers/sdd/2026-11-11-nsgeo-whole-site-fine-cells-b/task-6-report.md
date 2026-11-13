# Task 6 report
Changed docs/guide/getting-started.md (steps 4-6: removed the "refuses at a cell that would not fit" text; rewrote Display with a plain coverage explanation and the companion file; rewrote Export GeoTIFF with the dialog, cell/pixel, refusal, replace, background run, normalisation, .qml) and README.md (#108 moved to Done as "next release"; In progress section removed; #157 in Wishlist Slices group, link added).
Code notes: the coverage companion is written only when Show coverage is ticked (the guide says so). The dialog's replace text says the layer is "added again when the export finishes"; on success the new export is added, on cancel/failure the old one is restored (guide follows this). The old progress window was not mentioned in the guide (only "shows its progress", which is still true).
Tests: test_release_docs.py 5 passed. No Python touched.

## Fix round 1
Show coverage paragraph: replaced "A cell with 0 had no line cross it" with "The number in a cell is how many traces fell in it. A blank cell had no line through it". Re-ran test_release_docs.py: 5 passed.
