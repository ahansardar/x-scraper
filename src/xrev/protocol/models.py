from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


class CapabilityId(StrEnum):
    SEARCH_TWEETS = "SEARCH_TWEETS"


class RevisionStatus(StrEnum):
    DRAFT = "DRAFT"
    CANDIDATE = "CANDIDATE"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(value[key]) for key in sorted(value)})

    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)

    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}

    if isinstance(value, tuple):
        return [_thaw(item) for item in value]

    return value


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _thaw(payload),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class Revision:
    revision_id: str
    status: RevisionStatus
    evidence_maturity: str
    validation_freshness: str
    operational_health: str
    content_hash: str = field(init=False)

    def content_payload(self) -> Mapping[str, Any]:
        return {
            "revision_id": self.revision_id,
            "type": self.__class__.__name__,
        }

    def __post_init__(self) -> None:
        object.__setattr__(self, "content_hash", _stable_hash(self.content_payload()))


@dataclass(frozen=True)
class OperationRevision(Revision):
    operation_name: str
    operation_id: str
    method: str
    url_template: str

    def content_payload(self) -> Mapping[str, Any]:
        return {
            **super().content_payload(),
            "operation_name": self.operation_name,
            "operation_id": self.operation_id,
            "method": self.method,
            "url_template": self.url_template,
        }


@dataclass(frozen=True)
class FeatureBundleRevision(Revision):
    features: Mapping[str, Any]
    field_toggles: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "features", _freeze(self.features))
        object.__setattr__(self, "field_toggles", _freeze(self.field_toggles))
        super().__post_init__()

    def content_payload(self) -> Mapping[str, Any]:
        return {
            **super().content_payload(),
            "features": self.features,
            "field_toggles": self.field_toggles,
        }


@dataclass(frozen=True)
class ParserRevision(Revision):
    parser_name: str
    output_contract: str

    def content_payload(self) -> Mapping[str, Any]:
        return {
            **super().content_payload(),
            "parser_name": self.parser_name,
            "output_contract": self.output_contract,
        }


@dataclass(frozen=True)
class PaginationStrategyRevision(Revision):
    strategy_name: str
    cursor_semantics: str

    def content_payload(self) -> Mapping[str, Any]:
        return {
            **super().content_payload(),
            "strategy_name": self.strategy_name,
            "cursor_semantics": self.cursor_semantics,
        }


@dataclass(frozen=True)
class AuthProfileRevision(Revision):
    auth_class: str
    required_material: tuple[str, ...]

    def content_payload(self) -> Mapping[str, Any]:
        return {
            **super().content_payload(),
            "auth_class": self.auth_class,
            "required_material": list(self.required_material),
        }


@dataclass(frozen=True)
class TransactionProfileRevision(Revision):
    profile_name: str
    required_headers: tuple[str, ...]

    def content_payload(self) -> Mapping[str, Any]:
        return {
            **super().content_payload(),
            "profile_name": self.profile_name,
            "required_headers": list(self.required_headers),
        }


@dataclass(frozen=True)
class ClientProfileRevision(Revision):
    profile_name: str
    constraints: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "constraints", _freeze(self.constraints))
        super().__post_init__()

    def content_payload(self) -> Mapping[str, Any]:
        return {
            **super().content_payload(),
            "profile_name": self.profile_name,
            "constraints": self.constraints,
        }


@dataclass(frozen=True)
class AcquisitionRecipeRevision(Revision):
    operation: OperationRevision
    parser: ParserRevision
    pagination: PaginationStrategyRevision
    auth_profile: AuthProfileRevision
    transaction_profile: TransactionProfileRevision
    feature_bundle: FeatureBundleRevision
    client_profile: ClientProfileRevision
    composition_hash: str = field(init=False)

    def content_payload(self) -> Mapping[str, Any]:
        return {
            **super().content_payload(),
            "operation": self.operation.content_hash,
            "parser": self.parser.content_hash,
            "pagination": self.pagination.content_hash,
            "auth_profile": self.auth_profile.content_hash,
            "transaction_profile": self.transaction_profile.content_hash,
            "feature_bundle": self.feature_bundle.content_hash,
            "client_profile": self.client_profile.content_hash,
        }

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "composition_hash", self.content_hash)


@dataclass(frozen=True)
class ProtocolCapabilityBinding:
    capability_id: CapabilityId
    contract_version: int
    recipe: AcquisitionRecipeRevision


@dataclass(frozen=True)
class ProtocolReleaseManifest:
    release_id: str
    status: RevisionStatus
    bindings: tuple[ProtocolCapabilityBinding, ...]

    @classmethod
    def from_file(cls, path: str | Path) -> ProtocolReleaseManifest:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(payload)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ProtocolReleaseManifest:
        bindings = tuple(_binding_from_dict(item) for item in payload["bindings"])
        return cls(
            release_id=payload["release_id"],
            status=RevisionStatus(payload["status"]),
            bindings=bindings,
        )


def _revision_base(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "revision_id": payload["revision_id"],
        "status": RevisionStatus(payload["status"]),
        "evidence_maturity": payload["evidence_maturity"],
        "validation_freshness": payload["validation_freshness"],
        "operational_health": payload["operational_health"],
    }


def _binding_from_dict(payload: Mapping[str, Any]) -> ProtocolCapabilityBinding:
    recipe_payload = payload["recipe"]
    operation = OperationRevision(
        **_revision_base(recipe_payload["operation"]),
        operation_name=recipe_payload["operation"]["operation_name"],
        operation_id=recipe_payload["operation"]["operation_id"],
        method=recipe_payload["operation"]["method"],
        url_template=recipe_payload["operation"]["url_template"],
    )
    parser = ParserRevision(
        **_revision_base(recipe_payload["parser"]),
        parser_name=recipe_payload["parser"]["parser_name"],
        output_contract=recipe_payload["parser"]["output_contract"],
    )
    pagination = PaginationStrategyRevision(
        **_revision_base(recipe_payload["pagination"]),
        strategy_name=recipe_payload["pagination"]["strategy_name"],
        cursor_semantics=recipe_payload["pagination"]["cursor_semantics"],
    )
    auth_profile = AuthProfileRevision(
        **_revision_base(recipe_payload["auth_profile"]),
        auth_class=recipe_payload["auth_profile"]["auth_class"],
        required_material=tuple(recipe_payload["auth_profile"]["required_material"]),
    )
    transaction_profile = TransactionProfileRevision(
        **_revision_base(recipe_payload["transaction_profile"]),
        profile_name=recipe_payload["transaction_profile"]["profile_name"],
        required_headers=tuple(recipe_payload["transaction_profile"]["required_headers"]),
    )
    feature_bundle = FeatureBundleRevision(
        **_revision_base(recipe_payload["feature_bundle"]),
        features=recipe_payload["feature_bundle"]["features"],
        field_toggles=recipe_payload["feature_bundle"]["field_toggles"],
    )
    client_profile = ClientProfileRevision(
        **_revision_base(recipe_payload["client_profile"]),
        profile_name=recipe_payload["client_profile"]["profile_name"],
        constraints=recipe_payload["client_profile"]["constraints"],
    )
    recipe = AcquisitionRecipeRevision(
        **_revision_base(recipe_payload),
        operation=operation,
        parser=parser,
        pagination=pagination,
        auth_profile=auth_profile,
        transaction_profile=transaction_profile,
        feature_bundle=feature_bundle,
        client_profile=client_profile,
    )
    return ProtocolCapabilityBinding(
        capability_id=CapabilityId(payload["capability_id"]),
        contract_version=int(payload["contract_version"]),
        recipe=recipe,
    )
