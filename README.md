# Team MJF - FIN 67110 Lab 09 / Checkpoint 3

Martin, Jose, and Francesco serve a long-term equity investor seeking companies below conservative fair value, including overlooked spinoffs. SEC filing evidence supports valuation, risks, and what would change the investment view.

## What we own

The team owns the factor check: factors, directions, and weights are fixed in `spinoff_factors.txt` before returns are observed. `factor_check.py` reports the number of valid comparisons actually made; sparse observations do not establish statistical significance.

## Roles

- **Francesco - One Desk & Orchestration Lead:** joined pipeline, agent team, fixed execution order, replay, and final-report integration.
- **Martin - Evaluation & Proposal Lead:** three-column comparison, desk diagram, Checkpoint 3 documentation, and evaluation of what the join changed.
- **Jose - Skills & Evidence Lead:** seeker, worksheet, numeric guard, and filing/source verification.

## Architecture and joins

`one_desk.py` coordinates the existing Python components and CrewAI Flow in a fixed order:

```text
Seeker -> Selection -> Agent team -> Worksheet -> Numeric hook -> Final report
```

No model chooses the execution order. The seeker runs as a pipeline step in screen mode; ticker mode enters at Selection. The agent team performs the seven data steps, Research Analyst, Financial Analyst, Investment Advisor, Strategy Manager, and mandatory Verifier.

The worksheet join is **PIPELINE**: the team saves filing evidence in the shared run folder, then the worksheet reads those saved files. Python assembles the verified team report and the worksheet's final View and Conviction section. The numeric hook checks the saved team report, worksheet skill output, and assembled final report before completion. A role may quote a skill output file with attribution but must not recompute its numbers.

See [Checkpoint 3](CHECKPOINT-3.md) for the file-boundary diagram, completed AMD evaluation, partner filing checks, and PANW live record awaiting the final commit.

## Installation and local configuration

Use Python 3.10 through 3.13 and the dependencies in `requirements.txt`, including CrewAI 1.15.34. The current Python 3.13 environment already passed offline validation. For a new environment, install with:

```sh
python -m pip install -r requirements.txt
```

Configure a private, ignored local `.env` for real runs using these variable names only:

- `API_KEY` - Purdue model access.
- `SEC_USER_AGENT` - SEC identification.
- `CLOSES_FILE` - optional workbook path for price/liquidity evidence.

Never commit credentials. Missing export data leaves affected price, valuation comparisons, and liquidity evidence unavailable or not computed. A usable export needs Instrument, Date, and Price Close columns, plus Volume and Currency for the corresponding evidence.

## Main commands

Run from the repository root. Ticker and screen commands require live SEC/model access; offline tests use fictional inputs and mocks.

```sh
python -B -u one_desk.py TICKER
python -B -u one_desk.py screen
python -B -u one_desk.py --replay "runs/desk/SAVED_DESK_FOLDER"
python -B -u one_desk.py --continue "runs/desk/SAVED_PARTIAL_DESK_RUN"
python -B -u one_desk.py --finalize "runs/live/SAVED_PARTIAL_DESK_RUN"
```

Screen defaults to a 90-calendar-day distribution cutoff. Each execution uses one shared folder, by default under `runs/desk/<TICKER>_<timestamp>/`; `--output-root "runs/live"` selects the live-run root. The completed final report is `desk_report.md`, alongside `verified_report.md`, the timestamped worksheet Markdown/evidence JSON, `view.json`, and `desk_manifest.json`. Full generated runs remain local; minimum Lab 09 review evidence is preserved under `evidence/lab09/`.

Replay uses only the completed run's saved evidence and must not fetch missing evidence. It validates hashes, reruns saved-evidence checks, and requires byte-identical final-report composition. Missing or changed evidence fails; replay makes no SEC/model calls and does not read the live workbook.

