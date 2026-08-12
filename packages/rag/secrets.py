"""Secret detection/redaction (spec module 43). Applied to every chunk's content
before it is embedded, stored, or ever returned to the LLM/citations/logs — a secret
that made it into the vector store would leak through RAG results forever, so this
runs at chunk-build time, not as an afterthought at the API boundary.
"""
from __future__ import annotations

import re

# (label, pattern) — ordered roughly by specificity so more specific patterns match
# before generic fallbacks would double-redact the same span.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("aws_secret_key", re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}['\"]?")),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    (
        "db_connection_string",
        re.compile(r"(?i)(postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://[^:\s]+:[^@\s]+@[^\s'\"]+"),
    ),
    (
        "generic_api_key_assignment",
        re.compile(
            r"(?i)((?:api|secret|access)[_-]?(?:key|token)|password|passwd)\s*[=:]\s*"
            r"['\"]([A-Za-z0-9_\-/+]{16,})['\"]"
        ),
    ),
]


def redact(content: str) -> tuple[str, list[str]]:
    """Returns (redacted_content, labels_found). Never raises — a detector bug must
    not break indexing; worst case is an under-redaction, not a crash."""
    found: list[str] = []
    for label, pattern in _PATTERNS:
        def _sub(m: re.Match, label=label) -> str:
            found.append(label)
            # Keep assignment-style matches readable (`key = "[REDACTED:...]"`)
            # instead of destroying the whole line, when the pattern has 2 groups.
            if m.re.groups == 2:
                return f'{m.group(1)}="[REDACTED:{label}]"'
            return f"[REDACTED:{label}]"

        content = pattern.sub(_sub, content)
    return content, found
