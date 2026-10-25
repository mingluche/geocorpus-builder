# GeoCorpus Builder

GeoCorpus Builder converts geographic attributes and zonal statistics into quantitative text records linked to evidence records. It provides a reusable preparation workflow for environmental language-model corpora. Text generation uses deterministic rules and templates; it does not require an LLM API.

## Publication release

This repository candidate accompanies the manuscript **GeoCorpus Builder: Software for constructing environmental quantitative text corpora for language-model training**. The implementation is version 0.1.0. The 50 Python source files match the archived implementation evaluated in October 2026. Packaging documentation and the Python installation declaration are prepared separately from the historical evaluation.

The original software is released under the MIT license. Versioned source and a wheel are provided through the GitHub release; a separate permanent archive DOI has not yet been assigned. Do not interpret the software license or public download access as permission to redistribute third-party geodata.

## Installation

Python 3.10 or later is declared in the publication package. The historical experiments used Python 3.10.16; compatibility with every later Python/dependency combination is not implied. Install from the repository root:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e "./geocorpus-builder[spatial]"
geocorpus --help
```

The spatial extra is used for the manuscript workflow and CLI imports. Optional GUI and provider-backed query dependencies are available through the existing `gui` and `rag` extras. They are not required by the example below and were not evaluated in the paper. No administrative boundary database is bundled in this publication candidate.

## Reproducible synthetic example

The example contains invented values for two explicitly fictional objects. It demonstrates record construction and evidence linkage, not environmental observations or model-training performance. Use a new output directory:

```bash
python examples/minimal_quantitative_corpus.py --output demo_run
python -m unittest discover -s tests -v
```

Expected construction: four basic records, one comparison record and four evidence records. The script checks numeric values, object identifiers and resolvable basic evidence links. It also reports, rather than conceals, the implementation's empty physical-unit metadata. A smoke-test result is not a guarantee that all corpus records are ready for training.

## Inputs and outputs

| Input | Processing | Main output |
| --- | --- | --- |
| Vector attributes | Read object identifiers, geometry and selected numeric attributes | Text and evidence records |
| Numerical rasters and zones | Pixel-centre zonal statistics, followed by table-based construction | Statistics tables, text and evidence records |
| CSV or Parquet statistics | Read existing statistics without recomputing them | Text and evidence records |

`corpus/corpus_units.jsonl` stores text, object and variable context, and evidence identifiers. `evidence/evidence_links.jsonl` stores the associated source table, object, statistic and numeric value. Schema support does not guarantee that every field is populated correctly by every input route.

## Reproducing the paper

See [REPRODUCIBILITY.md](REPRODUCIBILITY.md) for the acquisition, case, controlled-test and benchmark commands. The retained directory layout keeps the original evaluation scripts' relative imports working:

```text
geocorpus-builder/          Python distribution and unchanged implementation
examples/                  Synthetic, API-free quick start
tests/                     Publication-package smoke tests
experiments/2026-10-16/     Original evaluation scripts and selected audit summaries
reproducibility/           Source fingerprints, supplementary tables and figures
```

The historical evaluation emitted 19,000 basic and 7,086 derived records across eight projects, including duplicate facts across input formats and records with known quality defects. Of 432 controlled statistic comparisons, 359 passed the paper's criterion. These are retained historical findings, not results of an undisclosed new experiment. The publication preparation step only reaggregates the stored audit records and performs separately identified smoke tests.

## Data and license boundaries

Original software and documentation are distributed under [MIT](LICENSE). Dataset conditions remain separate.

Read [DATA_LICENSES.md](DATA_LICENSES.md) before acquiring or sharing data. WorldClim rasters, real-data statistical tables and full real-data corpora are not included. The download scripts and source manifest allow readers to obtain permitted inputs from their providers. The legacy Chinese administrative boundary files are also excluded pending redistribution clearance. A software license cannot override third-party data restrictions.

## Quality and limitations

See [KNOWN_ISSUES.md](KNOWN_ISSUES.md). Important issues include incomplete unit propagation, non-finite text for empty zones, and missing evidence in some cross-variable derived records. Existing query and GUI functionality is outside the manuscript evaluation. Downstream LLM training gains have not been tested.

## Citation and contact

Citation metadata is provided in [CITATION.cff](CITATION.cff). No publication DOI or archive DOI is invented. The manuscript authors are Minglu Che, Yuanming Hu, Jiarong Zhong, Jie He, Yanlong Guo and Yanyun Nian; the first two authors contributed equally. Correspondence: Yanlong Guo, guoyl@itpcas.ac.cn.

## Contributing

Please include a small reproducible input, expected behavior, actual output, software versions and relevant logs in an issue. Never attach access tokens or restricted source data. See [CONTRIBUTING.md](CONTRIBUTING.md).
