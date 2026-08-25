# R-86 revalidation: the runbook for "they say it's fixed"

**Script:** `scripts/r86_revalidate.py` · **Seal:**
`data/escalations/r86-reproducer.manifest.json` · **Runs:** `eval/reports/r86-revalidation/`

Written for somebody who was not here when the defect was found.

---

## When to run it

When the provider or firewall owner says R-86 is resolved. Not before — a
revalidation that runs on a hunch adds a `FAIL` to the record and tells you nothing
you did not already know.

## How

```bash
uv run python scripts/r86_revalidate.py --verify-only          # no model calls
MEDAUTH_LIVE_MODEL=1 uv run python scripts/r86_revalidate.py --write
```

`--verify-only` checks the seal and the live configuration and makes no calls. Run it
first: if the configuration has drifted, the live run would be measuring something
else and the script will refuse anyway.

`MEDAUTH_LIVE_MODEL=1` is a *safety* flag, not a bypass — its absence refuses, its
presence permits nothing beyond making real calls.

## What it does, in order

1. **Loads the seal** and checks it against its own digest. A hand-edited manifest
   attests to nothing and is refused before anything else happens.
2. **Compares live to sealed** — model, system prompt, instructions template, note
   frame, schema, gateway and firewall digests, caller key id, temperature, ceiling,
   attempts. **Any difference is `INCONCLUSIVE` and no call is made.**
3. **Runs both production-shaped cells**, unmodified, six trials each. The short cell
   is the control: a run where the long cell passed and the short one broke is a
   different system, not a fix.
4. **Applies the pre-registered threshold**, read from `eval.validity.ValidityRule`.
5. **Writes one timestamped run**, with every observation including the failures.

## Reading the result

| result | meaning | what happens next |
|---|---|---|
| **PASS** | ≤ 0.10 failure on the production shape, under the sealed configuration | `eval/official_gate.py` authorises; the frozen experiment may execute |
| **FAIL** | the defect persists | nothing changes; add the run to the escalation |
| **INCONCLUSIVE** | drift, a partial run, a moved threshold, or a broken seal | **blocks exactly as FAIL does** — fix the cause, do not interpret |

`INCONCLUSIVE` is not a soft `PASS`. It exists so "we could not tell" has somewhere to
go that is not the more convenient neighbour.

## What it will not do

- **Not modify the configuration.** Every value comes from the seal or the live
  system. There is no flag that changes one.
- **Not alter the threshold.** It is read, never restated. A revalidation whose
  threshold disagrees with the seal is `INCONCLUSIVE` rather than judged — because
  the cheapest way to fake a fix is to leave the system alone and move the line.
- **Not drop a failing trial.** Every observation is written out; a run with fewer
  than the registered trials cannot decide the gate in either direction.
- **Not authorise anything.** It records a result. The gate decides what that permits,
  and the gate is the only thing that may.

## Why runs accumulate

Each run is its own timestamped file and nothing is overwritten. **"It passed on the
third try" and "it passed" are different facts**, and a directory keeping only the
latest cannot tell them apart. The gate reads the *latest* run, not the best one — a
later `FAIL` is not overruled by an earlier `PASS`, and a test asserts it.

## If the configuration has drifted

The script tells you which digest moved. Two legitimate cases:

- **The provider changed the model.** Then the seal describes a system that no longer
  exists and the escalation is about a different one. Re-seal
  (`scripts/seal_r86_reproducer.py --write`), tell the owner the digest changed, and
  re-run.
- **We changed something.** During an evaluation hold we should not have. Find out
  what and why before re-sealing.

Re-sealing prints loudly when the digest moves, because anything already sent to the
owner then describes a different system.

## After a PASS

```bash
uv run python scripts/phase16_authorisation.py --write   # expect AUTHORISED
```

Then the frozen `phase16-evaluation-001` may run **exactly as frozen** — nothing is
adjusted first, and gold_v2's single scoring is spent at that point.

## The first recorded run

`20260825T155710Z.json` — `FAIL`, 6/12 = 0.5000, configuration matching the seal,
12 of 12 trials made. It exists so the harness is not theoretical: it has been run
end to end against the live path and does what this page says.
