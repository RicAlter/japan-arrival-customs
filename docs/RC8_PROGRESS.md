# rc.8 progress checkpoint

## Source scope

This branch continues the frozen rc.7 commit `b93ce6e` and records the rc.8 confirmed-input, three-level gate, and operations-adapter work through `0.8.0-rc.3`. It is a source checkpoint, not a deployment or formal-release approval. Existing rc.7/rc.2 installations and local evidence are retained separately.

- `confirmed-arrival-v1` accepts traceable batch facts and uses the existing calculation/rendering modules.
- Input integrity, controlled-draft availability and formal customs release are reported separately. Missing formal fields do not uniformly block drafts. Missing tax parameters leave tax results blank.
- KMT operations intake recognizes the business-confirmed and declaration-preparation workbook structures using independent mapping JSON. Operators do not manually create a three-sheet standard input.
- The first call returns a source-bound preview and the complete exceptional quantity-conversion list. A subsequent explicit batch unit/scope confirmation must match both hashes.
- Field evidence records original file hash, worksheet, row, cell, formula, cache and exact arithmetic precedents. Ambiguous identities, unsupported formulas, missing or mismatched caches, conflicting facts and stale confirmations are rejected.
- Business amounts remain authoritative. Optional historical output comparison is evidence-only and cannot override them. Non-exact declaration prices remain blank; no automatic tail adjustment is introduced.
- Both workbooks are controlled drafts generated from one state and verified after save. Formal output remains unconditionally disabled. No database, website or new review UI is added by the adapter.

## Verification

The local candidate passed 89 tests with the explicitly supplied private raw-workbook path. The source-only checkout normally skips that one optional test when the private file is unavailable; synthetic fixtures remain runnable without business assets:

```powershell
python -B -m unittest discover -s tests -v
```

Private full-sample replay also verified all mapped rows, exceptional conversions, non-exact prices, evidence-only historical amount differences, and physical carton/weight reconciliation. Business totals, row identifiers, file hashes, source paths, comparison records and generated workbooks are intentionally omitted here. The older independent regression suites were not rerun as part of this checkpoint and are not claimed as covered by these tests.

## WorkBuddy status

The operator reported isolated candidate installation, complete release-manifest hash verification and initial source-status smoke success. The installed legacy rc.7 was reported unchanged. Business intake, actual units/scope confirmation and workbook display/save have not yet been accepted with a live business batch. Development is paused pending that batch.

Use `workbuddy --request` for the operations intent. `workbuddy-route` does not list this new intent; it is dispatched in `workflow.execute`. This known routing gap has not been silently fixed during acceptance preparation. Explicit interpreter selection may be required when the host's default Python lacks the pinned dependency.

## Deliberate exclusions

No real inputs, historical workbooks, batch JSON, per-row reports, product/decision databases, tokens, local settings, personal paths, screenshots, generated archives or operational logs are included. Source provenance at runtime is retained only in protected local output. The next action is user-run WorkBuddy acceptance, not further feature expansion.
