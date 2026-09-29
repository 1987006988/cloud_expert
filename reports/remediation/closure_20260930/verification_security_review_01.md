# Offline Verification Guard Review

Date: 2026-09-30 (Asia/Shanghai). This is bounded code review of a Python test
guard, not an OS security sandbox, business model approval or release certification.

## Windows Compatibility

The first two full bundles exposed Windows file-URI conversion and subprocess
audit argument differences. The runner now uses the platform file-URI converter
and Windows argument parser, verifies the exact Python executable and rejects
startup switches that could remove the inherited guard. The original 12 failing
cases were re-executed inside a real outer guard, without skipping them or
changing their CLI harnesses. Network/external execution and outside-output writes
remain denied by the guard's explicit Python audit boundary.

## P1: Environment Alias Bypass

The independent reviewer reproduced a bypass with both `PYTHONPATH` and a
case-variant key in the child environment. A case-sensitive dictionary lookup
passed while the actual Windows child could omit the guard. Probes used audit
events only; no actual outside file, network or database operation was performed.

The fix canonicalizes environment keys according to the host platform and rejects
ambiguous case-insensitive duplicates on Windows before validating protected
values. Normal inherited guard behavior and grandchild propagation remain tested.

- Final focused run under the real outer guard: 128 passed, zero failures,
  errors or skips. Receipt: `verification_guard_windows_03/junit.xml`.
- Independent reviewer reported 23/23 read-only checks passing and confirmed the
  P1 closed, with no further actionable finding in this bounded review.
- Only `evals/verification_run.py` and its dedicated unit test were changed by
  the repair owner. No CLI test harness was weakened; no business DB was accessed.
- Full bundle03 was intentionally interrupted when the P1 was found. Its failed
  sealed receipt remains preserved; it is not a passing baseline.

Full bundle04 is a separate final offline verification attempt. Its own sealed
result, unchanged-input checks and fresh coverage are required before calling it
passed. Neither focused tests nor this review substitutes for full-chain Eval,
actual Model Judge, customer qualification or deployment verification.
