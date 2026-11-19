> Инструкция пользователя объединена в [README_RU.md](../README_RU.md). Этот документ содержит дополнительные технические сведения.

# Scientific references and software citations

Cite the methods actually used in a reported calculation, together with the software versions, configuration and data sources. A software citation is not a substitute for a license notice; see [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## Methods used by the application

| Component | Use in this code | Reference |
|---|---|---|
| RDKit | SMILES parsing, sanitization, descriptors, molecular drawings and fingerprints | [RDKit citation guidance](https://www.rdkit.org/docs/Overview.html#citing-the-rdkit). Cite "RDKit: Open-source cheminformatics", https://www.rdkit.org, with the actual version. The docking environment pins 2026.3.6 and the separate ADMET environment pins 2026.9.2; the [Zenodo collection](https://doi.org/10.5281/zenodo.591637) is a version-discovery link, not a verified DOI for this particular wheel. |
| ETKDG | Foundation of the conformer generation method used in ligand preparation | Riniker S, Landrum GA. Better Informed Distance Geometry: Using What We Know To Improve Conformation Generation. *J Chem Inf Model*. 2015;55:2562-2574. [doi:10.1021/acs.jcim.5b00654](https://doi.org/10.1021/acs.jcim.5b00654). |
| ETKDGv3 | `AllChem.ETKDGv3()` in `src/preparation/ligands.py` | Wang S, Witek J, Landrum GA, Riniker S. Improving Conformer Generation for Small Rings and Macrocycles Based on Distance Geometry and Experimental Torsional-Angle Preferences. *J Chem Inf Model*. 2020;60:2044-2058. [doi:10.1021/acs.jcim.0c00025](https://doi.org/10.1021/acs.jcim.0c00025). |
| UFF | Geometry optimization after embedding; bounded convergence retries | Rappe AK, Casewit CJ, Colwell KS, Goddard WA III, Skiff WM. UFF, a full periodic table force field for molecular mechanics and molecular dynamics simulations. *J Am Chem Soc*. 1992;114:10024-10035. [doi:10.1021/ja00051a040](https://doi.org/10.1021/ja00051a040). |
| Meeko | Ligand parameterization and PDBQT serialization | Santos-Martins D et al. Meeko: Molecule Parametrization and Software Interoperability for Docking and Beyond. *J Chem Inf Model*. 2025;65:13045-13050. [doi:10.1021/acs.jcim.5c02271](https://doi.org/10.1021/acs.jcim.5c02271). [Source and documentation](https://github.com/forlilab/Meeko). |
| AutoDock Vina | External docking executable | Trott O, Olson AJ. AutoDock Vina: improving the speed and accuracy of docking with a new scoring function, efficient optimization, and multithreading. *J Comput Chem*. 2010;31:455-461. [doi:10.1002/jcc.21334](https://doi.org/10.1002/jcc.21334). Also cite Eberhardt J, Santos-Martins D, Tillack AF, Forli S. AutoDock Vina 1.2.0: New Docking Methods, Expanded Force Field, and Python Bindings. *J Chem Inf Model*. 2021;61:3891-3898. [doi:10.1021/acs.jcim.1c00203](https://doi.org/10.1021/acs.jcim.1c00203). |
| Crippen logP | Molecular descriptor reports | Wildman SA, Crippen GM. Prediction of Physicochemical Parameters by Atomic Contributions. *J Chem Inf Comput Sci*. 1999;39:868-873. [doi:10.1021/ci990307l](https://doi.org/10.1021/ci990307l). |
| TPSA | Descriptor reports via RDKit | Ertl P, Rohde B, Selzer P. Fast Calculation of Molecular Polar Surface Area as a Sum of Fragment-Based Contributions and Its Application to the Prediction of Drug Transport Properties. *J Med Chem*. 2000. [doi:10.1021/jm000942e](https://doi.org/10.1021/jm000942e). |
| SA score | Optional docking-report descriptor loaded from RDKit `Contrib/SA_Score` | Ertl P, Schuffenhauer A. Estimation of synthetic accessibility score of drug-like molecules based on molecular complexity and fragment contributions. *J Cheminform*. 2009;1:8. [doi:10.1186/1758-2946-1-8](https://doi.org/10.1186/1758-2946-1-8). The RDKit contributed implementation includes modifications to the published method; see its source and [notice](../licenses/rdkit/SA_Score-NOTICE.txt). |
| Open Babel | Optional external `obabel` fallback | O'Boyle NM et al. Open Babel: An open chemical toolbox. *J Cheminform*. 2011;3:33. [doi:10.1186/1758-2946-3-33](https://doi.org/10.1186/1758-2946-3-33). Cite the version only when this backend was actually used. |

The [Ki/pKi conversion note](affinity_estimates.md) documents 298.15 K, units and limitations. Docking scores are not experimental binding free energies, and converted values are not measured inhibition constants.

## Optional ADMET and preference analysis

The following sources credit the software and methods behind the optional analysis.
Cite the components actually used and report their installed versions; a paper's
publication year is not the version number of the installed package.

| Component | Role in DockScreen | Scientific reference and software source |
|---|---|---|
| ADMET-AI | Local ADMET predictions through the separately installed ADMET-AI 2.0.1 package | Swanson K et al. ADMET-AI: a machine learning ADMET platform for evaluation of large-scale chemical libraries. *Bioinformatics*. 2024;40(7):btae416. [doi:10.1093/bioinformatics/btae416](https://doi.org/10.1093/bioinformatics/btae416); [open-access article](https://pmc.ncbi.nlm.nih.gov/articles/PMC11226862/); [official code and version notes](https://github.com/swansonk14/admet_ai). |
| Chemprop v2 | Molecular property prediction backend used by ADMET-AI; the dependency group pins Chemprop 2.3.1 | Graff DE et al. Chemprop v2: An Efficient, Modular Machine Learning Package for Chemical Property Prediction. *J Chem Inf Model*. 2026;66(1):28-33. [doi:10.1021/acs.jcim.5c02332](https://doi.org/10.1021/acs.jcim.5c02332); [official code](https://github.com/chemprop/chemprop); [upstream citation records](https://github.com/chemprop/chemprop/blob/main/CITATIONS.bib). |
| Chemprop molecular representations | Scientific background for the directed message-passing approach; DockScreen does not train a new model | Yang K et al. Analyzing Learned Molecular Representations for Property Prediction. *J Chem Inf Model*. 2019;59(8):3370-3388. [doi:10.1021/acs.jcim.9b00237](https://doi.org/10.1021/acs.jcim.9b00237). |
| PyTorch | Neural-network execution within the separate ADMET environment | Paszke A et al. PyTorch: An Imperative Style, High-Performance Deep Learning Library. *Advances in Neural Information Processing Systems*. 2019;32. [official proceedings](https://proceedings.neurips.cc/paper_files/paper/2019/hash/bdbca288fee7f92f2bfa9f7012727740-Abstract.html); [official software](https://pytorch.org/). |
| Therapeutics Data Commons (TDC) | Source of ADMET tasks/datasets used upstream by ADMET-AI, rather than a new dataset trained or downloaded by DockScreen | Huang K et al. Therapeutics Data Commons: Machine Learning Datasets and Tasks for Drug Discovery and Development. *NeurIPS Datasets and Benchmarks*. 2021;1. [official proceedings](https://datasets-benchmarks-proceedings.neurips.cc/paper/2021/hash/4c56ff4ce4aaf9573aa5dff913df997a-Abstract-round1.html); [ADME tasks](https://tdcommons.ai/single_pred_tasks/adme/); [toxicity tasks](https://tdcommons.ai/single_pred_tasks/tox/). |
| SMAA-2 | Basis of rank-acceptability analysis under sampled preferences | Lahdelma R, Salminen P. SMAA-2: Stochastic Multicriteria Acceptability Analysis for Group Decision Making. *Operations Research*. 2001;49(3):444-454. [doi:10.1287/opre.49.3.444.11220](https://doi.org/10.1287/opre.49.3.444.11220). |
| SMAA computation | Numerical implementation background | Tervonen T, Lahdelma R. Implementing stochastic multicriteria acceptability analysis. *European Journal of Operational Research*. 2007;178(2):500-513. [doi:10.1016/j.ejor.2005.12.037](https://doi.org/10.1016/j.ejor.2005.12.037); [author's institutional record](https://pure.eur.nl/en/publications/implementing-stochastic-multicriteria-acceptability-analysis/). |

**Version and interpretation notes.** The ADMET-AI paper describes v1. Its authors
state that v2 uses Chemprop v2 with retrained models and can produce different
predictions; see the official repository's Versions section. DockScreen records
the actual model/dependency provenance instead of treating paper benchmarks as
validation of each candidate. Chemprop v2's journal citation is 2026, although
the article first appeared online in December 2025.

DockScreen implements a preference-only adaptation of SMAA-2 with fixed property
values, explicit desirability scales, Dirichlet-sampled weights and symmetric
handling of tied candidates. It does not model prediction-error distributions or
claim the full uncertainty model of the original method. See [the SMAA guide](smaa.md)
for exact assumptions. Pareto nondomination is implemented locally; it is not an
additional external software dependency.

TDC and ADMET-AI citations do not replace endpoint-specific dataset attribution.
Keep the endpoint source information recorded in prediction metadata when reporting
particular endpoints. See [the ADMET guide](admet.md) and [third-party notices](../THIRD_PARTY_NOTICES.md)
for runtime details and licensing. Bibliographic details were checked against the
article/proceedings, the authors' citation records and institutional records on
2026-11-19.

## Supporting numerical libraries

- Harris CR et al. Array programming with NumPy. *Nature*. 2020;585:357-362. [doi:10.1038/s41586-020-2649-2](https://doi.org/10.1038/s41586-020-2649-2).
- Virtanen P et al. SciPy 1.0: fundamental algorithms for scientific computing in Python. *Nature Methods*. 2020;17:261-272. [doi:10.1038/s41592-019-0686-2](https://doi.org/10.1038/s41592-019-0686-2).

These support the installed chemistry stack; they are not separate docking engines. Gemmi, Pillow, Rich, filelock, Jinja2 and the testing dependencies are identified with versions and licenses in the third-party inventory. A separate scientific paper is not invented for each infrastructure package.

## Test data and preparation tools

- **JAK1, PDB 3EYG:** [structure record](https://www.rcsb.org/structure/3EYG), [dataset DOI](https://doi.org/10.2210/pdb3EYG/pdb). Williams NK et al. Structural study of JAK-specific inhibitor complexes. *J Mol Biol*. 2009;387:219-232. [doi:10.1016/j.jmb.2009.01.041](https://doi.org/10.1016/j.jmb.2009.01.041).
- **JAK2, PDB 6BBV:** [structure record](https://www.rcsb.org/structure/6BBV), [dataset DOI](https://doi.org/10.2210/pdb6BBV/pdb). Vazquez ML et al. Study identifying PF-04965842 as a selective JAK1 clinical candidate. *J Med Chem*. 2018;61:1130-1152. [doi:10.1021/acs.jmedchem.7b01598](https://doi.org/10.1021/acs.jmedchem.7b01598). The paper's JAK1 focus does not change the identity of the JAK2 structure 6BBV.
- **Ligand structures:** Kim S et al. PubChem 2025 update. *Nucleic Acids Res*. 2025;53:D1516-D1525. [doi:10.1093/nar/gkae1059](https://doi.org/10.1093/nar/gkae1059). Individual CIDs and record URLs are in [ligand_sources.csv](../data/ligand_sources.csv). See [PubChem citation guidance](https://pubchem.ncbi.nlm.nih.gov/docs/citation-guidelines). Experimental activity claims would require their own assay/publication sources; none are supplied by this technical dataset.
- **External receptor inspection:** Pettersen EF et al. UCSF ChimeraX: Structure visualization for researchers, educators, and developers. *Protein Sci*. 2021;30:70-82. [doi:10.1002/pro.3943](https://doi.org/10.1002/pro.3943). ChimeraX was used by the dataset preparer for receptor inspection and box placement, not as an application dependency. [Official citation guidance](https://www.cgl.ucsf.edu/chimerax/docs/credits.html).

Details, confirmed preparation steps and unresolved provenance are in [test_data.md](test_data.md). 

## Reporting a reproducible calculation

For a methods section or a shared calculation record, retain:

- Input molecule IDs/SMILES and receptor structures, their sources and preparation;
  include the chosen binding-site box and any handling of stereochemistry/charges.
- Software/model versions, settings, seeds and the selected target/protocol.
- Original docking scores and ADMET outputs, including failed/excluded rows and
  their reasons; retain units and endpoint definitions.
- Pareto criteria and, when used, exact SMAA scales, Dirichlet parameters,
  scenario count, seed and rank/tie rules. Report these as preference assumptions.
- Saved JSON/settings/provenance, poses where applicable, and the generated
  tables/reports. An imported CSV's unknown protocol must remain identified as such.

Start with the run's preserved input/provenance and the analysis metadata rather
than reconstructing a protocol from a screenshot. Technical tests establish
software behaviour; task-specific scientific validation remains a separate step.

## Citing DockScreen

Use the root [CITATION.cff](../CITATION.cff) to cite DockScreen. Kirill V. Karkhanin is the sole software author and developer. See [AUTHORS.md](../AUTHORS.md).
