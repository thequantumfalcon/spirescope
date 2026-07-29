# Reporting Security Vulnerabilities

Please do not report security vulnerabilities through public GitHub issues.

Instead, use GitHub's private vulnerability reporting:
<https://github.com/thequantumfalcon/spirescope/security/advisories/new>

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact

Expected response time: 48 hours.

## Supported Versions

| Version | Supported |
| ------- | --------- |
| latest  | Yes       |
| < latest| No        |

## Scope

SpireScope is a local-only tool. CSRF and CSP are in scope. Rate limiting is in scope only for non-loopback binds (`STS2_HOST`); it is intentionally skipped on loopback, where the server is single-user.
The opt-in sync service is in scope. Game data accuracy is out of scope.
