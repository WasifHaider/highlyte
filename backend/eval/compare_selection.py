"""Compare clip-selection prompts on stored transcripts.

Reruns ranking and packing (no download, transcription or titles call) for
jobs whose transcript is saved, once per prompt variant and run, and prints
the kept clips side by side. The LLM gives different answers each run, so
use --runs 2 or more and trust picks that recur.

Every Groq answer is saved under --out, so --replay can rescore a run (after
a scoring change, say) without spending quota. A gold file marks the moments
a person judged worth clipping; the report then says how many each variant
found.

    python -m backend.eval.compare_selection --jobs 48ec2e8a39e7,9f63335a3729 \\
        --variants current,v2 --runs 2 --gold eval-runs/gold.json

Gold file: {"<job id>": [[start_s, end_s], ...], ...}

Uses GROQ_KEY from the environment (.env). Each run of a long video costs
several Groq calls against that key's daily limit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

from .. import db
from ..pipeline import groq_llm, scoring
from ..pipeline.groq_llm import ChatResult
from ..pipeline.ingest import duration_label
from ..pipeline.segments import from_dict as segment_from_dict
from ..pipeline.selection import rank_and_pack
from .prompts import VARIANTS

GOLD_MATCH = 0.5     # a kept clip covers a gold moment at this overlap
SAME_PICK = 0.5      # clips from different runs are the same pick at this overlap


@dataclass
class Kept:
    start: float
    end: float
    total: float
    standalone: float
    hook: float
    payoff: float
    reason: str
    text: str
    weak: bool
    shortened: bool = False


@dataclass
class Run:
    variant: str
    run: int
    kept: list[Kept]
    candidates: int
    picks: int
    skipped: list[str]
    rejects: dict[str, int]
    calls: int
    est_tokens: int
    answers: list[dict[str, Any]] = field(default_factory=list)


class RecordingChat:
    """Passes calls to a real chat and keeps every answer."""

    def __init__(self, chat) -> None:
        self.chat, self.answers, self.est_tokens = chat, [], 0

    def complete(self, prompt: str, *, max_tokens: int) -> ChatResult:
        self.est_tokens += groq_llm.estimate_tokens(prompt) + max_tokens
        result = self.chat.complete(prompt, max_tokens=max_tokens)
        self.answers.append({
            "prompt_sha": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12],
            "content": result.content, "finish_reason": result.finish_reason,
        })
        return result


class ReplayChat:
    """Answers with a saved run's answers, in order. Refuses a prompt that
    differs from the recorded one, since the saved answer wouldn't apply."""

    def __init__(self, answers: list[dict[str, Any]]) -> None:
        self.answers, self.est_tokens = list(answers), 0

    def complete(self, prompt: str, *, max_tokens: int) -> ChatResult:
        if not self.answers:
            raise RuntimeError("replay ran out of saved answers")
        saved = self.answers.pop(0)
        if hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12] != saved["prompt_sha"]:
            raise RuntimeError("prompt changed since this run was recorded; rerun without --replay")
        return ChatResult(saved["content"], saved["finish_reason"])


def _kept(c: scoring.Candidate) -> Kept:
    return Kept(
        start=round(c.start, 2), end=round(c.end, 2), total=round(c.total, 3),
        standalone=c.standalone, hook=c.hook, payoff=c.payoff, reason=c.reason,
        text=" ".join(w.t for w in c.words), weak="weak_pick" in c.flags,
        shortened="shortened" in c.flags,
    )


def run_once(segments, loudness, chat, variant: str, run: int) -> Run:
    rejects: list[str] = []
    v = VARIANTS[variant]
    out = rank_and_pack(segments, loudness, chat, template=v.template, clock=v.clock, rerank=v.rerank, rejects=rejects)
    answers = getattr(chat, "answers", [])
    counts: dict[str, int] = {}
    for r in rejects:
        counts[r] = counts.get(r, 0) + 1
    if out is None:
        return Run(variant, run, [], 0, 0, [], counts, len(answers), chat.est_tokens, list(answers))
    ranked, candidates, kept = out
    skipped = [f"{duration_label(s.start)}-{duration_label(s.end)} {s.reason}" for s in ranked.skipped]
    return Run(variant, run, [_kept(c) for c in kept], len(candidates), len(ranked.picks), skipped,
               counts, len(answers), chat.est_tokens, list(answers))


def gold_found(kept: list[Kept], gold: list[list[float]]) -> int:
    return sum(1 for g in gold if any(scoring.span_overlap((k.start, k.end), (g[0], g[1])) >= GOLD_MATCH for k in kept))


