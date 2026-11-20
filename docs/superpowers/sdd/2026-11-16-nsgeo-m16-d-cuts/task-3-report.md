# Task 3 report
Implemented walls.py (MAX_WALL_COLUMNS, Wall, wall_columns, line_wall, cut_wall, wall_points), vtkxml.write_structured_grid / structured_grid_bytes, vtk_reader StructuredGrid support, README rows for the two new public names (test_public_api requires them).
RED: both new test files failed at collection (ImportError: cannot import name 'structured_grid_bytes' / no module walls).
GREEN: test_slices_walls + test_vtkxml 16 passed (real-line test ran, data present). Full core+pure: 1971 passed, 1 failed (README names; fixed by README rows, rerun of test_public_api green), 9 skipped, 19 xfailed. ruff check/format and CI mypy clean.
Concern: brief's round-trip test asserts n == stat size == structured_grid_bytes(20,1), impossible with a 4096 header allowance (as image_data_bytes). structured_grid_bytes = payload + 4096; test asserts size <= est and est - size < 4096, and n == size.
Extra tests: line wall interpolation on synthetic ramp (catches clock off-by-one), NaN outside time range, rotated frame bent-path cut wall.
