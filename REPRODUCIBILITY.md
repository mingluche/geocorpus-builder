# Reproducing the evaluated workflow

## What is preserved

The implementation's 50 Python files are unchanged from the historical source fingerprints. `reproducibility/historical_source_sha256.json` also records the original packaging metadata hash; the publication candidate changes only its Python requirement from 3.11 to 3.10 to match the executed environment. This metadata change is not a fix for the observed numerical or semantic defects.

Historical environment: Windows, Intel Core i5-14600K, 127.69 GiB RAM, Python 3.10.16. Recorded package versions include NumPy 2.2.6, pandas 2.2.3, GeoPandas 1.1.3, Shapely 2.0.6, Rasterio 1.4.3, PyArrow 24.0.0, Pydantic 2.12.5 and psutil 5.9.0. See `requirements-experiments.txt`. Timing is machine-dependent; exact repetition of the reported seconds is not expected.

## 1. Acquire the permitted inputs

First review the providers' current conditions in DATA_LICENSES.md. The manifest identifies the source URLs, selected files, versions and original checksums. Raw data are deliberately absent from this repository.

```bash
python experiments/2026-10-16/scripts/acquire_data.py --help
python experiments/2026-10-16/scripts/acquire_data.py --only all
```

The acquisition code requires HTTP byte-range support and refuses to silently download an entire multi-GB archive. Provider changes may require a documented acquisition adaptation. Do not replace missing files with invented data. The existing manifest is historical; make a copy before rerunning acquisition if original checksums are to be preserved.

## 2. Real-data cases

```bash
python experiments/2026-10-16/scripts/run_real_cases.py --manifest experiments/2026-10-16/data/real_case_manifest.json --output experiments/2026-10-16/results/real_reproduction --seed 2026 --n-base 100 --n-reuse 100 --sample-sizes 100,500,1000
```

Use a new output directory for each reproduction. The input vector is the HydroATLAS region-code-4 subset (`HYBAS_ID` beginning with 4), not all of geographical Asia; Siberia is separately coded. Of 2,489 selected objects, 138 invalid geometries were excluded without repair, leaving 2,351. `TableS4_excluded_geometry_ids.csv` lists the excluded identifiers. Geometry diagnostics can be regenerated from the original vector and the acquisition/validation code; no unrecorded historical diagnostic reasons are invented.

The independent reference uses explicit Shapely pixel-centre selection and NumPy float64 statistics. Continuous values satisfy `abs(observed-reference) <= 5e-5 + 1e-6*abs(reference)`; counts must match exactly. SD uses population variance. Empty zones are audited separately.

## 3. Controlled synthetic tests

```bash
python experiments/2026-10-16/scripts/run_controlled.py
```

The runner creates timestamped output under `experiments/2026-10-16/results`. The retained six-statistic recheck table uses the manuscript criterion. The original runner also saves a stricter rounded-reference diagnostic; its pass count must not be substituted for the manuscript's 359/432. The extended sum test is not part of the six-statistic denominator.

## 4. Performance

```bash
python experiments/2026-10-16/scripts/run_benchmarks.py --vector experiments/2026-10-16/results/real_reproduction/prepared/prepared_vector.gpkg --manifest experiments/2026-10-16/data/real_case_manifest.json --output experiments/2026-10-16/results/benchmark_reproduction --sizes 100,500,1000 --raster-counts 1,3,5 --repeats 4
```

The paper reports the median of runs 1-3 after the first observed run 0. OS file caches were not flushed or controlled. Peak RSS was sampled every 50 ms. Timed scope includes zonal statistics, table write/read, construction and file output; it excludes download, sampling, project initialization and independent references. A stage's independent median need not sum exactly to the median total time.

## 5. Record reconstruction

Repeat a build into three new project directories using identical statistics, configuration and templates, then calculate SHA-256 for both JSONL files. Stored historical hashes and the template-replacement result are provided in `reproducibility/audit_summary.json` and Table S3. These historical files support checking the reported outcome; restricted real-data corpora must be reconstructed locally from provider-authorized inputs.

## Supplementary evidence

- Table S1: eight-project record and quality denominators.
- Table S2: all 36 timings and the nine reported medians.
- Table S3: three identical-input reconstructions and one template replacement.
- Table S4: excluded geometry identifiers.
- Table S5: all 432 synthetic comparisons and their nine-by-six aggregation.
- Figure S1: passing comparisons by input variant and statistic.

Regenerate the workflow diagram and controlled-statistics matrix from the retained synthetic comparison table:

~~~bash
python reproducibility/make_figures.py --output regenerated_figures
~~~

The scripts in reproducibility/archival_figure_sources preserve the original other-figure sources. They refer to the original experiment layout and locally reconstructed real-data inputs, rather than constituting a new, fully portable one-command figure pipeline.

This archive does not contain a completed human semantic assessment, a conventional-script efficiency baseline or an LLM training experiment.
