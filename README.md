# DockScreen 0.3.0

![DockScreen](assets/dockscreen-logo.svg)

[Русская инструкция](README_RU.md)

DockScreen helps you prepare small molecules, dock them to prepared proteins, and explore the resulting candidates. Start with the numbered terminal menu; commands for repeatable runs are included below.

The four steps answer different questions:

| Step | What it does | What you get |
|---|---|---|
| Docking | Places a molecule in a chosen region of a protein and scores the poses | Poses and docking scores |
| ADMET, optional | Predicts selected absorption, distribution, metabolism, excretion and toxicity properties from SMILES | Model scores and predicted properties |
| Pareto, optional | Applies your limits, then removes a candidate if another is at least as good in every objective and better in at least one | A front and reasons for every exclusion |
| SMAA, optional | Repeats ranking with many possible preference weights | How often each candidate occupies each rank or enters your top-N |

These are computational decision aids. They do not establish measured activity, selectivity, clinical safety or a successful drug.

## 1. Install and open

1. Unpack the project into a writable folder. Keep the folders together.
2. Install **Python 3.12, 64-bit**, then run **INSTALL.cmd** and wait for it to finish. Internet access is needed to download packages. Installation creates `.venv` for docking and analysis. When it asks whether to install optional ADMET, answer `y` to create `.venv-admet` too. Answering no keeps docking available without ADMET.
3. Run **CHECK.cmd** to check the setup, then **START.cmd** to open the menu.
4. Enter a menu number and press Enter. Enter `0` to exit.

There is one dependency list: **pyproject.toml**, with the `docking`, `admet` and `test` groups. The installer reads that list. Two environments are intentional: the docking and ADMET engines need different versions of some libraries. Do not combine the groups into one environment.

AutoDock Vina is an external program. A Windows package may already contain `tools/vina.exe`. If yours does not, put a compatible Vina executable there and set its path in `settings/app_settings.json`:

```json
{"vina_executable": "tools/vina.exe"}
```

Paths inside that file are relative to the **project folder**, not the `settings` folder. The GitHub source package does not include Vina. On Linux use a native Linux Vina executable, such as `tools/vina`; a Windows `.exe` is not a native Linux executable. Preserve the applicable Vina licenses and notices when redistributing it.

<details>
<summary>Linux installation</summary>

Use Python 3.12 and a native Linux Vina executable. From the project folder:

```bash
python3.12 scripts/install.py --interactive
./.venv/bin/python main.py --check --vina /path/to/vina
./.venv/bin/python main.py
```

Replace `/path/to/vina` with its actual path; save it in `settings/app_settings.json`
for subsequent menu runs. The `.cmd` launchers are for Windows.

</details>

## 2. Find your files

```text
DockScreen-0.3.0/
  START.cmd                  open the menu
  INSTALL.cmd                install the environments
  CHECK.cmd                  check the setup
  pyproject.toml             one dependency list
  settings/
    app_settings.json        Vina executable path
    cpu_settings.json        CPU allocation
    ligand_import.json       optional custom molecule-CSV mapping
    PARETO_CRITERIA.csv      your editable Pareto criteria
    PARETO_PARAMETERS.csv    available-parameter catalogue, created when needed
    receptors/
      JAK1_3EYG.txt          receptor box/settings
      JAK2_6BBV.txt
  data/
    ligands.csv              molecule names and SMILES
    proteins/                prepared receptor .pdbqt files
    ligand_sources.csv       provenance of bundled molecules
    receptor_sources.json    provenance of bundled receptors
  tools/vina.exe             Windows docking executable, if supplied
  output/runs/               separate folders for saved runs
```

