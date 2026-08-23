# Policy Identity

**Policy type participates in identity. It is never optional metadata.**

`app/core/identity.py`. Design rationale: [ADR-025](../adr/ADR-025-policy-identity-and-coverage-substantiation.md).

---

## The problem

Until Phase 6 a policy version was addressed three different ways depending on
where you stood:

| where | key |
|---|---|
| retrieval | a bare `version_id` UUID |
| linkage YAML, criteria inventory, gold cases | `(policy_id, version)` |
| the database | `(policy_id, document_type)` + `(document_id, revision_id)` |

The three agreed only because the corpus contained one policy type. Adopting NCDs
ended that: a regulation and a coverage determination could share a `policy_id`,
share a version, carry identical text and be in force on the same date — and every
composite key except the database's would treat them as one document.

**R-62 was that gap in the evaluation runners.** It was an instance; this is the fix
for the class.

## The canonical identity

```python
PolicyIdentity(policy_type=PolicyType.NCD, policy_id="NCD 310.1", version="3")
#   .key        -> ("NCD", "NCD 310.1", "3")
#   .scope_key  -> ("NCD", "NCD 310.1")
#   str(...)    -> "NCD:NCD 310.1:3"
```

**Type is the first component.** So a partial key that omits it cannot accidentally
match a full one, and there is no constructor that leaves it out — a function taking
a `PolicyIdentity` cannot be handed a half-identity, which is what a convention
("remember to pass the document type too") cannot promise.

## The prefix rule is enforced, not assumed

| type | required prefix |
|---|---|
| `REGULATION` | `42 CFR ` |
| `NCD` | `NCD ` |
| `LCD` | `L` |
| `ARTICLE` | `A` |

`42 CFR 410.32` and `NCD 310.1` were distinguishable by eye only because whoever
wrote them was careful. `PolicyIdentity` **refuses** a `policy_id` whose prefix
disagrees with its type, so a bare policy id in a log line, a citation or an error
message says which layer of authority it names.

`PolicyIdentity.infer()` recovers the type from the prefix, for artefacts written
before type was part of identity. It **refuses an unprefixed id rather than
guessing** — a default there would reintroduce exactly the ambiguity the prefix
removes.

## Where it lives, and why

`app/core/identity.py`, not `app/policy/models.py`. Identity is domain vocabulary,
not a persistence detail, and `app.decision` may not import `app.policy`.
`DocumentType` in `app.policy.models` is now an **alias** of `PolicyType` — the same
object, not a parallel enum that could drift.

## What changed at each site

| site | before | after |
|---|---|---|
| `eval/runners/retrieval*.py` | `{v.version_id for v in versions}` | full-identity keys (**R-62**) |
| `scripts/load_code_links.py` | `{(policy_id, revision): id}` | identity-keyed, and a **scoped** delete |
| `app/policy/resolve.py` | `version_ids` (deleted in Phase 5) | `scope_for(document_type)` |
| retrieval query | ids only | ids **and** `document_type` |

The linkage loader's whole-table `DELETE` was the other latent collision: loading the
NCD file would have silently wiped every CFR link. It now deletes only the versions
the file being loaded names.

## What is proven

`test_the_r62_collision_cannot_occur_end_to_end` builds the collision as
adversarially as the schema permits — a REGULATION and an NCD sharing a procedure
code, a revision id, a date of service and a byte-identical sentence. Every
discriminator except policy type is removed: similarity cannot separate them,
the temporal predicate cannot, the revision id cannot, the code cannot.

Each scope returns exactly its own chunk. Dropping type from the identity key makes
the unit tests fail; removing the `document_type` predicate from the query makes the
hand-built-scope test fail. Both mutations were run.
