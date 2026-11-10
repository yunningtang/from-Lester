# Name That LLM: TF-IDF baseline

Competition: https://www.kaggle.com/competitions/name-that-llm
Task: classify a short text into one of 18 LLMs. Metric: balanced accuracy.
Submission: `submission.parquet` with columns `id`, `model` (model name as a string).

Training is on Kaggle's CPU. Your computer only pushes the code.

## Files

| File | Purpose |
|---|---|
| `baseline.py` | Main code: TF-IDF (char 1–5 + word 1–2) + LogisticRegression, 5-fold CV grouped by `prompt_id` |
| `build_notebook.py` | Wraps `baseline.py` into a notebook (code competitions need notebook submissions) |
| `name-that-llm-baseline.ipynb` | Generated notebook; this is what gets pushed |
| `kernel-metadata.json` | Kaggle kernel config: CPU, internet off, competition data attached |

## One-time setup (on your computer)

1. Join the competition on its web page and accept the rules. Otherwise the data won't attach.
2. Install the CLI:

```bash
pip install kaggle
```

3. Kaggle website → Settings → API → Create New Token. Put the downloaded `kaggle.json` in `~/.kaggle/` (on Windows: `C:\Users\<you>\.kaggle\`).
4. Replace `YOUR_KAGGLE_USERNAME` in `kernel-metadata.json` with your Kaggle username.

## Run on Kaggle (no local compute)

```bash
cd kaggle/name-that-llm
```

```bash
kaggle kernels push -p .
```

Check status. It finishes when it shows `complete` (about a few minutes):

```bash
kaggle kernels status YOUR_KAGGLE_USERNAME/name-that-llm-tfidf-baseline
```

Download the logs and output. The log shows the `CV balanced_acc` for each fold:

```bash
kaggle kernels output YOUR_KAGGLE_USERNAME/name-that-llm-tfidf-baseline -p out
```

To submit, open that notebook on the Kaggle website → Output → Submit to Competition.
During scoring, Kaggle re-runs the notebook on about 4,000 hidden texts. The script skips CV automatically in that run.

## Making changes

After editing `baseline.py`, rebuild the notebook and push again:

```bash
python build_notebook.py && kaggle kernels push -p .
```

Local quick test (optional; needs `train.csv` and `test.csv` in `data/`. The data is small, so a laptop CPU takes only a few minutes):

```bash
kaggle competitions download -c name-that-llm -p data && cd data && unzip -o name-that-llm.zip && cd ..
```

```bash
python baseline.py --data data
```

## Why CV is grouped by prompt_id

The training set has only about 2,700 rows covering 150 prompts, and the test texts come from new prompts. If you split randomly, the same prompt appears in both training and validation. The model then learns "which prompt it is," and the CV score comes out much too high. Grouping by prompt matches how the test set is built.

## Next steps

1. Tune `--C`, n-gram ranges, and handcrafted style features (em-dash rate, markdown, sentence length) and watch which classes have the worst recall.
2. Fine-tune DeBERTa-v3 on Kaggle's GPU (set `enable_gpu` to `true`). Upload the trained weights as a Dataset and add it to `dataset_sources`.
3. LLM (Qwen and similar) + LoRA classifier, then blend the probabilities from all the models.