Use **settings/** for editable configuration and **output/** for results. Settings created for an individual run are under `output/runs/RUN/settings/`; exact settings used by an analysis are also saved with that analysis. Existing result snapshots are evidence of an earlier calculation: do not edit them to change a new analysis.

The bundled example contains 40 molecules and independently evaluated JAK1_3EYG / JAK2_6BBV receptors. It is a technical example, not a validated activity or selectivity benchmark. Keep the source tables when redistributing it. Receptor preparation and stereochemistry limitations are recorded in [example provenance](docs/test_data.md).

## 3. Run your first docking

1. Open **START.cmd**.
2. Choose **9 — Readiness check**. Resolve missing files before calculating.
3. Choose **1 — Docking**.
4. Select a receptor by its number, or `all` for all listed receptors.
5. Select molecules by their numbers or `all`. Read the readiness summary and confirm the run.
6. When asked **Generate reports?**, answer yes to get HTML/CSV reports.
7. The next question offers optional **ADMET**. Answer yes to add local predictions, or no to finish with docking alone.
8. Note the printed result path. Open the HTML in a browser or CSV in a spreadsheet.

Different receptors are evaluated separately. A failure for one receptor does not erase successful results for another. Each run has a separate folder inside `output/runs/`.

**Reading a score:** for the same receptor and compatible protocol, `−8` is a lower, more favourable docking score than `−6`. The minus sign matters. A score limit `≤ −7` admits `−8` and rejects `−6`; exactly `−7` passes. A docking score is not a measured binding affinity. Any displayed Ki/pKi is a score-derived estimate, not an independent experiment.

## Work progress

Terminal menus and panel labels are in English.
During ligand preparation and docking, a rotating abstract ASCII molecule appears
above the completed-work progress bar. The bar advances only after a task finishes,
not with each animation frame. The same molecule is used for ADMET.
The ADMET panel shows the real progress bar, phase,
cache count, failures and elapsed time. It is decorative, not the current candidate.
Environment checks and model loading do not display invented percentages. Prediction
counts advance after completed batches and refer to unique structures. Redirected
output and limited terminals use plain phase/count messages. Set
DOCKSCREEN_NO_ANIMATION=1 to disable motion.

![Interface preview — sample numbers](assets/admet-panel-preview.gif)

## 4. Use your own molecules and receptor

Replace or copy `data/ligands.csv` with a **UTF-8 CSV**:

```csv
name,smiles
ethanol,CCO
ethylamine,CCN
```

`name` is your label; `smiles` describes the structure. Duplicate names remain separate numbered rows. Comma, semicolon and tab separators are supported for molecule input. If a field contains the separator, quote it using normal CSV rules. Custom headers can be configured in `settings/ligand_import.json`; an example is in `settings/examples/ligand_import.json`. A CSV containing only molecule SMILES is a docking input, not an already completed docking report.

For a new receptor, put a **prepared** `MY_RECEPTOR.pdbqt` in `data/proteins/` and its box file `MY_RECEPTOR.txt` in `settings/receptors/`. Names must match. DockScreen prepares ligands, **not proteins**. Choose box coordinates for your binding site; copying example coordinates onto another protein does not locate that site.

```ini
center_x = 10.96
center_y = 14.23
center_z = -14.78
size_x = 20
size_y = 20
size_z = 20
scoring = vina
seed = 42
cpu = 1
```

Those coordinates illustrate the format only; lengths are in angstroms. For several sites/settings on one receptor, use `settings/receptors/MY_RECEPTOR/PROFILE.txt` and select `MY_RECEPTOR@PROFILE` in the command line.

## 5. Add ADMET later, without repeating docking

Choose **14 — Local ADMET / HTML report**, select a saved run, then choose prediction for all molecules or best N for one target. “Report only” uses already saved matching ADMET. It does not predict missing values.

The ordinary docking HTML has **Docking / ADMET** tabs. In ADMET, open the metric selector to search and choose columns. By default it shows DILI, ClinTox and Bioavailability_Ma. This changes the display only; CSV retains all available predictions.

**Example:** `Bioavailability_Ma = 0.70` is a classification-model score on a 0–1 scale. It is **not 70% oral bioavailability**, nor a verified 70% chance of success. Larger values favour the model's positive class. DILI, ClinTox and hERG are also model signals; smaller values are preferred in the default scenario. They are not calibrated individual clinical-risk probabilities.

Predictions are local and may reuse the project's matching cache. An invalid structure or failed prediction keeps an error status; it does not become zero. ADMET-AI is heavy: input batching does not remove the model ensemble from memory.

## 6. Choose Pareto goals and limits

Choose **15 — Pareto selection from CSV** and select a saved run. The program supplies an editable criteria CSV and a parameter catalogue. Edit the CSV, save **CSV UTF-8**, then run item 15 again and apply it to one target/protocol. You do not repeat docking or ADMET.

The default scenario **user-default-v3** is:

| Parameter | Allowed values | Prefer |
|---|---|---|
| docking_score | ≤ −7 | smaller |
| DILI | ≤ 0.5 | smaller |
| ClinTox | ≤ 0.5 | smaller |
| Bioavailability_Ma | ≥ 0.5 | larger |
| hERG | ≤ 0.5 | smaller |

These are editable screening choices, not clinical standards. Equality passes. A missing active value excludes the row with a reason. **Zero acceptable candidates is a valid result**: inspect the reasons or deliberately revise your criteria; the program does not silently loosen them. A run of the bundled 40-molecule example can produce an empty set under these five limits.

The criteria CSV uses these Russian values in both language versions:

| Column | What to enter |
|---|---|
| Параметр | Exact ID, for example `DILI` |
| Использование | `сравнивать` = objective; `ограничение` = filter only; `не учитывать` = ignore |
| Направление | `минимум`, `максимум`, or `диапазон` for an objective |
| Не ниже / Не выше | Inclusive lower / upper limits; blank means no limit |
| Цель от / Цель до | Desired interval for `диапазон`; distance is zero inside it |
| Пояснение | A note; it does not change calculation |

For Bioavailability_Ma ≥0.5, enter `0.5` in **Не ниже**. For hERG ≤0.5, enter `0.5` in **Не выше**. For docking ≤−7, enter `-7` in **Не выше**. Do not put a threshold into the desired-interval columns.

The generated delimiter is `;`. If Excel puts everything into one column, import “From Text/CSV”, select UTF-8 and semicolon. Keep the parameter IDs unchanged. To add another parameter, copy its row from the catalogue. Repeated IDs are rejected.

**What is a front?** Ignoring limits just for this illustration, compare docking (smaller) and bioavailability score (larger): A=`(−8,0.4)`, B=`(−7.5,0.6)`, C=`(−7,0.3)`. A and B trade advantages, so both are on the front. A is better than C in both objectives, so C is dominated. Pareto alone assigns no weights and declares no single winner. Several objectives can leave a large front.

Outputs are under `RUN/pareto/selection-.../`: `front.csv`, `feasible.csv`, `all_candidates.csv`, exact criteria/settings, and a read-only `report.html` with candidate dossiers. User criteria are applied through item 15 or an explicit CLI path; automatic post-docking selection uses the named default scenario, not a silently edited global file.

## 7. Explore preferences with SMAA

Choose **16 — Pareto + SMAA**. First create a settings template, inspect it, then select the separate action to execute. The same criteria CSV controls objectives and limits. Only one target/protocol is analysed at a time.

SMAA considers **all** acceptable candidates, including dominated rows. It holds their predicted properties fixed and varies how much each objective is valued. For every candidate it saves the share of scenarios at first place/top-N, mean and median rank, rank quantiles and the complete rank distribution.

**Example:** a top-5 share of `0.65` means 65% of the sampled preference scenarios allocated that candidate a top-5 place. It does **not** mean a 65% probability of experimental success. Three exactly tied candidates competing for first place each receive `1/3`, independent of row order. Excluded rows have blank/null SMAA metrics, not last place. If you request top-10 with only six acceptable candidates, the applied N is six.

The separate JSON contains `worst` (desirability 0), `best` (desirability 1), and `alpha` for every objective. For example, a decreasing docking scale with worst=`−6`, best=`−10` gives score `−8` desirability `0.5`. Values outside the anchors saturate at 0/1. For a target interval, the scale describes distance from that interval, with best distance 0.

Automatic anchors use observed values for the chosen protocol **before limits** and remain fixed in the saved JSON. Constant data use an explicitly recorded expansion; an all-inside target interval uses worst distance 1. Check these exploratory scales before interpreting results. Creating a new template after changing criteria is an explicit action; preserve anchors if comparing only the effect of changed limits.

Default weights are **Dirichlet(alpha=1)**, uniform on the weight simplex; that is a chosen preference assumption, not an absence of assumptions. Scores are added after scaling. Such a model allows compensation between properties inside the accepted set. Correlated endpoints can reinforce overlapping information. Clipping can turn raw dominance into equal desirability. Exact float64 ties share rank positions; quantiles use the inverse discrete rank CDF.

Results are in `RUN/smaa/analysis-.../`: start with `SUMMARY.txt` and `candidates.csv`; `results.json`, `rank_acceptability.csv`, copied settings, source hashes and method/library versions support reproduction. Seed and scenario count are recorded. Monte Carlo standard errors quantify numerical integration of preferences, **not** ADMET prediction errors. No unsubstantiated property-error model is added.

## 8. Already have a DockScreen docking CSV?

Choose **17 — CSV report → ADMET / Pareto / SMAA**, select your report, then choose ADMET only, ADMET + Pareto, ADMET + SMAA, or ADMET + Pareto + SMAA. Docking and conformer preparation are not repeated. A new `output/runs/csv-import-.../` retains the original CSV and optional sidecar; source files stay unchanged.

This accepts DockScreen's native report CSV, not arbitrary spreadsheets: `name`, `smiles`, `<target>_delta_g` and companion Ki/pKi columns must be present. It uses the docking score, ignores imported ADMET numbers as verified predictions, then runs the usual local ADMET pipeline with its cache policy. CSV cannot restore a complete docking protocol or extra score precision: the imported protocol is explicitly marked unknown. Prefer the original saved JSON run when available.

Keep `report.csv.notes.json` next to `report.csv`. The checksum-bound marker permits reversible decoding of protected text. A mismatch is rejected. Without it, text is preserved literally, including apostrophes that may affect SMILES. A checksum does not authenticate the author of a file.

Automatic SMAA in item 17 announces and saves observed fixed scales, alpha=1, 10000 scenarios, seed=42 and top-N=10. To inspect scales first, use **import only** through CLI, then items 14, 15 and 16 separately.

## HTML and readable document names

HTML is generated automatically after a successful analysis. Item 15 produces
Pareto HTML. In item 16 choose 2 for Pareto + SMAA, or 3 for SMAA only. In item 17,
option 4 runs ADMET + SMAA; option 3 runs ADMET + Pareto + SMAA. CSV constraints
apply in either mode; SMAA ranks the entire feasible set, not just the front.
SMAA-only does not produce a separate Pareto report. Empty results still have an
HTML report explaining exclusions, without invented ranks.

Open the HTML path printed at completion. Each analysis has a `documents/`
folder containing readable copies of the report, tables, results and settings.
`INDEX.json` lists their names and checksums. Short canonical names such as
`results.json` and `criteria.csv` remain stable for the program. Existing analyses
are not renamed automatically.

Example: `SMAA__2026-11-18_18-30-00Z__JAK2_6BBV__a1b2c3d4__report.html`.
Fields are type, UTC date/time (Z), target, short analysis ID and document role.
A shared ID groups documents from the same analysis. Unsafe target characters
are replaced. Types include DOCKING, DOCKING-ADMET, ADMET, PARETO, SMAA,
PARETO-SMAA, HITS and RESULTS (ZIP). ADMET uses molecular-properties because
these predictions are receptor-independent; combined targets use multiple-targets.
Editable settings keep stable names under `settings/`.

Keep CSV and its paired `.csv.notes.json` together; do not rename only one file.
ZIP includes the named documents and index. For CLI SMAA-only use `--smaa-run`
with `--smaa-only`. CSV mode `--csv-analysis-mode smaa` runs local ADMET + SMAA
without a separate Pareto report.

## 9. Save results and troubleshoot

Use **6 — Export ZIP** for the selected run. A result archive includes compact provenance, reports, applicable poses and completed analyses; it excludes environments, model weights and cache. It is not a full cache backup. Keep source JSON, receptor/box files and referenced poses when retaining the complete calculation record.

- **“No completed runs”**: finish docking, or import a native report using item 17. A plain ligand CSV is not a completed run.
- **Empty Pareto/SMAA set**: read exclusion reasons; a strict limit or missing active property may exclude every row.
- **ADMET fails**: check `.venv-admet`, the reported error and available RAM. Docking results remain saved.
- **Vina not found**: check `tools/vina.exe` and `settings/app_settings.json`, then run CHECK.cmd.
- **Too much memory**: reduce the feasible SMAA set with meaningful criteria, or partition docking input into independent runs. Merely displaying fewer rows does not reduce the calculation.
- **Interrupted**: Ctrl+C stops between calculation batches where supported. Completed cache entries can be reused. An incomplete SMAA is not published as successful.

Use one application instance per project directory. CPU budget applies to that instance, not to every program on the computer. In `settings/cpu_settings.json`, `{"cpu_budget":4,"cpu_per_job":1}` permits up to four one-thread Vina jobs when the worker count is four. Raising threads per job reduces simultaneous jobs.

## Commands for saved or automated runs

Open PowerShell **in the project folder**. These Windows examples use the environment made by INSTALL.cmd:

```powershell
# Check and dock the bundled examples.
.\.venv\Scripts\python.exe main.py --check --vina tools/vina.exe
.\.venv\Scripts\python.exe main.py --run --vina tools/vina.exe --ligands data/ligands.csv --receptors JAK2_6BBV --cpu-budget 4 --cpu-per-job 1 --workers 4 --exhaustiveness 8

# Copy the printed run path into $run; replace this example placeholder.
$run = "output/runs/YOUR_SAVED_RUN"
.\.venv\Scripts\python.exe main.py --admet-run $run
.\.venv\Scripts\python.exe main.py --pareto-run $run --pareto-criteria settings/PARETO_CRITERIA.csv --pareto-target JAK2_6BBV

# Create a NEW scales file, inspect it, then run SMAA separately.
.\.venv\Scripts\python.exe main.py --smaa-template $run --pareto-criteria settings/PARETO_CRITERIA.csv --smaa-settings "$run/settings/MY_SMAA.json" --pareto-target JAK2_6BBV
.\.venv\Scripts\python.exe main.py --smaa-run $run --pareto-criteria settings/PARETO_CRITERIA.csv --smaa-settings "$run/settings/MY_SMAA.json" --pareto-target JAK2_6BBV

# Or analyse a native saved docking report in a new imported run.
.\.venv\Scripts\python.exe main.py --csv-analyze "C:/my_reports/report.csv" --csv-analysis-mode pareto+smaa --pareto-target JAK2_6BBV
# Import alone: add ADMET and inspect scales later through items 14/15/16.
.\.venv\Scripts\python.exe main.py --csv-import "C:/my_reports/report.csv"
```

Use `--pareto-protocol ID` if a target has several protocols. Add `--export-zip results.zip` to a supported calculation/analysis command; an existing ZIP needs `--overwrite-zip`. `--pareto-template RUN --pareto-criteria NEW.csv` creates criteria separately. `python main.py --help` lists options. On Linux, in an appropriately installed environment, replace `.\.venv\Scripts\python.exe` with `./.venv/bin/python` and select the native Vina executable.

<details>
<summary>Technical limits, provenance and verification</summary>

Up to 100000 input rows is an input-size limit, not a guarantee of ranking 100000 feasible alternatives. Dense SMAA rank accumulation needs O(n²) memory for the **feasible** set. Its estimate is checked against 256 MiB before allocating that matrix; total process memory can be higher. Limits also apply to scenarios/objectives/batch sizes; check saved configuration. Large-library throughput has not been validated.

The installer refuses to modify shared environments connected by links. Install into a clean folder for a separate installation.

Native RDKit/Meeko preparation has no enforced process wall-clock timeout. Vina tasks have configurable timeouts. Cache reuse depends on molecular identity, engine, settings and implementation. Keep caches on local storage; partition independent cluster jobs into separate projects, outputs and caches. There is no GPU/MPI or automatic multi-node distribution. [Slurm example](examples/slurm_screening.sh) needs adaptation to your scheduler.

Preparation does not select pH-dependent microstates, enumerate tautomers/stereoisomers or repair unsuitable proteins. A connected valid structure is not evidence of chemical stability. The included technical receptor example has documented preparation gaps. Score-derived Ki/pKi uses 298.15 K as a conversion parameter, not a Vina simulation temperature; see [conversion details](docs/affinity_estimates.md).

SMAA checks source hashes before/after reading and before publishing. It records fixed scales, exact criteria, PCG64, Dirichlet parameters, seed and method/library versions. Identical numerical reproduction needs the same inputs and computation environment; timestamps/UUIDs differ. Temporary incomplete analyses are not exported as successful.

Testing instructions and dependency groups are defined by the project tooling. The tests and real-Vina verification check technical behaviour, not scientific prediction accuracy. `.\.venv\Scripts\python.exe verify_screening.py --vina tools/vina.exe` runs a small technical docking check. Source packaging uses `scripts/source_release.py`; publication is a separate action.

Method references: [SMAA-2](https://doi.org/10.1287/opre.49.3.444.11220), [implementing SMAA](https://doi.org/10.1016/j.ejor.2005.12.037). Scientific sources, model limitations and example-data attribution remain in [references](docs/references.md) and [data provenance](docs/test_data.md).

</details>

## Author and licenses

Sole software author and developer: **Kirill V. Karkhanin**. Original application code is under [MIT](LICENSE). Preserve [AUTHORS.md](AUTHORS.md), [CITATION.cff](CITATION.cff), [third-party notices](THIRD_PARTY_NOTICES.md), [licensing details](docs/licensing.md), and the applicable files in `licenses/`. Dependencies, AutoDock Vina and structural data retain their own terms.
