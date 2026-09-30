# Retained Metadata Compatibility Investigation

The second frozen verification completed with 2,838 offline tests and 90.53826170183675 percent combined coverage. The same input digest passed five PostgreSQL migration commands and 14 integration tests. Week9 and Week10 both returned GO in their `*_gate_02.json` reports. This is a historical verified checkpoint, not advance approval of subsequent source edits.

DecisionResult 10281 was freshly generated and passed the read-only precheck. Actual `gpt-6-astra` primary execution returned exit code zero and a conditional business opinion. The panel nevertheless failed runtime attestation with `runtime_retained_source_invalid`, did not execute independent adversarial review, and did not write any approval to the database. Panel02 remains inconclusive and must never be retroactively approved.

The isolated native trace differs from the data-free probe03 in two retained-source boolean fields: `complete=false`. Their semantics have not been established as universally harmless. Read-only investigation found exact UTF-8 equality without trimming in both native copies of the user input and both native copies of the assistant output:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| Full prompt | 68014 | cedf49e971e717c47dbb242366b1afbe06e8cbce1fa558ca75819056fed3fb09 |
| Full response | 3645 | 099a3486f2899ea48b78617af4d447da8eb9327ebcb895b6808358da41c83d10 |
| Local-only original native trace | retained privately | 8902234b454812b8452868c64c625fbff1cfbc362660fb61a2155a0cd4034b02 |

All other native identity, input, completion, isolation and CLI checks passed during controlled read-only diagnostics. Diagnostics are not production acceptance and do not change the rejected receipt.

The authorized repair is limited to this observed clean-profile metadata variant, with explicit metadata fingerprints and exact full-byte input/output attestation across duplicate native records. Nonboolean flags, unknown fields, truncation, whitespace changes, wrong identity bindings and absent completion must still be rejected. New regression verification, PostgreSQL receipts, Decision regeneration and an entirely new independent model panel are required after implementation. Original runtime bytes remain private and excluded from Git.

## Verified Runtime Checkpoint

The repair is implemented. Frozen input `9d100e35a933191cde4e3c95059e81603cac7817511e8c9c5211eb260e43c769` passed 2,920 offline tests with 90.54386444383711 percent combined coverage, plus all five real PostgreSQL migration commands and 14 integration tests without skips. The offline manifest hash is `e4aaf0459354960b23064d7f8df3376fd4a53b17a2d0e7fb8bc6af2113d6bd3f`; the PostgreSQL manifest hash is `bf46547c0ed051075150a3d4c31b55173859102445524a67b29da100b19c1064`.

The initial focused regression retained 552 passes, 7 failures and 70 setup errors. These exposed a new test metadata mutation that was not supplied to the validator, and an older mock response whose CRLF bytes differed between the file and native records. Corrected test setup passed the focused probes and the complete frozen run. Production byte checks were not relaxed.

Independent read-only analysis also found a separate contract gap: the model may propose correct scoped conditions that the writeback layer cannot execute because it only accepts fixed limitation strings. That requires a versioned, evidence-bound condition registry and fresh independent reviews. This verified checkpoint does not claim that subsequent condition-registry code, a Decision approval, customer eligibility or Week11 completion has passed.
