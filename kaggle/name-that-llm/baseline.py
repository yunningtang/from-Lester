"""Name That LLM - TF-IDF + LogisticRegression baseline.

Runs unchanged locally (pass --data DIR) and as a Kaggle kernel (CPU, internet off).
Writes submission.parquet with columns ["id", "model"].

CV uses StratifiedGroupKFold on prompt_id: the hidden test set uses prompts that are
not in train, so a plain random split would overestimate the score.
Metric: balanced accuracy (mean per-class recall), same as the leaderboard.
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score
from sklearn.model_selection import StratifiedGroupKFold

ON_KAGGLE = os.path.exists("/kaggle/input")
IS_RERUN = os.environ.get("KAGGLE_IS_COMPETITION_RERUN") is not None


def find_data_dir(cli_dir):
    candidates = [cli_dir] if cli_dir else []
    candidates += [
        "/kaggle/input/competitions/name-that-llm",
        "/kaggle/input/name-that-llm",
        "data",
    ]
    for c in candidates:
        if c and (Path(c) / "train.csv").exists():
            return Path(c)
    sys.exit(f"train.csv not found in any of: {candidates}")


def build_features(train_text, other_texts):
    """Char n-grams catch punctuation/formatting habits (em dashes, markdown, spacing);
    word n-grams catch vocabulary. Fit on train only."""
    char_vec = TfidfVectorizer(
        analyzer="char", ngram_range=(1, 5), min_df=2, sublinear_tf=True,
        lowercase=False, max_features=300_000,
    )
    word_vec = TfidfVectorizer(
        analyzer="word", ngram_range=(1, 2), min_df=2, sublinear_tf=True,
        lowercase=True, token_pattern=r"(?u)\b\w+\b|[^\w\s]", max_features=200_000,
    )
    x_train = hstack([char_vec.fit_transform(train_text), word_vec.fit_transform(train_text)]).tocsr()
    others = [hstack([char_vec.transform(t), word_vec.transform(t)]).tocsr() for t in other_texts]
    return x_train, others


def make_model(c):
    return LogisticRegression(C=c, max_iter=3000, class_weight="balanced")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=None, help="folder with train.csv / test.csv")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--C", type=float, default=10.0)
    parser.add_argument("--no-cv", action="store_true", help="skip CV, only fit + predict")
    args, _ = parser.parse_known_args()  # tolerate Jupyter's own argv

    data = find_data_dir(args.data)
    train = pd.read_csv(data / "train.csv", dtype=str)
    test = pd.read_csv(data / "test.csv", dtype=str)
    train["text"] = train["text"].fillna("")
    test["text"] = test["text"].fillna("")
    print(f"data={data} train={train.shape} test={test.shape} "
          f"classes={train['model'].nunique()} prompts={train['prompt_id'].nunique()}")

    y = train["model"].values

    # Skip CV during the hidden-test rerun to save runtime.
    if not args.no_cv and not IS_RERUN:
        sgkf = StratifiedGroupKFold(n_splits=args.folds, shuffle=True, random_state=42)
        oof = np.empty(len(train), dtype=object)
        for fold, (tr, va) in enumerate(sgkf.split(train, y, groups=train["prompt_id"])):
            x_tr, (x_va,) = build_features(train["text"].iloc[tr], [train["text"].iloc[va]])
            model = make_model(args.C).fit(x_tr, y[tr])
            oof[va] = model.predict(x_va)
            print(f"fold {fold}: balanced_acc={balanced_accuracy_score(y[va], oof[va]):.4f}")
        print(f"CV balanced_acc={balanced_accuracy_score(y, oof):.4f}")
        per_class = (
            pd.DataFrame({"y": y, "ok": oof == y}).groupby("y")["ok"].mean().sort_values()
        )
        print("per-class recall (worst first):\n" + per_class.round(3).to_string())

    x_tr, (x_te,) = build_features(train["text"], [test["text"]])
    model = make_model(args.C).fit(x_tr, y)
    sub = pd.DataFrame({"id": test["id"], "model": model.predict(x_te)})
    assert list(sub.columns) == ["id", "model"] and sub["model"].notna().all()

    out = Path("/kaggle/working") if ON_KAGGLE else Path(".")
    sub.to_parquet(out / "submission.parquet", index=False)
    print(f"wrote {out / 'submission.parquet'} rows={len(sub)}")
    print(sub["model"].value_counts().head(18).to_string())


if __name__ == "__main__":
    main()
