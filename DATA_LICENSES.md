# Data sources and redistribution boundaries

Software, source data and generated text are separate research objects. Software licensing does not grant a right to redistribute third-party data or train models under conditions that the data provider does not authorize.

## HydroATLAS and BasinATLAS version 1.0

- Provider: https://www.hydrosheds.org/hydroatlas
- Dataset archive: https://doi.org/10.6084/m9.figshare.9890531
- Reference: Linke et al. (2019), https://doi.org/10.1038/s41597-019-0300-6
- HydroATLAS as a collective database is CC BY 4.0; its technical documentation states that component attributes retain their relevant CC BY 4.0 or ODbL conditions.
- The experiment uses level-6 BasinATLAS objects whose HYBAS_ID begins with 4, excluding invalid geometries. Original geometry/attribute files are not bundled here.

## WorldClim 2.1

- Data page: https://worldclim.org/data/worldclim21.html
- Conditions: https://www.worldclim.org/about.html
- Reference for the climate surface methodology: Fick and Hijmans (2017), https://doi.org/10.1002/joc.5086
- The provider states that the data are available for academic and other non-commercial use and that redistribution or commercial use requires prior permission. Publishing maps in academic research articles is allowed under the stated conditions.
- This candidate excludes WorldClim rasters and full real-data statistical/text outputs. Whether a particular derivative corpus or training use is permitted must be determined with the provider; no blanket derivative-data permission is assumed.

## Legacy administrative boundary layers

The local development directory contains Chinese administrative boundary and other imported GeoParquet files. Their source labels alone do not establish redistribution permission. All of these files and their local registry metadata are omitted from the publication candidate. Spatial enrichment therefore requires users to supply appropriately licensed layers.

## Synthetic examples and aggregate audit results

The minimal example explicitly uses invented values. Controlled-test arrays are synthetic, not field observations. Aggregate audit counts, numerical error summaries and timing measurements document software behavior and are separated from original environmental values. MIT covers the original software and its accompanying original documentation and demonstration scaffolding; it does not relicense any third-party source data or authorize restricted derivative-data reuse.

Conditions were checked on 2026-10-25. Recheck provider conditions when acquiring or reusing data. For uncertain permissions, obtain authorization rather than infer it from public download access.
