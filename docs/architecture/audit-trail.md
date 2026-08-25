# The audit trail

**Schema:** `app/audit/models.py` · **Migration:** `0005_case_lifecycle_and_audit` ·
**Tests:** `tests/unit/test_audit_schema.py` (12), `tests/integration/test_audit_append_only.py` (7)

R-16 (audit tampering, **Critical**) and R-17 (clinical text in audit payloads, High)
both recorded mitigations that did not exist. `AuditEvent` was an in-memory contract
that the slice produced correctly and the process discarded on return. This is those
two rows becoming true.

---

## 1. Four tables, and only two of them are the record

| table | mutable | why |
|---|---|---|
| `cases` | **yes** | a case advances through states; this is a projection |
| `case_recommendations` | insert-only in practice | one row per run, ordered by `run_seq`; a re-run never overwrites an earlier recommendation |
| `audit_events` | **append-only, enforced** | the record |
| `human_review_events` | **append-only, enforced** | the record |

Confusing the projection with the record would either freeze the lifecycle or unfreeze
the trail. `cases` keeps `UPDATE`; the event stream never does.

## 2. What "append-only" is enforced by — and what it is not

### The grants do not bind, and finding that out is the point

The first version of the migration did what R-16's wording says: `REVOKE UPDATE, DELETE`
from the application role. It applied cleanly and read correctly in
`information_schema`:

```
audit_events    ['INSERT', 'SELECT']
```

**And UPDATE, DELETE and TRUNCATE all still succeeded.** PostgreSQL does not enforce
grants against a table's **owner**, and this deployment's application user owns its own
schema. The control was documented, believed, present in the catalogue, and inert —
which is the third time this repository has found that shape (R-103, R-105, and now
this).

### A trigger does bind

`medauth_refuse_audit_mutation()` raises on `UPDATE` and `DELETE`. Triggers apply to the
owner, which is what makes this the mechanism and the grants defence in depth for
deployments that do separate roles.

### And a row-level trigger is not enough

The second version added `BEFORE UPDATE OR DELETE ... FOR EACH ROW`. UPDATE and DELETE
were refused. **TRUNCATE went straight through** — it removes every row without visiting
any, so a per-row trigger never fires, and it is the most complete erasure available.

So each append-only table carries **two** triggers:

```
{table}_append_only   BEFORE UPDATE OR DELETE  FOR EACH ROW
{table}_no_truncate   BEFORE TRUNCATE          FOR EACH STATEMENT
```

Neither defect was caught by reading. Both were caught by running the statements against
a real server, which is why `tests/integration/test_audit_append_only.py` exists
alongside the schema test rather than instead of it.

### Verified behaviour

```
INSERT    allowed          the trail can grow
UPDATE    refused          rows survive
DELETE    refused          rows survive
TRUNCATE  refused          rows survive
retention removed by created_at, and the guard is restored afterwards
```

### The residual, stated

A **superuser can** `ALTER TABLE ... DISABLE TRIGGER` or drop it. Nothing inside a
database stops a deliberate administrator, and no schema can. The claim this earns is
narrow and it is the only one made anywhere in this repository:

> **No application code path can mutate the audit trail.**

Not "the trail is immutable". Not "tampering is impossible". A deployment that needs the
stronger property needs an external, append-only sink, and that is not built.

## 3. Retention deletes by `created_at` and by nothing else

```sql
purge_audit_before(before timestamptz) RETURNS integer
```

One parameter, one predicate. There is no overload that takes a case id, a reviewer or
an outcome — a purge that can be aimed at particular rows is a mechanism for erasing the
record of one particular recommendation, which is precisely the attack R-16 names.

It suspends the append-only triggers for exactly two statements and restores them on
both the success and the failure path. A test asserts the `EXCEPTION` handler re-enables
them and re-raises, because one bad purge that left the trail mutable would be worse
than a failed purge.

## 4. No column can hold clinical text (R-17)

Every column in `audit_events` is an identifier, an enum, a count, a digest or a
timestamp. `payload` is JSONB carrying fact ids, chunk ids, criterion ids and spans.
There is no `Text` column, and every `String` is bounded at 64 characters or fewer —
asserted by walking the metadata, so "we needed somewhere to put it" cannot quietly
become a column.

The submitted payload is **not** stored. `cases.input_sha256` records its digest, which
is what lets a later reader prove which input produced which recommendation without the
note living in the audit database.

The two deliberate exceptions are on `human_review_events`: `rationale` and
`reviewer_qualification`, both unbounded, both written by a named person about their own
decision and their own credentials. A test asserts they are the *only* two.

## 5. A human override never erases the AI's recommendation

An override does not update `case_recommendations`. It **inserts** a
`human_review_events` row beside the recommendation it disagreed with, carrying
`recommended_outcome_at_review` denormalised so that "did the human agree" is answerable
from that row alone.

- `OVERRIDE` is its own action, not an `APPROVE` with a flag, so disagreement is
  countable without parsing anything.
- `DENY` and `OVERRIDE` require a rationale — a `CHECK` constraint, because the API is
  not the only writer a deployment might ever have.
- The foreign key to `case_recommendations` is `ON DELETE RESTRICT`: deleting a
  recommendation a human ruled on would remove the thing the decision was about and
  leave the decision standing.

## 6. What is not built yet

The schema exists and is enforced. **Nothing writes to it yet** — the slice still
returns its `AuditEvent`s to its caller, and wiring the runtime through this schema is
the next step, along with the API that would read it. Reporting the trail as "complete"
on the strength of a correct schema would be the same error this document opens by
describing.
