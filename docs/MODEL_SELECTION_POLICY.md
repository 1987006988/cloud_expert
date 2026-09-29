# Model Selection Policy

The Week14 registry is `config/model_review/model_registry.yaml`. It ranks
approved review models by capability, and `resolve_review_model.py --probe`
verifies that the highest-ranked model responds through a read-only ephemeral
Codex CLI session. Fallback is disabled by default; an unavailable highest
model yields `BLOCKED`, not an automatic switch to a weaker model.

The configured highest model is `gpt-6-astra`, consistent with the
[official OpenAI model catalog](https://developers.openai.com/api/docs/models/gpt-6-astra).
The local 0.158.0 CLI completed a `max`-reasoning probe. This confirms runtime
availability, not approval of any cloud fact. The API/model alias did not expose
an immutable snapshot version, so `model_version=alias_unresolved` and the
release Gate remains blocked on version reproducibility unless the scoped
alternative below is actually verified. The alias is never relabeled pinned.

`config/model_review/review_authorization.yaml` separately controls transfer
of local Evidence excerpts to the external model. The environment's earlier
safety review rejected an unauthorized transfer. The project owner later
explicitly authorized official-source excerpts, mapping candidates, and
necessary identifiers for `gpt-6-astra` review; customer data and secrets
remain excluded. The pilot validates official source authority, HTTPS domain,
snapshot hashes, and the current deterministic precheck before transfer.
Authentication and model availability alone never authorize a dataset.

## Owner-Approved Internal RC Alternative

On 2026-09-30 the owner explicitly approved an alternative for internal release
candidates only: freeze review inputs, preserve complete model responses and
evidence hashes, rerun evaluation for every release, and disclose that the model
alias may change. See `config/model_review/reproducibility_policy.yaml`.

This is authorization for an auditable release method, not proof that its
requirements have already been implemented or verified. A valid audit bundle
must bind the candidate code, rules, prompts, data cutoff, evidence hashes,
actual model identity, isolated primary/adversarial/arbitration executions and
the fresh full-chain evaluation. Failed or incomplete bundles remain blocked.
It supports replaying the preserved decision record, not reproducing identical
future model outputs or asserting immutable model weights.

The policy does not permit production deployment, weaker-model fallback,
customer data transfer, customer output by default or a reduction of any fact,
price, citation, arithmetic or review threshold. Historical blocked reports are
retained. No model-version field may be invented to satisfy an old Gate.
