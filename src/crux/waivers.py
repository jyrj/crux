"""Waiver system for suppressing known CDC/RDC violations.

Waivers allow designers to acknowledge and suppress known-safe violations.
Format is YAML:

```yaml
waivers:
  - rule: MISSING_SYNC
    signal: "data_a"
    from_domain: "clk_a"
    to_domain: "clk_b"
    reason: "Quasi-static signal, verified by simulation"
    reviewer: "engineer@example.com"
```

Matching uses fnmatch glob patterns on signal, from_domain, to_domain fields.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Waiver:
    """A single waiver entry."""
    rule: str                 # ViolationType value: "MISSING_SYNC", etc.
    signal: str | None        # signal name pattern (fnmatch glob)
    from_domain: str | None   # source domain pattern
    to_domain: str | None     # dest domain pattern
    reason: str               # mandatory justification
    reviewer: str | None      # who approved this waiver

    def matches(
        self,
        rule: str,
        signal: str = "",
        from_domain: str = "",
        to_domain: str = "",
    ) -> bool:
        """Check if this waiver matches a violation."""
        if self.rule != rule:
            return False
        if self.signal and not fnmatch.fnmatch(signal, self.signal):
            return False
        if self.from_domain and not fnmatch.fnmatch(from_domain, self.from_domain):
            return False
        if self.to_domain and not fnmatch.fnmatch(to_domain, self.to_domain):
            return False
        return True


def load_waivers(waiver_path: str | Path) -> list[Waiver]:
    """Load waivers from a YAML file."""
    try:
        import yaml
    except ImportError:
        raise ImportError(
            "PyYAML is required for waiver support. Install with: pip install pyyaml"
        )

    path = Path(waiver_path)
    with open(path) as f:
        data = yaml.safe_load(f)

    if not data or "waivers" not in data:
        return []

    waivers: list[Waiver] = []
    for entry in data["waivers"]:
        if not isinstance(entry, dict):
            continue
        if "rule" not in entry or "reason" not in entry:
            continue

        waivers.append(Waiver(
            rule=entry["rule"],
            signal=entry.get("signal"),
            from_domain=entry.get("from_domain"),
            to_domain=entry.get("to_domain"),
            reason=entry["reason"],
            reviewer=entry.get("reviewer"),
        ))

    return waivers


def apply_waivers(
    violations: list,
    waivers: list[Waiver],
) -> tuple[list, list[tuple[Any, Waiver]]]:
    """Apply waivers to a list of violations.

    Returns (active_violations, waived_pairs) where waived_pairs is
    [(violation, matching_waiver), ...].
    """
    if not waivers:
        return violations, []

    active: list = []
    waived: list[tuple[Any, Waiver]] = []

    for v in violations:
        # Extract matching fields from the violation
        rule = v.rule.value if hasattr(v.rule, 'value') else str(v.rule)
        signal = getattr(v, 'signal_name', '')
        from_dom = getattr(v, 'source_domain', '')
        to_dom = getattr(v, 'dest_domain', '')

        matched = False
        for w in waivers:
            if w.matches(rule, signal, from_dom, to_dom):
                waived.append((v, w))
                matched = True
                break

        if not matched:
            active.append(v)

    return active, waived
