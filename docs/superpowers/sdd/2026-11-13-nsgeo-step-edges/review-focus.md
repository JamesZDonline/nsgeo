## Review Focus

1. **Numpy scalars from plugin code.** A pick or a spin box can hand `np.int64` or `np.float32` to
   `build_step`. Ints and floats must still accept them. Pinned in Task 3.
2. **A repaired preset applied later.** After a load repair, applying the preset to a grid or using
   it for slices must build and run, not raise. Pinned in Task 4.
3. **Save, then reopen, after a repair.** The repaired state persists, and the second open has no
   notes. Pinned in Task 4.
4. **The Add-step dialog's one-trace test run** (bandpass, migration, gain curve) on an all-zero
   first trace. A valid bandpass must still pass it; the empty-band check depends only on the
   sample count and interval. Pinned in Task 3.
5. **One NaN through the user's real stack.** Time zero, time cutoff 45 ns, dewow, background mean,
   AGC and gain curve end with exactly one NaN in the output, at the bad sample. Pinned in Task 2.

