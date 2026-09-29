# Retained Verification Attempts

These attempts are not release verification. No report or raw artifact was
overwritten to turn a failed run into a pass.

- `reports/verification/closure_frozen_20260930_01`: 2,125 tests passed and 12
  failed; 89.82% combined coverage. The Windows SQLite file-URI and subprocess
  audit compatibility defects caused the failures. Concurrent follow-up fixes
  also changed the original input inventory. Sealed manifest SHA256:
  `84c4805ead7f7cdbb30de7f07698f8363b4aa3ff0c06df20aa83e10878099a98`.
- `reports/verification/closure_frozen_20260930_02`: 2,131 passed and 12 failed;
  89.83% combined coverage. This isolated copy retained the old guard, so the
  same failures remained. Source input drift also disqualifies the bundle.
  Manifest SHA256:
  `3b71a02576a8916281b777015ba43157b9852ccf0afac983061a4c9fdf5a7bac`.
- `reports/verification/closure_frozen_20260930_03`: intentionally interrupted
  after an independent reviewer reproduced a Windows case-alias environment
  bypass in the subprocess guard. Only the specifically identified pytest worker
  was stopped; the outer wrapper finished and sealed the unsuccessful attempt.
  Missing JUnit/coverage output and the nonzero child result cannot be treated as
  passed/skipped tests. Manifest SHA256:
  `3ceebee0a480dfc3f4792d8a149f1b1f71facddb88d0bbfdca249567d0575c90`.

The independent probe used audit events, not actual network/database/outside-file
operations. Subsequent verification must use a new run directory after the guard
fix and regression tests. These coverage measurements do not prove full-chain
Eval, Model Judge, customer eligibility, release readiness or real pilot success.
