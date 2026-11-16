# R4-03 scoped local triage

The real saved CNY-cost pair has a new projection version using the same saved R2 and R3 contracts. The existing dual_projection entry consumes audited saved category/material cells as reviewed references, with source/header/full row-scope coordinates. It introduces no material search, image lookup, quantity inference or new calculation engine. The internal file is byte-identical to its parent; the customs draft changes only originally blank category/material cells. Existing values and formula caches remain intact.

## Read-only triage interface

`python tools/triage_pair_acceptance.py --request request.json --output NEW_DIRECTORY`

The request binds pair_source, parent_pair_source, acceptance_report and parent_acceptance_report. Report references contain path/SHA; both audits must have full same-version whole-batch technical coverage and no preservation errors. Parent and child must share the exact saved R2 and all R3 references and stable row order. The current pair is read through read_pair_source. The new output directory must be independent of inputs/old task directories; existing evidence is never overwritten.

Output contract `arrival-acceptance-triage/1` includes exact raw-record references, scoped unique issues, review cases, topic/code/field sets, full affected row identities, parent-to-child removed/added reasons, immutable pair/audit references, and the triage tool SHA. JSON and CSV outputs include reason totals, business questions, and every raw-to-case link.

Exact dedup uses complete original records, including messages, field, column, kind and row. Distinct causes are preserved even when a review case combines them. Quantity and its dependent price/result questions are consolidated by stable shipment identity. Same JAN never merges shipments. Weight-sheet rows and product-sheet rows have separate domains. Unknown codes remain explicit. Preservation failures cannot be relabelled as business questions.

Tax-rate and template-dimension questions are consolidated for presentation only, retaining all rows and separate fields. No common rate, unit or blanket permission is inferred; a reply must specify its actual applicable scope. Missing material and pictures remain paused. Existing image correspondence review is separately retained and not subtracted from the original pending-count denominator.

## Actual local scope

The local run projected 1,276 already-saved category values and 1,275 already-saved material values as references only. Original 77,413 overlapping missing/reason records become 74,862 after those 2,551 source-binding gaps are addressed. Exact identical duplicates are zero. All remaining records map to 8,527 scoped business-confirmation cases and two paused cause groups. Consolidation reduces repeated questions, not unresolved facts. Whole coverage is 2,861/2,861 rows with zero missing/extra/duplicate/reordered identities.

Business cases comprise 2,861 public/customs-field questions, 2,861 typed procurement-quote questions, 2,798 quantity/packaging/dependency cases, one tax-evidence question, one template-display question and five weight-page questions. G procurement options/numeric suffixes are not silently used as public specifications; channel is not brand and internal names are not customs names. Blank weight formula rows and summary remain pending.

The local review workbook has a summary, filterable scoped questions with reply/scope columns, and existing-field provenance. It is a review aid: editing a reply does not automatically save a business fact or mutate R2/R3. Raw trace links remain separate. Original data, manual values, formulas/cache and pictures are preserved; a preview is not WPS evidence. New-file WPS, operator/professional approval, data readiness and overall R4 completion remain false.

Business runs remain bound to the previous frozen program; this candidate adds only QA code, its tests and portable procedure documentation. Accepted development, main, formal installation/database and old tasks remain unchanged. Business files, raw evidence and screenshots stay local.
