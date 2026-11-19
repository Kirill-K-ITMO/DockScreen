# Changelog

## 0.3.0 — prepared 2026-11-19

### Added

- Optional local ADMET after docking, or on saved DockScreen CSV reports, with
  isolated model execution, reusable predictions and per-row error reporting.
- ADMET columns and metric visibility controls in ordinary docking HTML reports;
  CSV retains every endpoint. Candidate dossiers include structures and properties.
- CSV-configured Pareto objectives and inclusive bounds, with reasons for exclusion.
- Optional preference-only SMAA-2 for all feasible complete candidates, including
  dominated rows: fixed desirability scales, Dirichlet weights, symmetric ties,
  rank acceptability and top-N fractions, seed and input provenance.
- Separate Pareto + SMAA and SMAA-only HTML summaries, CSV/JSON outputs and ZIP export.
- Import of saved docking CSVs without rerunning docking. Imported protocols are
  explicitly marked unknown; local ADMET does not trust old prediction columns.
- Readable dated document names and document indexes with hashes.
- Decorative rotating ASCII molecules above progress during ligand preparation,
  docking and ADMET; counters reflect completed work, with plain-log fallback.

### Changed

- Version 0.3.0; terminal menus and work panels are English.
- English and Russian main READMEs explain installation, workflows and interpretation.
- Editable global settings live in `settings/`; analysis settings stay with their run.
- `pyproject.toml` is the single dependency source; docking and ADMET use separate
  environments. Installation protects shared/linked environments.
- SMAA technical limit is 100,000 source rows. Scenario batching and memory guards
  remain applicable; the limit is not a performance guarantee.
- Default exploratory criteria: docking score <= -7 (minimize), DILI <= 0.5
  (minimize), ClinTox <= 0.5 (minimize), Bioavailability_Ma >= 0.5 (maximize),
  hERG <= 0.5 (minimize). Existing user criteria are preserved.

### Interpretation and scope

SMAA fractions describe sensitivity to sampled preferences with fixed predictions;
they are not probabilities of experimental success or clinical safety. Docking is
not measured activity. ADMET classifier scores are not percent bioavailability or
individual prediction accuracy. Reference compounds and prediction-error models
are outside this release. Model hashes record provenance, not a trusted signature:
only trusted locally installed model files should be used.

The GitHub source package contains no runtime, models, environments or user results.
Python and Python dependencies must still be installed.
