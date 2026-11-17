# Example screening inputs

The bundled table contains 40 ligand SMILES, with prepared JAK1_3EYG and JAK2_6BBV receptors and matching boxes. Both receptors are screened independently.

Windows example from the project directory:

```powershell
.\.venv\Scripts\python.exe main.py --check --vina tools/vina.exe
.\.venv\Scripts\python.exe main.py --run --vina tools/vina.exe --cpu-budget 4 --cpu-per-job 1 --workers 4 --exhaustiveness 8
```

On Linux use `./.venv/bin/python` and a Linux `tools/vina` executable.

The files are technical examples, not a validated activity/selectivity benchmark. Provenance, preparation limitations and structural stereochemistry are described in [docs/test_data.md](../docs/test_data.md). Keep ligand_sources.csv and receptor_sources.json when redistributing the examples. Receptor/config bytes must be preserved for their recorded hashes to remain valid. See the root README for your own CSV and receptor setup.
