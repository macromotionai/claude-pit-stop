# Handoff vs no handoff: a controlled test

Run on 2026-09-18. One run per arm.

## Question

Does handing off to a fresh session at 250k context reduce the total tokens needed to finish the same piece of work, once the cost of the handoff itself is paid? And does the work come out equally finished?

## Design

Two arms, identical except for one thing.

- **Without handoff.** One session from the first step to the last.
- **With handoff.** Identical, except that when a reply ends at 250k context or more, the next message is the handoff skill. The run then continues in a new session that opens with the plugin's exact prompt: continue from the handoff note.

**Scripted, not typed.** A script sends every message, so both arms get the same words in the same order. The biggest difference between two real sessions is what the human says and when; scripting removes it. The trigger uses the plugin's own context-reading function, so the rule is the plugin's, not a copy. The question box itself is not tested here, only the token mechanics after the user says yes.

**The task.** Thirteen legacy Python modules of about 1,700 lines each, generated from a fixed seed so every run gets byte-identical files. Each module has one function whose code disagrees with its own docstring. Each step adds that step's test file and sends one prompt: read the module in full, fix the function the new test names, add a line to `CHANGELOG.md`, run the whole test suite. The last test also checks that `CHANGELOG.md` holds all 13 lines in order, so the fresh session has to carry the earlier work forward correctly. Each step adds roughly 30k of context, so the no-handoff arm climbs to about 450k and the handoff arm crosses 250k after step 7.

**Held constant.** Claude Opus 5 with the 1M context window, effort medium, both pinned on the command line. The same user settings, `CLAUDE.md`, skills, plugins and MCP servers in both arms. Permission mode bypass. Runs back to back with no idle gaps, so the one-hour prompt cache never expired. Each run in its own new folder, so project memory, checklists and handoff notes could not leak between runs.

**Measured.** Every token of every API call in every session of the run, in all four classes the API reports: input, cache writes, cache reads and output. Subagents are included; none ran. Two independent counts:

1. The `usage` block on every reply in the session transcripts. One API response is written as several transcript records, so records are deduplicated on message ID and request ID. Without that, totals come out about three times too high.
2. The per-call totals `claude -p --output-format json` returns.

The two counts agreed within 0.02%. Dollar figures are Claude Code's own list-price estimates from that JSON output, not a bill.

## Results

| | Without handoff | With handoff |
|---|---|---|
| Total tokens | 13,742,004 | 9,352,819 |
| Cost at list price | $11.33 | $9.72 |
| Cache reads | 13.29M | 8.84M |
| Cache writes | 0.45M | 0.49M |
| Output | 9,266 | 14,204 |
| API calls | 52 | 57 |
| Peak context | 457k | 272k |
| Mean context per call | 264k | 164k |
| Handoffs | 0 | 1, after step 7 at 266k |
| Handoff overhead: the handoff turn plus the new session's first turn | none | 1.31M tokens, $1.23 |
| Compactions | 0 | 0 |
| Tests passed | 14 of 14 | 14 of 14 |
| Wall time | 3 min | 4 min |

**The handoff arm used 32% fewer tokens and cost 14% less, with the overhead included.**

Per step, context after the step and cost of the step:

| Step | Without: context | Without: $ | With: context | With: $ |
|---|---|---|---|---|
| 01 | 86k | 0.88 | 86k | 0.88 |
| 02 | 117k | 0.52 | 118k | 0.54 |
| 03 | 149k | 0.61 | 147k | 0.57 |
| 04 | 179k | 0.65 | 177k | 0.65 |
| 05 | 210k | 0.71 | 206k | 0.69 |
| 06 | 241k | 0.78 | 236k | 0.75 |
| 07 | 273k | 0.85 | 266k | 0.82 |
| handoff | | | 273k | 0.66 |
| new session reads the note | | | 60k | 0.57 |
| 08 | 304k | 0.91 | 91k | 0.49 |
| 09 | 336k | 0.97 | 121k | 0.53 |
| 10 | 365k | 1.01 | 153k | 0.55 |
| 11 | 394k | 1.07 | 186k | 0.59 |
| 12 | 426k | 1.16 | 216k | 0.62 |
| 13 | 457k | 1.21 | 247k | 0.79 |

## Reading it

- **Steps 1 to 7 cost almost the same in both arms.** That suggests little run-to-run noise on this task, even with one run per arm.
- **After the handoff, each step cost about half as much,** because each message re-read about 150k less. The handoff paid for itself within about three steps. The longer the work continues after a handoff, the bigger the saving.
- **Money fell less than tokens.** Cache reads are cheap and cache writes are not. The fresh session has to write its starting context into the cache once, and the handoff turn writes the note. Cache writes went up slightly while cache reads fell by a third.
- **Nothing was lost.** The note carried the step pattern, every earlier fix and the changelog state. The fresh session finished steps 8 to 13 and the changelog test passed.

## Limits

- One run per arm. The near-identical first seven steps make noise unlikely to explain a 32% gap, but this is not a statistical result.
- A synthetic, repetitive task. It shows the token mechanics. It does not show how well a handoff note holds up on messy real work, where losing a detail can cost more later.
- One threshold, 250k, on a 1M-context model. Other thresholds are one command-line flag away in the harness.
- The question box, tab opening and user choice are not part of this test.

## Reproduce

```
cd experiment
python3 make_task.py
python3 driver.py control
python3 driver.py handoff
python3 measure.py results/control-*.json results/handoff-*.json
```

It spends real tokens, about 23M for the pair on the settings above. `AB_MODEL` and `AB_EFFORT` change the model and effort.
