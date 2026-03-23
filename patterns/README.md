# Patterns

`generated/` contains experiment pattern YAMLs produced by the matrix generation pipeline. These are **runtime artifacts**, not source of truth.

**Source of truth:** Matrix manifests in `configs/matrices/`.

To regenerate:
```bash
python scripts/generate_experiment_matrix.py configs/matrices/<manifest>.yaml --wave <wave_name>
```

Generated patterns should be gitignored — regenerate from manifests for reproducibility.
