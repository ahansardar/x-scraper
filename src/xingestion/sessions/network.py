from __future__ import annotations

from dataclasses import dataclass


SUPPORTED_NETWORK_KINDS = {"direct", "proxy", "vpn"}


@dataclass(frozen=True)
class NetworkPolicy:
    raw: str
    kind: str
    route: str | None = None
    region: str | None = None

    @property
    def label(self) -> str:
        parts = [self.kind]
        if self.route:
            parts.append(self.route)
        if self.region:
            parts.append(self.region)
        return ":".join(parts)

    def public_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "kind": self.kind,
            "route": self.route,
            "region": self.region,
        }


def parse_network_policy(value: str | None) -> NetworkPolicy:
    raw = (value or "direct").strip() or "direct"
    parts = tuple(part.strip().lower() for part in raw.split(":"))
    if any(not part for part in parts):
        raise ValueError(f"network_context has empty segment: {raw}")
    if len(parts) > 3:
        raise ValueError("network_context must be kind[:route][:region]")
    kind = parts[0]
    if kind not in SUPPORTED_NETWORK_KINDS:
        raise ValueError(
            f"unsupported network kind {kind}; expected one of {', '.join(sorted(SUPPORTED_NETWORK_KINDS))}"
        )
    return NetworkPolicy(
        raw=raw,
        kind=kind,
        route=parts[1] if len(parts) >= 2 else None,
        region=parts[2] if len(parts) >= 3 else None,
    )


def network_matches(session_context: str, required_context: str | None) -> bool:
    if not required_context or not required_context.strip():
        return True
    session = parse_network_policy(session_context)
    required = parse_network_policy(required_context)
    if session.kind != required.kind:
        return False
    if required.route and session.route != required.route:
        return False
    if required.region and session.region != required.region:
        return False
    return True
