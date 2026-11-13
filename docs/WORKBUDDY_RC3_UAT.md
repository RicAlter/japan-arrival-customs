# WorkBuddy rc.3 isolated acceptance

Keep the existing rc.7 and rc.2 installations unchanged. The candidate has the same Skill name, so a second chat or a renamed extraction directory alone does not guarantee isolation. Use a verified separate profile/workspace scope, test user or VM. Do not replace the global same-name Skill. If only explicit script execution is possible, record that as script testing and leave native Skill loading unverified.

Requirements: Python 3.11+, `openpyxl==3.1.5`, local script execution, persistent readable attachment paths, and writable output outside both the input and installation directories. Node, database and web access are not required. Verify the actual interpreter and dependency from the WorkBuddy host; do not assume the default `python` command is suitable.

1. In the isolated environment, read the candidate's actual installation path and `arrival_core.__version__`; require `0.8.0-rc.3`. Run both `scripts/run.py --help` and `scripts/adapt_operations.py --help`, recording exits and output.
2. Upload the confirmed KMT business workbook and unpriced declaration-preparation workbook. The business workbook must include its weights sheet. Ask WorkBuddy to handle “处理已确认运营表” using the isolated candidate. The first request contains `message` and `files`; no unit confirmation yet.
3. Expect `needs_confirmation`, source identities, row count, required units, source bundle hash, special conversion hash and the full exceptional-conversion list. Do not summarize away items requiring scope confirmation. No workbook should exist at this stage.
4. After the operator verifies actual business/internal/declaration units and the entire displayed exception scope, WorkBuddy constructs `units_confirmation` with those unit values, a real reference, `confirm=true` and the two current hashes. Business and internal quantity units must agree. Do not substitute technical replay unit labels. If any exception remains disputed, stop and report it.
5. Use the candidate's original request entry:

```text
<explicit-python> -B <candidate>/scripts/run.py --output <separate-state/run-01> workbuddy --request <request.json>
```

For optional historical amount comparison, specify that workbook in `comparison_files` before the first preview. Adding it later changes the confirmation scope and requires a new preview. It never becomes the amount authority.

6. On `ok`, display both files in `pair/` as attachments and save them to a separate delivery directory, keeping the draft markers. Reopen the saved copies, verify format, pending price/tax cells and reconcile source amounts and carton totals. Compare SHA256 between each generated file and its saved copy. A successful disk write and a successful attachment download are separate checks.

Outputs include `standard/confirmed-arrival-v1.xlsx`, `evidence/provenance.json`, `batch.json` and `pair/` with its gate/comparison reports. Non-exact declaration prices and their calculated amounts remain blank, so a visible customs total may be incomplete. Do not fill those prices to force a total. Tax fields are expected blank in this adapter phase. Formal export remains closed.

## Failure evidence and rollback

Save each command, request, exit code, stdout/stderr and full response before retrying. Retain the preview, `input-problems.json` if produced, provenance, batch state and available `pair/gate_report.json`, `draft_comparison.json` and `draft_payload.json`. Some failures occur before these files exist. The candidate does not maintain a complete append-only error history; preserve host/tool output separately because input-problems may be replaced on another attempt.

Record file paths, runtime versions and whether the failure was intake, confirmation, rendering, display or saving. Keep logs protected; do not upload app databases, tokens or login settings. Preserve incomplete run directories and retry in a new run directory rather than deleting evidence or modifying code.

Rollback means stop the isolated session and disable/remove only that confirmed isolated candidate registration, or leave the test profile/user. Preserve test files for review. Return to the unchanged prior environment and verify its actual version. No database rollback or source overwrite is required when isolation has been maintained.
