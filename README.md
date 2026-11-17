# DockScreen 0.2.0

![DockScreen](assets/dockscreen-logo.svg)

Prepare ligands from SMILES and screen them against one or more prepared receptors using an external AutoDock Vina executable. DockScreen provides a terminal menu and a non-interactive command for batch jobs.

The program includes RDKit/Meeko ligand preparation, bounded CPU allocation, per-calculation caching, docking poses, HTML reports, and CSV/JSON exports. Each receptor is evaluated independently. Docking scores are computational estimates, not measurements of activity or selectivity.

Version 0.2.0 adds per-task timeout outcomes, configurable CSV columns/names,
multiple receptor configuration profiles, per-profile hit tables and compact
result archives.
DockScreen is a preliminary release.

## Installation

Use Python 3.12 x64. AutoDock Vina is installed separately; no Vina binary is
included in this source repository. A separate Windows release ZIP can include
Vina.

Windows 10, PowerShell in the unpacked project directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py --version
```

Linux:

```bash
python3.12 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python main.py --version
```

Put a compatible Vina executable in `tools/`, or use one already on PATH. On Windows you can copy your existing `vina.exe`. On Linux use a Linux executable, not `vina.exe`; give it execute permission if required. Check it with `tools/vina --version` or `.\tools\vina.exe --version`.

For the terminal menu, configure `app_settings.json`:

```json
{
  "vina_executable": "tools/vina.exe"
}
```

On Linux use `"tools/vina"`, an absolute path, or `"vina"` if available on PATH.

## Input layout

```text
data/
  ligands.csv
  proteins/
    receptor_A.pdbqt
    receptor_B.pdbqt
  configs/
    receptor_A.txt
    receptor_B.txt
