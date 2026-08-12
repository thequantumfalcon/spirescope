# Reporting Security Vulnerabilities

Please do not report security vulnerabilities through public GitHub issues.

Use GitHub's private vulnerability reporting:
<https://github.com/thequantumfalcon/spirescope/security/advisories/new>

That channel is private between you and the maintainer, and it is the only
one this project offers. An email address was listed here previously, but it
was a reply-blocked GitHub alias that does not accept incoming mail, so
anything sent to it was discarded silently. A contact that quietly drops
reports is worse than none, because it leaves the reporter believing they
have disclosed responsibly — hence the single channel.

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact

Reports are acknowledged within 5 days.

## Supported Versions

| Version | Supported |
| ------- | --------- |
| latest  | Yes       |
| < latest| No        |

## Scope

SpireScope is a local-only tool. CSRF and CSP are in scope. Rate limiting is in scope only for non-loopback binds (`STS2_HOST`); it is intentionally skipped on loopback, where the server is single-user.
The opt-in sync service is in scope. Game data accuracy is out of scope.
