# Offline Isolation Preflight

These are synthetic test-harness checks, not complete release verification.

- Attempt 01 was blocked before test collection because the ad-hoc harness did
  not redirect pytest capture's temporary files into the allowed output root.
- Attempt 02 redirected those files: 59 tests passed and one child-process guard
  test failed. The ad-hoc harness had not installed the full runner's
  sitecustomize bootstrap. The test correctly detected the missing child guard.
- Attempt 03 uses the same two-line guard bootstrap as the actual frozen runner,
  inherited through an absolute PYTHONPATH, with all temporary files under its
  own output root. No production guard or runtime isolation rule was relaxed.

Attempts 01 and 02 remain retained. Neither is reported as a passing run.