def recurrence(runs: list[Run]) -> list[tuple[Kept, int]]:
    """Each distinct pick across a variant's runs, with how many runs kept it."""
    groups: list[tuple[Kept, set[int]]] = []
    for r in runs:
        for k in r.kept:
            for rep, seen in groups:
                if scoring.span_overlap((k.start, k.end), (rep.start, rep.end)) >= SAME_PICK:
                    seen.add(r.run)
                    break
            else:
                groups.append((k, {r.run}))
    return sorted(((rep, len(seen)) for rep, seen in groups), key=lambda x: x[0].start)


def report(job_id: str, title: str, runs: list[Run], gold: list[list[float]] | None) -> str:
    lines = [f"## {job_id}  {title}", ""]
    by_variant: dict[str, list[Run]] = {}
    for r in runs:
        by_variant.setdefault(r.variant, []).append(r)
    for variant, vruns in by_variant.items():
        n = len(vruns)
        tokens = sum(r.est_tokens for r in vruns)
        lines.append(f"### {variant}: {n} run(s), about {tokens} tokens")
        for r in vruns:
            extra = f", skipped {'; '.join(r.skipped)}" if r.skipped else ""
            if r.rejects:
                extra += ", dropped: " + ", ".join(f"{k} x{v}" for k, v in sorted(r.rejects.items(), key=lambda x: -x[1]))
            g = f", gold {gold_found(r.kept, gold)}/{len(gold)}" if gold else ""
            lines.append(f"- run {r.run}: {r.picks} picks, {r.candidates} candidates, kept {len(r.kept)}"
                         f" ({sum(k.weak for k in r.kept)} weak, {sum(k.shortened for k in r.kept)} shortened){g}, {r.calls} calls{extra}")
        lines.append("")
        lines.append("| in runs | time | total | s/h/p | reason | opening |")
        lines.append("|---|---|---|---|---|---|")
        for k, seen in recurrence(vruns):
            when = f"{duration_label(k.start)}-{duration_label(k.end)} ({k.end - k.start:.0f}s)"
            shp = f"{k.standalone:.2f}/{k.hook:.2f}/{k.payoff:.2f}"
            weak = (" weak" if k.weak else "") + (" short" if k.shortened else "")
            opening = k.text[:90].replace("|", "/")
            lines.append(f"| {seen}/{n} | {when} | {k.total:.2f}{weak} | {shp} | {k.reason.replace('|', '/')} | {opening} |")
        lines.append("")
    return "\n".join(lines)


def _save(path: str, run: Run) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"variant": run.variant, "run": run.run, "answers": run.answers,
                   "kept": [k.__dict__ for k in run.kept]}, f, ensure_ascii=False, indent=1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jobs", required=True, help="comma-separated job ids with a stored transcript")
    ap.add_argument("--variants", default="current", help=f"comma-separated, from: {', '.join(VARIANTS)}")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--gold", help="gold moments JSON file")
    ap.add_argument("--out", default="eval-runs")
    ap.add_argument("--replay", action="store_true", help="reuse saved answers instead of calling Groq")
    args = ap.parse_args(argv)

    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    unknown = [v for v in variants if v not in VARIANTS]
    if unknown:
        ap.error(f"unknown variant(s): {', '.join(unknown)}")
    gold_all = json.load(open(args.gold, encoding="utf-8")) if args.gold else {}

    chat = None
    if not args.replay:
        chat = groq_llm.build_chat()
        if chat is None:
            ap.error("GROQ_KEY is not set")

    sections = []
    for job_id in [j.strip() for j in args.jobs.split(",") if j.strip()]:
        stored = db.get_transcript(job_id)
        if not stored or not stored.get("segments"):
            print(f"{job_id}: no stored transcript, skipped", file=sys.stderr)
            continue
        row = db.get_job(job_id) or {}
        title = row.get("video_title") or ""
        segments = [segment_from_dict(d) for d in stored["segments"]]
        loudness = stored.get("loudness") or []
        job_dir = os.path.join(args.out, job_id)
        os.makedirs(job_dir, exist_ok=True)

        runs: list[Run] = []
        for variant in variants:
            for i in range(1, args.runs + 1):
                path = os.path.join(job_dir, f"{variant}-{i}.json")
                if args.replay:
                    if not os.path.exists(path):
                        print(f"{job_id}: no saved {variant} run {i}, skipped", file=sys.stderr)
                        continue
                    answers = json.load(open(path, encoding="utf-8"))["answers"]
                    run = run_once(segments, loudness, ReplayChat(answers), variant, i)
                    run.answers = answers
                else:
                    print(f"{job_id}: {variant} run {i}...", file=sys.stderr)
                    run = run_once(segments, loudness, RecordingChat(chat), variant, i)
                    _save(path, run)
                runs.append(run)
        sections.append(report(job_id, title, runs, gold_all.get(job_id)))

    text = "\n".join(sections)
    with open(os.path.join(args.out, "report.md"), "w", encoding="utf-8") as f:
        f.write(text)
    # Windows consoles default to a code page that can't print every
    # character a transcript holds; the file above keeps them all.
    sys.stdout.reconfigure(errors="replace")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
