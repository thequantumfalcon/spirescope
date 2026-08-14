# 1. Defer the application factory and router split

Date: 2026-08-12
Status: Accepted (revisit after v3.1.0 has shipped and settled)

## Context

`sts2/app.py` builds the FastAPI application at module import: it constructs
the `KnowledgeBase`, seeds and migrates state directories, registers every
middleware, and exposes module-level globals (`kb`, the caches, the CSRF
secret) that `sts2/routes.py` reaches back into through a deferred `_app()`
import to break an `app -> routes -> app` cycle. `routes.py` is roughly two
thousand lines covering pages, the JSON API, settings, admin, streaming,
imports and exports.

Three separate reviews have raised the same recommendation: an application
factory, domain routers, typed application state, and injected services.
It is a fair recommendation. Import-time construction is why several defects
were possible in the first place — recovery ordering had to be threaded in
ahead of `KnowledgeBase()`, test isolation depends on monkeypatching module
globals, and the host allowlist had to be read per request rather than bound
once because binding it at import froze whatever the environment said then.

## Decision

Do not perform the refactor as part of the current repair work. Revisit it
as its own branch once v3.1.0 has shipped and been stable in use.

## Rationale

The refactor produces no user-visible change while touching nearly every
module and every test's setup path. Landing it immediately after a large
correctness pass would mean re-verifying more than a thousand tests against
relocated code at the same moment the behaviour under them changed, which
makes any regression hard to attribute to either cause. The repair work is
independently verifiable; the refactor is not, until it is the only thing in
the diff.

Deferring is cheap because nothing else waits on it: every defect the
structure contributed to has been fixed directly, and the fixes do not become
harder to carry across a later refactor.

## Consequences

Accepted, with eyes open:

- Startup ordering stays load-bearing. Anything that must happen before the
  knowledge base is built has to be placed above it in `app.py` by hand, and
  a comment is the only thing preventing a later edit from reordering it.
- Tests keep reaching into module globals, so isolation stays a convention
  rather than a property of the design.
- Configuration read at import time cannot respond to later changes, so
  anything that must stay live has to be read per request instead.
- `routes.py` keeps growing unless split, which makes ownership boundaries
  awkward when more than one change is in flight at once.

This is recorded so the deferral reads as a decision rather than an
oversight; it has now been raised as a finding three times.
