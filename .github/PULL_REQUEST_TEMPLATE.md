## What this changes

<!-- One or two sentences. What behaviour is different after this merges? -->

## Why

<!-- The problem being solved. Link an issue if there is one. -->

## How it was verified

<!-- Not "tests pass" — what did you actually observe?

For a bug fix, the useful thing is a test that FAILS on master and passes here;
say so explicitly. Several defects in this project survived for months behind a
green suite because the test asserted structure ("is a list", "contains <h1>",
"the mock was called") rather than the value the user actually sees.

If the change touches a page, a route, or packaged data, run the app and read
the rendered output. Two bad releases shipped with untranslated placeholder
keys on every page because verification stopped at the HTTP status code. -->

- [ ] `pytest -q` passes
- [ ] `ruff check sts2/ tests/` passes
- [ ] For a bug fix: a new test fails without this change
- [ ] If a page, route, or shipped data changed: loaded it in a browser and
      checked the rendered content, not just the status code
- [ ] If a new runtime file or directory was added: it is included in
      `spirescope.spec` so frozen builds still find it

## Anything reviewers should look at closely

<!-- Known trade-offs, things you were unsure about, areas you could not test
(e.g. no Windows machine, no game install). Saying "I couldn't verify X" is
more useful than silence. -->