Continuation is only for a partially completed original desk run with successfully completed team verification and validated saved verification provenance. It validates prerequisites, then runs Worksheet -> Numeric hook -> Final report, without repeating data collection, analysts, Manager, or semantic verification. Missing or mismatched prerequisites stop continuation before the worksheet model call. Continuation can make the worksheet's judgment model call; the minimum review subset is not a replay or continuation bundle.

Finalization is for an original run whose verified team report and existing worksheet both have valid saved provenance. Its fixed order is Validate saved team/verification evidence -> Validate existing worksheet provenance -> Numeric hook -> Final report. It reuses the exact saved worksheet without network/model calls or regeneration. Missing or changed provenance fails closed. The review subset is not sufficient to execute this mode.

## Partner review evidence and selected live release

Another team assigned NVIDIA (NVDA) and Advanced Micro Devices (AMD). Both One Desk runs are complete:

- NVIDIA: [final report](evidence/lab09/NVDA/desk_report.md), [manifest](evidence/lab09/NVDA/desk_manifest.json), and [saved 10-K](evidence/lab09/NVDA/10-K.txt). The FY2026 revenue filing check passed: $215.938 billion, `10-K.txt`, lines 915–920.
- AMD: [final report](evidence/lab09/AMD/desk_report.md), [manifest](evidence/lab09/AMD/desk_manifest.json), and the component/filing evidence linked in [Checkpoint 3](CHECKPOINT-3.md). The Q3 2026 revenue filing check passed: $13.377 billion, `earnings_release.txt`, lines 19–22 and 138–142. The 13-row AMD three-column evaluation is complete, including two EPS coverage omissions already present before final assembly.

The review subset preserves copied file bytes and filing line numbering. It excludes model requests/responses, download caches, and full run folders. It is for inspection; full saved runs are required for replay or continuation.

**Team MJF live company: Palo Alto Networks (PANW). Responsible member: Francesco.** This is separate from the two partner-assigned evaluation companies. PANW's saved One Desk run is complete: [final report](evidence/lab09/PANW/desk_report.md), [completed manifest](evidence/lab09/PANW/desk_manifest.json), [verified team report](evidence/lab09/PANW/verified_report.md), and [final worksheet](evidence/lab09/PANW/spinoff_worksheet_20261122_164308_061762_2a308f0d.md).

The [saved earnings release](evidence/lab09/PANW/earnings_release.txt), line 7, records November 18, 2026 and fiscal Q1 2027 ended October 31, 2026. The [saved 8-K](evidence/lab09/PANW/8-K.txt), lines 37–39, links that release to Item 2.02 / Exhibit 99.1. Accession **0001327567-26-000030** was accepted **2026-11-18 16:37:04 Eastern**, per [filing_time.json](evidence/lab09/PANW/filing_time.json). The [frozen view](evidence/lab09/PANW/view.json) was recorded **2026-11-22T21:42:46.511055+00:00**, or **16:42:46.511055 Eastern**. This view was recorded after the release; no pre-release or inside-window claim is made.

The original final report is `runs/live/PANW_2026-11-22_16-40-43_157876/desk_report.md`. The saved manifest establishes successful numeric checking and finalization, but records no final completion timestamp; its command-start time is not a completion time. Commit time and permalink are **PENDING FINAL COMMIT**. Inside-window status is **NOT ESTABLISHED** because no explicit applicable Lab 09 commit window is established by the locally available rules.

## Validation and pending work

**Final offline validation: 580 complete tests passed.** External network access was blocked. NVDA/AMD runs and filing checks, the AMD comparison, and PANW's live run are complete. PANW's live record awaits only the final commit time and permalink; window eligibility remains NOT ESTABLISHED.

Martin's earlier individual documentation is preserved in [Checkpoint 2 historical README](CHECKPOINT-2-HISTORICAL.md). Its commands and status belong to that historical implementation. The active team entry point is `one_desk.py`; Martin's `desk.py` remains preserved.

This is a learning exercise, not financial advice. AI assistance: OpenAI Codex. The saved-evidence checks and AMD evaluation above are documented; no human sign-off is asserted.
