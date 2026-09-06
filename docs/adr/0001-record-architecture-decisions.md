# 1. Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** APIx engineering

## Context

APIx produces a number that a national statistics office is expected to publish. MoSPI
and the RBI will not adopt a series whose construction they cannot interrogate, and a
statistical method has a lifetime measured in decades — longer than any of the people who
built it will be on the project.

That creates a specific problem. Someone in 2031 will look at a design decision here — the
choice of elementary formula, the shape of the `fare_quote` primary key, the refusal to
carry a price forward without flagging it — and need to know not just what was chosen but
what was rejected and why. Git history records what changed. It does not record what was
considered and discarded, and a code comment is the wrong place for a paragraph of
reasoning about alternatives.

There is a second reason, specific to this project. Several decisions here are
methodological rather than technical, and are the kind of thing an external reviewer at a
statistics office will want to challenge. Those arguments need to be written down in a
form that can be handed to someone outside the engineering team.

## Decision

We record architecture decisions as ADRs in `docs/adr/`, in the format described by
Michael Nygard.

- One file per decision, numbered sequentially: `NNNN-short-title.md`.
- Each records **Context** (the forces at play), **Decision** (what we are doing) and
  **Consequences** (what follows, including what gets worse).
- An ADR is immutable once accepted. A decision that is reversed gets a new ADR that
  supersedes the old one; the old file stays, with its status updated to `Superseded by
  NNNN`. The record of a mistake is as useful as the record of a success.
- Anything that changes the published number gets an ADR — an elementary formula, a
  splice method, an outlier rule, a change to the basket definition.
- Anything that would surprise a new engineer reading the schema gets one too.

ADRs complement, and do not replace, `docs/methodology.md`. That document is generated
from `config/method.yaml` and describes the method **currently in force**. An ADR explains
why it is that way and what else was on the table.

## Consequences

**Good.** A reviewer at MoSPI can be handed `docs/adr/` and understand the reasoning
without reading Python. Debates get resolved once and stay resolved, rather than
relitigated whenever someone new reads the code. Reversals become deliberate and visible.

**Costly.** Writing an ADR takes real effort, and the temptation will be to skip it under
deadline. The mitigation is scope: ADRs are for decisions that are expensive to reverse,
not for every design choice. Most code needs no ADR at all.

**Risk.** ADRs rot if they drift from the code. They are dated and immutable precisely so
that an old ADR reads as a historical record rather than as current documentation. When
the code and an accepted ADR disagree, that is a bug in one of them and worth a new ADR
either way.
