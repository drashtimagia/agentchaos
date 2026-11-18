# Security policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 0.1.x   | ✓         |

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Instead, email the maintainer directly at the address listed on the
[GitHub profile](https://github.com/drashtimagia). You will receive a
response within 72 hours. If the issue is confirmed, a fix will be released
as soon as possible (target: within 14 days for critical issues).

## Scope

AgentChaos is a local testing library. It does not operate network services
in production and does not store or transmit user data. The main attack
surface to report would be:

- Arbitrary code execution via a crafted YAML policy file or JSONL trace
- Path traversal in `--trace`, `--cache-dir`, or `--report` arguments
- Prototype pollution or deserialization issues in Pydantic model parsing