```

The receptor and its config must share a filename stem. Supply already prepared, scientifically appropriate receptor files. DockScreen does not prepare proteins.

The default ligand CSV schema is UTF-8 with `name,smiles` columns. Custom
schemas use `--smiles-column`, `--name-column`, `--name-mode`, `--delimiter`
or project-wide `data/ligand_import.json` (example under examples/).

```csv
name,smiles
ethanol,CCO
ethylamine,CCN
```

Comma, semicolon and tab separators and UTF-8 BOM are supported. A file with only `smiles` receives generated names. Quote fields containing the separator using standard CSV quoting. Names are labels, not file paths. The batch command preserves duplicate names as distinct numbered rows and uses chemical identity for caching.

Structures must be valid connected molecular graphs without unpaired radicals or open attachment atoms. Input validation does not establish chemical stability or synthetic accessibility. Preparation does not enumerate tautomers, protonation states or unspecified stereoisomers. Unsupported UFF parameters, failed embedding or nonconverged optimization can cause preparation failure.

Example receptor config:

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

Centers and box sizes are in angstroms. Use a box appropriate to your receptor, not these example coordinates. Command-line exhaustiveness controls the screening effort. A receptor config's explicit seed takes precedence over the default `--seed`. Effective options are retained in the result JSON.

## Configuration profiles and CSV naming

Multiple profiles can share one receptor: put configuration files under
`data/configs/RECEPTOR/PROFILE.txt` and select `--targets RECEPTOR@PROFILE`.
For example, `siteA_screen`, `siteA_deep`, `siteB_screen` and `siteB_deep`
are explicit profile names; the software does not infer their biological role.
The legacy `data/configs/RECEPTOR.txt` remains supported by `--receptors`.
When `--exhaustiveness` is omitted, the config value applies (fallback 8);
an explicit CLI value overrides it.

Custom CSV schemas use exact column names, for example
`--smiles-column Structure --name-column CompoundCode --delimiter tab`.
`--name-mode preserve` retains labels, `row` generates numbered names, and
`column-row` appends a row number to each label. Project-wide settings for the
menu can be saved as `data/ligand_import.json`; see `examples/ligand_import.json`.
Previously cached calculations may be recomputed after implementation changes;
the cache is not deleted during upgrades.

## CPU allocation

```json
{
  "cpu_budget": 4,
  "cpu_per_job": 1
}
```

Save this as `cpu_settings.json`. With four workers, this allows up to four simultaneous one-thread Vina jobs. More threads per job reduce the number of jobs that fit in the same budget. CPU settings are capped by detected CPU availability. The budget applies to one application process; it is not a global limit across separate jobs or nodes.

## Terminal menu

```powershell
.\.venv\Scripts\python.exe main.py
```

Select `1 Docking`, choose receptors by numbers or `all`, then choose ligands by numbers, `all`, or `write smiles` for manual input. The readiness summary appears before confirmation. Other menu items provide preparation, reports, history and cache management.

## Non-interactive screening

Check inputs first on Windows:

```powershell
.\.venv\Scripts\python.exe main.py --check --vina tools/vina.exe --receptors JAK1_3EYG JAK2_6BBV --cpu-budget 4 --cpu-per-job 1
```

Run the bundled ligand table:

```powershell
.\.venv\Scripts\python.exe main.py --run --vina tools/vina.exe --receptors JAK1_3EYG JAK2_6BBV --ligands data/ligands.csv --cpu-budget 4 --cpu-per-job 1 --workers 4 --exhaustiveness 8
```

Linux equivalent:

```bash
./.venv/bin/python main.py --run --vina tools/vina --receptors JAK1_3EYG JAK2_6BBV --ligands data/ligands.csv --cpu-budget 4 --cpu-per-job 1 --workers 4 --exhaustiveness 8
```

Paths passed through `--ligands` and a relative executable path passed through `--vina` are resolved against `--project`. `--project` defaults to the directory containing `main.py`. Omitting `--receptors` selects all receptor PDBQT files there. Use `--timeout` to set the timeout in seconds per Vina task, `--preparation-seed` for embedding, and `--no-html` to omit drawings on large runs. `--force-preparation` and `--force-docking` force the corresponding calculations.

Exit codes: `0` success, `1` setup or execution error, `2` completed screening with failed pairs, `130` keyboard interruption.

## Results and restarting

Each batch command writes a separate `output/runs/screening-.../` directory:

- `scores.csv`: every requested pair, including failed preparation/docking rows, with input name, SMILES, status and score in kcal/mol.
- `results.json`: successful pair results with effective options, cache identifiers, pose paths and input snapshots.
- `preparation.json`: preparation results and errors for each input row.
- `summary.json`: run settings, counts, CPU allocation and docking statistics.
- `input.csv`: exact input bytes captured before calculation for batch CSV runs.
- `report.html`: optional detailed report for successful results.
- `task_outcomes.json`: per-row/target status, including timeout failures.
- `hits/`: separate CSVs (`name,smiles,dG,Ki`) and protocol notes per target.
  Ki is a score-derived estimate in micromol/L; unrounded estimates <= 1 qualify.

Use `--export-zip results.zip` to export this completed run. The menu also lets
you choose a run. Result ZIPs include compact provenance and referenced poses,
excluding cache, history DB, unrelated runs and temporary files. They do not
include all source/prepared structures and are not calculation-cache backups.

Result archives require a `.zip` destination outside protected input/source/run
directories. Existing files are kept unless `--overwrite-zip` is explicitly
supplied; even then only a valid ZIP can be replaced. The menu asks before
replacing an existing archive. Export defaults to exclusive creation, so a
concurrent writer's file is not overwritten. Use a local filesystem supporting
hard links for this no-clobber export, then copy the archive if needed.

CSV text and dynamic headers are escaped for spreadsheet safety. Formula-like
strings receive a leading apostrophe; numeric scores remain numeric. Original
names and SMILES remain in JSON. Keep `*.csv.notes.json` beside each CSV:
DockScreen restores exactly one presentation prefix only when the file checksum,
schema and encoding policy match. Edited CSV/notes are rejected on mismatch;
ordinary unmarked inputs are not automatically dequoted. This also applies to
hit tables used for another docking run. A metadata checksum binds the notes to
the CSV bytes; it does not authenticate their author. CSV and notes are separate
atomic files, so an interrupted export may require regeneration of the pair.

Poses are under `output/docking_results/by_id/`; immutable input snapshots and prepared files are under `output/inputs/` and `output/prepared/`. Preserve these alongside JSON to retain calculation provenance. The calculation cache is `.calculation_cache/v1/`. Batch commands write file-based reports; the experiment-history database is populated by interactive docking runs.

Rerun the same command in the same project to reuse successful cached calculations. Failures are not reusable successes and are retried. A failure against one receptor does not discard successful pairs against another. A new CSV row order or changed display name does not change the molecular calculation key.

Keyboard interruption is not guaranteed to stop all Vina workers immediately. Forced termination may leave an unfinished task without a cache result or a batch without its final CSV. Already committed successful calculation entries remain reusable; repeat the command to rebuild the batch export. Do not delete the cache when restarting. Keep cache databases on local disk, not a shared network filesystem.

Changing input bytes, relevant settings, engine or preparation implementation can invalidate cache reuse. Lowering exhaustiveness changes the calculation protocol; do not silently mix protocols when interpreting results.

The detailed HTML report includes optional Ki/pKi conversions at **298.15 K**. These are score-derived estimates, not experimental affinities or a Vina simulation temperature. See [conversion limitations](docs/affinity_estimates.md).

## Cluster execution

Run one instance per allocated node/job, with `--cpu-budget` no larger than the allocated CPUs. The program runs CPU Vina locally; it does not use GPUs, MPI or automatically distribute work between nodes.

For multiple independent jobs, partition the input CSV and give each job its own project/output/cache directory. Do not run multiple application instances against one project directory. Separate jobs do not share a global CPU budget or latest-results export. Merge completed `scores.csv` files using stable compound identifiers; row numbers are local to each input partition.

An optional [Slurm template](examples/slurm_screening.sh) is supplied. Set its paths and resource requests to your cluster's rules before submission. It has not been submitted to a cluster as part of verification. Other schedulers require a corresponding job script.

Native RDKit/Meeko preparation currently has no process isolation or enforced wall-clock timeout. All pair tasks are held in memory, and complete CSV exports appear at the end. Large-scale throughput and memory use have not been validated; use measured, separate input partitions.

## Verification

Local checks do not require a Vina executable:

```bash
python -m pip install -r requirements-test.txt
python -m pytest -q
```

Run the separate technical check with real Vina:

```powershell
.\.venv\Scripts\python.exe verify_screening.py --vina tools/vina.exe --output screening_verification.json
```

It uses the bundled real receptors and two small preparation fixtures to check execution, poses, cache reuse, CPU allocation and isolation of a failed receptor. This is not a docking accuracy benchmark. No Vina simulator or Vina executable is bundled.

To check or build a source release:

```bash
python scripts/source_release.py --check
python scripts/source_release.py --output dist/DockScreen_0.2.0-source.zip
```

Only reviewed source paths and the bundled example dataset are included.
The build uses portable default settings, checks example hashes and excludes
local results, environments and development logs. `--directory NEW_FOLDER`
writes a clean project ready for repository initialization.

## Authorship and licensing

Sole software author and developer: **Kirill V. Karkhanin**. DockScreen is an independent project without scientific supervision. Original application code is under [MIT](LICENSE). Dependencies and structural data retain their own terms; see [third-party notices](THIRD_PARTY_NOTICES.md), [scientific references](docs/references.md) and [example provenance](docs/test_data.md). Dependency pins were retained from the verified environment; they are not a guarantee of installability on every platform or a complete binary-distribution license inventory.
