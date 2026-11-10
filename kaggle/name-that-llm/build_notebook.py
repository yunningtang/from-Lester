"""Wrap baseline.py into a one-cell notebook for Kaggle (code competitions take notebooks).
Run after every edit to baseline.py:  python build_notebook.py"""
import json
from pathlib import Path

here = Path(__file__).parent
src = (here / "baseline.py").read_text(encoding="utf-8")
nb = {
    "cells": [{"cell_type": "code", "execution_count": None, "metadata": {},
               "outputs": [], "source": src.splitlines(keepends=True)}],
    "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                 "language_info": {"name": "python"}},
    "nbformat": 4, "nbformat_minor": 5,
}
(here / "name-that-llm-baseline.ipynb").write_text(json.dumps(nb, indent=1), encoding="utf-8")
print("wrote name-that-llm-baseline.ipynb")
