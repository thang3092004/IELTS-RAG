# Ablation Runner (3 scenarios)

This script runs exactly 3 ablation scenarios on an existing ingested VideoRAG `working_dir`:

- `no_graph`: disable graph/entity channel contribution
- `no_chunks`: disable text chunk retrieval channel
- `no_visual`: disable visual embedding retrieval channel

## Files

- `reproduce/ablation/ablation_runner.py`

## Prerequisite

You must already have an ingested cache (`working_dir`) from full pipeline run.

## Run

```bash
python reproduce/ablation/ablation_runner.py \
  --working-dir ./videorag-workdir \
  --queries longervideos/dataset.json \
  --max-queries 10 \
  --top-k 20 \
  --out reproduce/ablation/results/ablation_results.json
```

## Output

A JSON file:

- `reproduce/ablation/results/ablation_results.json`

Format:

- top-level keys are scenarios (`no_graph`, `no_chunks`, `no_visual`)
- each scenario maps query text -> model answer

## Notes

- The runner patches caption step to reuse stored segment content, so it does not require loading heavy caption VLM during ablation runs.
- If your dataset JSON format differs from `longervideos/dataset.json`, pass a JSON list of strings or list of objects with `question` field.
