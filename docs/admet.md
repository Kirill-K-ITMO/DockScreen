> Инструкция пользователя объединена в [README_RU.md](../README_RU.md). Этот документ содержит дополнительные технические сведения.

# Local ADMET and CSV-based selection

The preferred way to configure Pareto objectives and bounds is now an editable
CSV: menu item **15**, or `main.py --pareto-menu`. See [CSV selection](pareto_csv.md).
It produces candidate/front tables and a read-only HTML summary without browser
settings. Use the CSV workflow for new selections; the legacy combined report is retained only for compatibility.

ADMET is optional. It does not change docking preparation or repeat docking.
After interactive docking, the program asks `Generate reports?`, then asks
whether to add a local ADMET calculation. If accepted, the ordinary HTML/CSV
docking reports contain all available ADMET columns after the receptor score
columns. ADMET appears once per molecule, including for multiple receptors.
In HTML, the **Docking / ADMET** tabs control presentation. Docking opens without
the extra ADMET columns. The ADMET tab initially shows DILI, ClinTox and
Bioavailability_Ma; expand the metric selector to search, check other endpoints,
show all or hide all. Only column visibility changes; predictions, filters and
Pareto settings are not recalculated. CSV keeps every endpoint regardless of
the visible HTML columns. This works offline without a server.
Missing values stay blank/dash and status/error are shown. Reports are saved
under the selected run's `reports/`; endpoint units, model versions and warnings
are retained in the HTML details and CSV notes JSON. Later report generation
(menu4) can reuse matching saved ADMET without predicting again.

Successful ADMET also triggers the named `user-default-v3` Pareto preset for each
recorded receptor/profile/protocol independently: docking score <=-7 minimize,
DILI <=0.5 minimize, ClinTox <=0.5 minimize, Bioavailability_Ma >=0.5 maximize, hERG <=0.5 minimize.
The bioavailability threshold applies to the classifier score, not percent bioavailability. Exact criteria CSV
and results are stored under `run/pareto/`, with a `default_selections.json` index.
This is an editable exploratory example, not a clinical or pathology-specific
standard. Existing `settings/PARETO_CRITERIA.csv` is never overwritten. To apply your own
criteria use menu15; automatic selection uses the named preset, not an edited
global CSV. Failure of ADMET/Pareto preserves docking and allows docking reports.

Use a separate Python 3.12 x64 environment on Windows:

```powershell
.\.venv\Scripts\python.exe -m venv .venv-admet
python scripts/install.py --admet
.\.venv\Scripts\python.exe main.py --admet-run output/runs/SCREENING_RUN
```

Replace SCREENING_RUN with a completed run directory. Menu item 14 accepts
both batch screening and interactive menu docking. Older interactive runs with
saved row IDs/names/SMILES are imported into a new screening-import-* directory
without repeating docking; the source run remains unchanged. Legacy menu runs
saved canonical SMILES, not original CSV bytes; this limitation is recorded.
Runs with unrecoverable row identities are rejected instead of silently losing rows.
New interactive runs retain selected original SMILES and preparation failures.
Default: all original rows, batches of 16, CPU one
thread, no data-loader subprocesses; `--admet-timeout 600` limits each worker
invocation (probe and all missing predictions separately), not every molecule.
For best N: add `--admet-top 20 --admet-target JAK1_3EYG`. A target/profile is
mandatory for top N; incompatible protocols are rejected. Custom Python:
`--admet-python PATH_TO_PYTHON`. The base requirements do not include ADMET.
The model ensemble remains resident during prediction: batching limits input
work, not model memory. Large-library or 8 GB total-memory suitability has not
been established. Keep batches small and close other memory-heavy apps.

`admet.json`, `admet.csv` and its notes retain row identities, original SMILES,
structure policy, endpoint units/types/reference metrics, model hashes and
versions. Equivalent canonical isomeric structures share a calculation across
rows/receptors. Salts/disconnected graphs are rejected, no salt stripping,
neutralization, tautomer/protonation/stereoisomer enumeration is performed.
Specified stereochemistry, charges and isotopes are retained; unspecified
stereochemistry is not resolved. Atom maps are removed for model identity.
Worker RDKit may canonicalize the supplied model SMILES internally; both
installed RDKit versions and structure policy are retained in provenance.
Model/metadata/dependency/policy changes invalidate reusable predictions.
Failures are separate ADMET statuses; docking files remain intact. Repeat
runs retry failures and reuse successful predictions. One application instance
per project directory remains the supported mode.

Configure objectives and inclusive bounds with `settings/PARETO_CRITERIA.csv`
(menu15 or `--pareto-menu`), not by editing a browser report. Saved-run analysis
uses one explicit target/protocol; missing or nonfinite active values exclude
rows with a reason. Constraints precede exact nondomination. Equal candidates
remain; without objectives no Pareto ranking is claimed. Candidate tables and
read-only HTML are stored under a new `run/pareto/selection-*` folder. See
[CSV selection](pareto_csv.md) for the exact schema and commands.

Optional SMAA analyses all feasible complete rows, including dominated candidates,
using fixed scales and sampled preference weights; it creates CSV/JSON and a
standalone HTML summary. Combined Pareto + SMAA and SMAA-only presentation are
available separately. Templates and execution are separate actions in menu16;
see [SMAA](smaa.md). No new docking or ADMET prediction is needed for saved-run
selection. `--combined-report` remains a legacy compatibility operation.
`--export-zip results.zip` packages the selected run; `--overwrite-zip` is explicit.
Source packaging includes the integration and `pyproject.toml` dependency groups,
but excludes environments, model weights, local results and caches.

DILI/ClinTox <= 0.5 are editable user scenarios, not clinical standards. Classification
outputs, including DILI/hERG/Bioavailability_Ma, are model class scores, not
clinical risk probabilities or percent bioavailability. Docking is not measured
activity. Pareto membership does not establish a good or safe drug. Individual
uncertainty is not estimated; general model metrics are not molecule accuracy.
Negative reference R² for Half_Life_Obach/VDss_Lombardo is explicitly flagged.
ADMET-AI v2 may differ from v1 used in the paper/web app. No approval-status
bonus or clinical-data database is included. Preference-only SMAA is an optional separate saved-run analysis; see [SMAA guide](smaa.md).

Sources: [ADMET-AI 2.0.1](https://pypi.org/project/admet-ai/2.0.1/),
[upstream API](https://github.com/swansonk14/admet_ai/blob/main/admet_ai/admet_model.py),
[endpoint metadata](https://github.com/swansonk14/admet_ai/blob/main/admet_ai/resources/data/admet.csv),
[TDC Bioavailability](https://tdcommons.ai/single_pred_tasks/adme/#bioavailability-ma-et-al).
Runtime uses the installed package metadata and checksums, not mutable web data.

DockScreen docking CSV reports can also be imported and enriched via menu17 or
`--csv-analyze`; see [CSV report analysis](csv_analysis.md).

## Scientific citation

ADMET-AI: Swanson K et al., *Bioinformatics* 2024;40(7):btae416,
[doi:10.1093/bioinformatics/btae416](https://doi.org/10.1093/bioinformatics/btae416).
The paper describes v1; this integration installs v2, whose models were retrained.
The central [scientific references](references.md#optional-admet-and-preference-analysis)
also credit Chemprop v2, its representation method, PyTorch and the upstream TDC
datasets, and distinguish software versions from publication years.
