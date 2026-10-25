# Known issues in the evaluated version

The publication candidate intentionally preserves the evaluated implementation. This document records observed behavior, not newly fixed features.

1. Unit propagation is incomplete in automatic table and vector paths. A schema field's presence is not evidence that its value was populated.
2. Empty zones can generate non-finite numeric text. Raster-path count can also be non-finite rather than zero in these cases.
3. Some cross-variable derived records have no supporting evidence identifiers. They should not be treated as verified environmental relationships.
4. Missing or undeclared NoData and float32 SD computation caused failures in predefined controlled scenarios. The pass proportion is not an estimate of real-world reliability.
5. Automatic variable/domain/time inference includes assumptions inherited from the original glacier-oriented implementation. Review inferred fields explicitly for other variables.
6. Custom identifier and row-specific time mappings require inspection; controlled examples exposed mismatches.
7. Reusing a build instance or an output directory can produce ID collisions, skipped records or extra evidence. Use a fresh project/output directory for controlled reconstruction.
8. A structural validator can finish with warnings. That does not establish numeric, semantic, license or training-readiness approval.
9. Administrative boundary enrichment requires separately supplied, licensed data in this publication distribution.
10. GUI, optional provider-backed query functionality, cross-domain transfer, human usability and downstream LLM training benefits were not evaluated by the manuscript experiments.

Any future repair must receive a distinct version or commit and new evaluation results. Historical counts must not be silently relabeled as results of a repaired implementation.
