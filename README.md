# Bisect

**An evidence-first AI incident investigator.** When a production service breaks,
bisect figures out *what* broke, *which commit* likely caused it, *which runbook*
applies, and *how big* the impact is — then (in later phases) posts a clean brief
and drafts the postmortem.

It is **advisory and human-in-the-loop by design.** bisect diagnoses and
recommends; a human approves any action. It never changes production on its own.
The diagnosis quality is the product; the action is the human's judgment call.

---

## Why it's built this way

Two design decisions shape the whole project (full rationale in
[`DECISIONS.md`](DECISIONS.md)):

- **Evidence-first.** The correlation, impact math, timeline, and severity are
  all computed deterministically from real signals. Where an LLM is used, it only
  *ranks* pre-filtered git diffs and explains its reasoning — it never invents a
  number that lands in the incident record. Every conclusion is inspectable.
- **Measured, not asserted.** bisect is built on a controlled simulator with
  *ground truth* — we plant a known-bad commit, so we can actually measure whether
  diagnosis ranks it correctly, rather than just claiming it works.

## How "which commit caused it" works

Given an incident, bisect stacks three cheap signals and reasons over them:

1. **Time correlation** — the error spike starts right after a deploy landed.
2. **Blast radius** — the failing endpoint / stack-trace file maps to the files a
   commit touched.
3. **Error-signature match** — the exception (`AttributeError: 'NoneType' ...
   session`) points at the exact code a commit changed.

A deterministic baseline scores commits on these signals. An LLM ranker (optional)
reads the actual diffs and re-ranks with reasoning. The output is a *ranked list
with confidence and reasoning* — not a single guess.

## The benchmark (why this is more than a demo)

Because the simulator provides ground truth, bisect ships a benchmark that
measures diagnosis accuracy across easy and deliberately hard scenarios. The hard
scenarios include a benign **decoy commit** that touches the same failing file and
deploys closest to the spike — so timing and blast-radius heuristics get fooled,
and only *reading the diff* finds the real culprit.

| mode                     | top-1 | top-3 | notes                                  |
|--------------------------|:-----:|:-----:|----------------------------------------|
| deterministic baseline   |  33%  | 100%  | aces easy cases; fooled by the decoy   |
| LLM diff-reading ranker  |   —   |   —   | wired in; not yet measured (needs key) |

The baseline dropping to 33% top-1 on the hard set is the point: it shows that
service-matching and timing are not enough, and that reading the diff is what
closes the gap. The bad commit stays in the top 3 every time (100%), so the LLM's
job is to *reorder*, not to find a needle. Measuring the LLM row is a pending step
(see status below).

## Status

Built on a controlled simulator first; real integrations come after the core is
proven.

- [x] **Phase 0** — `Incident` schema (the shared contract every stage reads/writes)
- [x] **Phase 1** — simulator (breaks on deploy) + a real toy git repo with a
      planted bad commit and a decoy
- [x] **Phase 2** — detection (fires an alert, creates an Incident)
- [x] **Phase 3** — diagnosis agent (deterministic + optional LLM) + benchmark
- [x] **Phase 4** — runbook retrieval (TF-IDF; clean upgrade path to vector search)
- [ ] **Phase 5** — impact estimation
- [ ] **Phase 6** — Slack incident brief
- [ ] **Phase 7** — remediation buttons (demo-only, human-approved)
- [ ] **Phase 8** — resolution detection + postmortem generation
- [ ] **Phase 9** — real integrations (GitHub, Datadog/Prometheus, Slack)

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# build the real toy repo (planted bad commit + decoy)
python3 scripts/make_toy_repo.py

# run the pipeline: simulate an incident -> detect -> diagnose
python3 scripts/run_demo.py

# measure diagnosis accuracy across easy + hard scenarios
python3 scripts/run_benchmark.py

# check runbook retrieval accuracy
python3 scripts/eval_runbooks.py
```

The LLM ranker activates automatically when an `ANTHROPIC_API_KEY` is set;
without one, everything runs on the deterministic path.

## Layout

```
src/core/incident.py       the Incident contract (Phase 0)
src/simulator/             fake service: healthy -> deploy -> broken (Phase 1)
src/detection/             threshold detector -> Incident (Phase 2)
src/diagnosis/             signal gathering + ranking, deterministic & LLM (Phase 3)
src/runbooks/              TF-IDF runbook retrieval (Phase 4)
data/runbooks/             7 sample runbooks (committed)
scripts/make_toy_repo.py   builds a real git repo with a planted bad commit + decoy
scripts/run_demo.py        one-command pipeline demo
scripts/run_benchmark.py   diagnosis accuracy on easy + hard scenarios
scripts/eval_runbooks.py   runbook retrieval accuracy
```

## Tech

Python, Pydantic (the `Incident` contract), real `git` for commit correlation,
pure-Python TF-IDF for retrieval, and the Anthropic API for optional diff-reading
diagnosis. No external services required to run the core — it works offline on a
simulator with ground truth.

## Honest scope

This runs on a **simulator**, by design — the simulator is what provides the
ground truth that makes the benchmark meaningful. Real data-source integrations
(GitHub, Datadog/Prometheus, Slack) are Phase 9. Everything downstream reads one
`Incident` object, so swapping simulated sources for real APIs is a contained
change, not a rewrite.
