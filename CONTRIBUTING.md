# Contributing

Discuss a proposed behavioral change before submitting it. Include a minimal reproducible test and record whether it changes statistical definitions, pixel selection, missing-value handling, rounding, metadata propagation or output identifiers. Separate fixes from archived paper results.

Do not commit credentials, private paths containing secrets, original third-party geodata, provider-restricted corpora or downloaded binaries. Use synthetic inputs in tests. Preserve attribution and dataset conditions.

The evaluation implementation and publication-preparation scripts serve different purposes. Code changes require a new provenance fingerprint and, where relevant, rerun experiments. Documentation corrections do not retrospectively repair previously generated records.
