# Copilot instructions for Spirescope

## Read first

Before making meaningful changes, read:

- `README.md`
- `CONTRIBUTING.md`

## Operating doctrine

- Spirescope is a local-first, game-native intelligence dashboard for Slay the Spire 2.
- Preserve the project's dark gaming aesthetic and avoid generic dashboard design.
- Keep gameplay guidance concrete and useful rather than fluffy.

## Engineering rules

- Prefer existing FastAPI + Jinja server-rendered patterns.
- Preserve security headers, CSRF protection, rate limiting, SSE constraints, and input validation.
- Keep scraper and save-file behavior testable and mock-friendly.
- Avoid unnecessary framework or frontend complexity.

## Review priorities

When reviewing changes, prioritize:

1. gameplay usefulness
2. UI fit with the game's identity
3. SSE and caching correctness
4. search and analysis quality
5. web security and regression risk
