# Review Runtime Remediation

This is a diagnostic progress record, not a model approval or Gate result.
No failed review is being retroactively accepted.

## Observations

The first actual Decision 9587 review retained a model rejection requesting
explicit scenario binding. Independently, CLI runtime validation found inherited
local command permissions, a skill catalog and authentication provenance in the
native session record. Ignoring user configuration did not remove those inputs.

A subsequent data-free probe used a private temporary authentication home and
an empty working directory. It removed all inherited command prefixes. Five
built-in skills still appeared: imagegen, openai-docs, plugin-creator,
skill-creator and skill-installer. A production review must disable that catalog
at its source and attest the actual resulting runtime, not merely requested flags.

The native record also includes a generated environment message and world-state
metadata. A separately reviewed adapter must validate their complete shape,
read-only permissions, model, working directory, time, and lack of inherited
context. Unknown or changed content remains blocking.

## Privacy Boundary

Original native bytes stay local and access-restricted. The only proposed local
metadata exception covers the direct session_meta payload's creator_user_id and
creator_account_id after complete isolation validation. It does not apply to
prompts, responses, stdout, nested lookalike fields or other private content.
Secret patterns are checked both in raw bytes and in decoded JSON strings.

An independent code review found a same-name nested-path collision and Unicode
escape bypasses in JSON values and keys. These were repaired. The focused
privacy suite now has 31 passing cases. This is not the complete checkout's
verification result; new full offline and PostgreSQL receipts are still required.

Native diagnostic files can contain account identifiers and historical local
permissions. They are not public delivery artifacts and must not be recursively
staged, printed or transferred to the model. Prior attempts remain unchanged.

## Clean Probe 03

The installed CLI requires exact SKILL.md file selectors, not their containing
directories, to disable the five built-in skills. Offline prompt rendering first
confirmed that distinction. Probe 02 retained its nonzero skill catalog and was
not accepted as clean.

Probe 03 actually executed gpt-6-astra at MAX effort, returned AVAILABLE with
exit code zero, recorded zero inherited command rules and zero skill-body
characters, and removed its private temporary runtime directory after capture.
Its local-only original native SHA256 is
`52e46183eb1a22d601a9a57a7dad9beda63c32a73c9b5bc1a3806fef45455f39`.
This is connectivity/isolation evidence only, not a Decision review or approval.

The ordinary registry availability probe was also migrated to the isolated
launcher. Fourteen synthetic tests cover exact response matching, context
isolation, execution failures, tool/error events and cleanup failure. It never
claims that connectivity alone verifies a model identity or approves a fact.
