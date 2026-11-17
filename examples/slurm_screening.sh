#!/usr/bin/env bash
#SBATCH --job-name=dockscreen
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=4G
#SBATCH --time=24:00:00
#SBATCH --output=dockscreen-%j.log

set -euo pipefail

# Use a separate project/output/cache directory for each concurrently running job.
: "${DOCKSCREEN_PROJECT:?Set the absolute path of this job's project directory}"
: "${DOCKSCREEN_PYTHON:?Set the absolute path of the environment's Python executable}"
: "${DOCKSCREEN_VINA:?Set the absolute path of the Linux Vina executable}"

cd "$DOCKSCREEN_PROJECT"
"$DOCKSCREEN_PYTHON" main.py --run --project "$DOCKSCREEN_PROJECT" \
    --vina "$DOCKSCREEN_VINA" --ligands data/ligands.csv \
    --cpu-budget "${SLURM_CPUS_PER_TASK:-4}" --cpu-per-job 1 \
    --workers "${SLURM_CPUS_PER_TASK:-4}" --exhaustiveness 8 --no-html
