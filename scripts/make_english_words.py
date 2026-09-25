"""One-off: write backend/pipeline/data/english_words.txt, the common
English words hinglish.classify uses to tell English from Roman Hindi/Urdu.

  ./.venv/Scripts/pip install wordfreq
  ./.venv/Scripts/python scripts/make_english_words.py

wordfreq is only needed to regenerate the file; the app reads the text file.
"""
from pathlib import Path

from wordfreq import top_n_list

OUT = Path(__file__).resolve().parents[1] / "backend" / "pipeline" / "data" / "english_words.txt"
words = sorted({w for w in top_n_list("en", 10000) if w.isalpha() and w.isascii() and len(w) > 1})
OUT.write_text("\n".join(words) + "\n", encoding="utf-8")
print(f"{len(words)} words -> {OUT}")
