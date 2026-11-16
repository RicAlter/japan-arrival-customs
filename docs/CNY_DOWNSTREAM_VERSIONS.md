# Reviewed CNY cost revision: new downstream versions

The saved R2 CNY procurement-cost revision has been carried through the existing unified MVP into new R3-01 quantity, R3-02 price/tax, R3-03 carton/weight and R4-02 paired drafts. The prior task graph and outputs remain immutable. No new calculation or export implementation was introduced.

The local whole-batch run covers 2,861 shipment rows in their original order and carries all 63 authorized H-cell CNY display corrections. It preserves existing manual values, I, original K/L/M, formula caches, pictures, weight sheet and layout. Every ZIP member of the new internal workbook equals the saved R2 workbook; the container itself has a different SHA because the existing quantity exporter recompresses it. The R3-03 to R4 internal copy is byte-identical as required by the projection contract.

## Version transition

1. Read the R2 saved receipt and source in read-only mode; never invoke the old R2 handler with a new program binding.
2. Verify every source scope and stable worksheet/row. With no usable R1 mapping, bind explicitly to the R2 initial-file SHA and original row; do not join by JAN.
3. Reuse only coordinate-audited packaging, original invoice and carton evidence after scope equality is proved. Update each new binding to its actual upstream contract SHA.
4. Call quantity_conversion, price_tax, carton_weight and dual_projection through rebuild_mvp_v1 prepare in separate new directories. Each retains its own immutable code/source binding and current/resume checkpoints.
5. Read the joint pair receipt and run tools/verify_pair_acceptance.py against the actual initial-file roster. Keep the original warehouse-to-view row evidence as a separate provenance link.

The four new tasks run on the existing frozen 4b48d0d program. Later documentation commits do not rebind those tasks. All eight completed current/resume calls returned identical responses and left saved task/output bytes unchanged. The whole-batch acceptance found no missing, extra, duplicate or reordered rows and no unauthorized cell changes.

## Remaining business evidence

The combined pending file contains 77,413 overlapping field/reason records, not that many products. Unknown quantity units, packaging, typed procurement quotes, rates, customs-specific fields, dimension mapping and picture correspondence remain explicit. Clearer H-cell CNY text does not establish a physical package unit, exchange rate or tax rate. The original invoice total remains exact and independently retained; incomplete projected totals do not replace it.

Carton associations retain unique physical-box accounting. The four empty formula-template rows and related weight summaries remain pending; no rows were hidden to force source completeness. The CNY highest-cost rule does not apply to JPY or other currencies. No paused material/image query or download resumed.

Data readiness, operator/professional approval, formal output and overall R3/R4 completion remain false. New-file WPS display was not performed; prior screenshots cover only prior file hashes and their observed views. Technical verification uses code and original package parts, without Computer Use. Local business files, raw evidence and screenshots are excluded from GitHub.

Next work remains R4-03 field-evidence and operator/professional review. Accepted development, main, installed skills, formal database and historical tasks are unchanged.
