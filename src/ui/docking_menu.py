"""One ordinary docking workflow; selections never modify the user's CSV."""
from src.preparation.inputs import read_ligand_rows, csv_options
from src.core.calculation_cache import molecule_identity

def parse_selection(text, size):
    text = text.strip().lower()
    if text in ("all","все","всё"):
        return list(range(size))
    tokens = text.replace(",", " ").split()
    if not tokens:
        raise ValueError("Enter numbers or all")
    indices = []
    for token in tokens:
        value = int(token) - 1
        if not 0 <= value < size:
            raise ValueError(f"The number must be between 1 and {size}")
        if value not in indices:
            indices.append(value)
    return indices

def docking_menu(app, console):
    proteins = [target['id'] for target in app.docker.get_targets()]
    if not proteins:
        raise ValueError("No receptors found in data/proteins")
    for i, protein in enumerate(proteins, 1):
        console.print(f"{i}. {protein}", markup=False)
    selected = [proteins[i] for i in parse_selection(console.input("Receptors: numbers or all: "), len(proteins))]
    for name in selected:
        if app.docker.get_config(name) is None:
            raise ValueError(f"No configuration file for {name}")
    path = app.project_root / "data" / "ligands.csv"
    rows = read_ligand_rows(path, **csv_options(app.project_root,path)) if path.exists() else []
    for i, (name, smiles) in enumerate(rows, 1):
        console.print(f"{i}. {name}: {smiles}", markup=False, soft_wrap=True)
    choice = console.input("SMILES: numbers, all, or write smiles: ").strip()
    if choice.lower() in ("write smiles","ввести","ввод"):
        rows = []
        console.print("Enter one SMILES per line; an empty line finishes input. 0 = cancel.")
        while True:
            value = console.input(f"SMILES {len(rows)+1}: ").strip()
            if value == "0":
                return
            if not value:
                break
            # Validate immediately, before any expensive calculation.
            molecule_identity(value)
            rows.append((f"manual_{len(rows)+1}", value))
    else:
        rows = [rows[i] for i in parse_selection(choice, len(rows))]
    if not rows:
        raise ValueError("No molecules selected")
    checked = [(name, molecule_identity(smi)[0]) for name, smi in rows]
    value = console.input("Exhaustiveness [configuration value, fallback 8]: ").strip()
    exhaustiveness = int(value) if value else None
    from src.docking.vina import validate_timeout
    timeout = validate_timeout(float(console.input("Vina timeout per task, seconds [3600]: ").strip() or 3600))
    workers = int(console.input("Concurrent jobs [4], within the CPU budget: ").strip() or 4)
    if workers < 1 or (exhaustiveness is not None and exhaustiveness < 1):
        raise ValueError("Exhaustiveness and the job count must be positive")
    force = console.input("Overwrite docking results? (yes/no): ").strip().lower() in ("да", "yes", "y", "д")
    from src.core.preflight import check_run, display
    readiness = check_run(app.project_root, proteins=selected, rows=checked,
                          exhaustiveness=exhaustiveness, num_workers=workers, docker=app.docker)
    display(readiness, console)
    if not readiness.ready:
        return
    console.print(f"Molecules: {len(checked)}; receptors: {len(selected)}; pairs: {len(checked)*len(selected)}")
    if console.input("Start docking? (yes/no): ").strip().lower() not in ("да", "yes", "y", "д"):
        return
    app.docker.timeout = timeout
    from src.ui.progress import WorkProgress
    prepared = {}
    selected_smiles = {}
    selected_metadata = {}
    inputs = []
    used_labels = set()
    failures = []
    with WorkProgress("Ligand preparation", len(checked)) as progress:
        for i, (name, smiles) in enumerate(checked, 1):
            label = name
            suffix = 0
            while label in used_labels:
                suffix += 1
                label = f"{i:04d}_{suffix}_{name}"
            used_labels.add(label)
            original_smiles = rows[i - 1][1]
            entry = {'row_id': i, 'label': label, 'name': name, 'smiles': original_smiles}
            try:
                record = app.converter.prepare_cached(smiles)
                prepared[label] = record["path"]
                selected_smiles[label] = original_smiles
                selected_metadata[label] = {"input_name": name, "selection_row_id": i}
                entry.update(status='prepared', preparation=record)
            except Exception as error:
                failures.append((name, str(error)))
                entry.update(status='preparation_failed', error=str(error))
            finally:
                inputs.append(entry)
                progress.advance()
    for name, error in failures:
        console.print(f"Preparation failed for {name}: {error}", markup=False)
    if not prepared:
        raise ValueError("No prepared ligands")
    exp_id = app.database.add_experiment(name=f"Docking {len(prepared)}x{len(selected)}",
        user_params={"exhaustiveness":exhaustiveness,"timeout":timeout,"workers":workers,"proteins":selected,
                     "molecules":checked}, description="Unified docking workflow")
    results = app.docker.run_docking(proteins=selected, ligand_paths=prepared,
        exhaustiveness=exhaustiveness, num_workers=workers, force=force)
    for name, proteins_data in results.items():
        for row in proteins_data.values():
            row["smiles"] = selected_smiles[name]
            row.update(selected_metadata[name])
    app.docker._save_results_json()
    from src.core.calculation_cache import atomic_json
    run = app.docker.last_batch_dir
    atomic_json(run / 'preparation.json', inputs)
    successful = sum(len(v) for v in results.values())
    atomic_json(run / 'summary.json', {'kind': 'interactive_docking', 'run_dir': str(run),
        'receptors': selected, 'input_rows': len(inputs), 'successful_pairs': successful,
        'failed_pairs': len(inputs) * len(selected) - successful,
        'exhaustiveness': exhaustiveness, 'timeout': timeout, 'workers': workers,
        'docking_statistics': app.docker.stats,
        'input_note': 'Selected input rows saved before canonicalization; original CSV bytes not snapshotted.'})
    from src.reporting.hits import export_hits
    export_hits(results, app.docker.last_batch_dir / 'hits', targets=selected)
    app._save_results_to_db(exp_id, results, exhaustiveness)
    app.database.finish_experiment(exp_id)
    reports = console.input("Generate reports? (yes/no): ").strip().lower() in ("да", "yes", "y", "д")
    admet = None
    if console.input('Add ADMET predictions to the docking results? (yes/no, default no): ').strip().lower() in ('да','yes','y','д'):
        try:
            from src.admet.workflow import enrich_run
            from src.reporting.admet import report_context
            result = enrich_run(app.project_root, run)
            console.print(f'ADMET: successful {result["successful_rows"]}; failed {result["failed"]}; '
                          f'cached structures {result["cache_hits"]}.', markup=False)
            if result.get('error'): console.print(f'ADMET: {result["error"]}', markup=False)
            admet = report_context(app.project_root, run)
            if result['successful_rows']:
                from src.reporting.pareto_csv import run_default_pareto
                console.print('Default Pareto user-default-v3: docking ≤−7 ↓; DILI ≤0.5 ↓; '
                              'ClinTox ≤0.5 ↓; hERG ≤0.5 ↓; Bioavailability_Ma ≥0.5 ↑ (model score, not a percentage). '
                              'Editable research scenario, not a clinical standard.', markup=False)
                try:
                    for selection in run_default_pareto(app.project_root, run):
                        console.print(f'Pareto {selection["target"]}: feasible {selection["feasible"]}, '
                                      f'front {selection["front"]}; {selection["directory"]}', markup=False)
                except Exception as error:
                    console.print(f'Pareto not generated: {error}. Docking and ADMET results retained.', markup=False)
        except Exception as error:
            console.print(f'ADMET incomplete: {error}. Docking results retained.', markup=False)
    if reports:
        app.generate_reports(exhaustiveness=exhaustiveness, run_dir=run, admet=admet)
