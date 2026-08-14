from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xingestion.xprotocol.protocol import (
    CapabilityId,
    ProtocolCapabilityBinding,
    ProtocolReleaseManifest,
    RevisionStatus,
)


@dataclass(frozen=True)
class SearchTweetsInput:
    query: str
    product: str = "Top"
    cursor: str | None = None
    page_size: int = 20
    max_pages: int = 1
    page_number: int = 1
    pagination_root_task_id: str | None = None
    pagination_parent_task_id: str | None = None

    def validate(self) -> None:
        if not self.query.strip():
            raise CapabilityPlannerError("SEARCH_TWEETS query cannot be empty")
        if self.page_size < 1 or self.page_size > 50:
            raise CapabilityPlannerError("SEARCH_TWEETS page_size must be between 1 and 50")
        if self.max_pages < 1 or self.max_pages > 25:
            raise CapabilityPlannerError("SEARCH_TWEETS max_pages must be between 1 and 25")
        if self.page_number < 1 or self.page_number > self.max_pages:
            raise CapabilityPlannerError("SEARCH_TWEETS page_number must be between 1 and max_pages")


@dataclass(frozen=True)
class TweetByIdInput:
    tweet_id: str

    def validate(self) -> None:
        candidate = self.tweet_id.strip()
        if not candidate:
            raise CapabilityPlannerError("TWEET_BY_ID tweet_id cannot be empty")
        if not candidate.isdigit():
            raise CapabilityPlannerError("TWEET_BY_ID tweet_id must be a numeric string")


CapabilityInputPayload = SearchTweetsInput | TweetByIdInput


@dataclass(frozen=True)
class CapabilityRequest:
    capability_id: CapabilityId
    contract_version: int
    payload: CapabilityInputPayload
    required_fidelity: str = "STANDARD"
    traffic_priority: str = "NORMAL"

    def validate(self) -> None:
        if self.contract_version < 1:
            raise CapabilityPlannerError("contract_version must be at least 1")
        self.payload.validate()

    def public_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id.value,
            "contract_version": self.contract_version,
            "payload": _payload_public_dict(self.payload),
            "required_fidelity": self.required_fidelity,
            "traffic_priority": self.traffic_priority,
        }


def _payload_public_dict(payload: CapabilityInputPayload) -> dict[str, Any]:
    if isinstance(payload, TweetByIdInput):
        return {"tweet_id": payload.tweet_id}
    return {
        "query": payload.query,
        "product": payload.product,
        "cursor": payload.cursor,
        "page_size": payload.page_size,
        "max_pages": payload.max_pages,
        "page_number": payload.page_number,
        "pagination_root_task_id": payload.pagination_root_task_id,
        "pagination_parent_task_id": payload.pagination_parent_task_id,
    }


@dataclass(frozen=True)
class AcquisitionPlan:
    capability_id: CapabilityId
    contract_version: int
    release_id: str
    recipe_revision_id: str
    required_auth_class: str
    cursor: str | None
    page_size: int
    max_pages: int
    page_number: int
    traffic_priority: str
    binding: ProtocolCapabilityBinding

    def public_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id.value,
            "contract_version": self.contract_version,
            "release_id": self.release_id,
            "recipe_revision_id": self.recipe_revision_id,
            "required_auth_class": self.required_auth_class,
            "cursor": self.cursor,
            "page_size": self.page_size,
            "max_pages": self.max_pages,
            "page_number": self.page_number,
            "traffic_priority": self.traffic_priority,
        }


class CapabilityPlannerError(ValueError):
    pass


class CapabilityPlanner:
    def __init__(
        self,
        manifest: ProtocolReleaseManifest,
        *,
        allowed_statuses: set[RevisionStatus] | None = None,
    ) -> None:
        self.manifest = manifest
        self.allowed_statuses = allowed_statuses or {
            RevisionStatus.CANDIDATE,
            RevisionStatus.APPROVED,
        }

    def plan(self, request: CapabilityRequest) -> AcquisitionPlan:
        request.validate()
        if self.manifest.status not in self.allowed_statuses:
            raise CapabilityPlannerError(
                f"Manifest {self.manifest.release_id} is not eligible for planning"
            )

        binding = self._find_binding(request.capability_id, request.contract_version)
        recipe = binding.recipe
        if isinstance(request.payload, SearchTweetsInput):
            cursor = request.payload.cursor
            page_size = request.payload.page_size
            max_pages = request.payload.max_pages
            page_number = request.payload.page_number
        else:
            # Single-object capabilities (e.g. TWEET_BY_ID) have no cursor
            # concept -- these fields describe "one page, no continuation"
            # rather than a real pagination state.
            cursor = None
            page_size = 1
            max_pages = 1
            page_number = 1
        return AcquisitionPlan(
            capability_id=request.capability_id,
            contract_version=request.contract_version,
            release_id=self.manifest.release_id,
            recipe_revision_id=recipe.revision_id,
            required_auth_class=recipe.auth_profile.auth_class,
            cursor=cursor,
            page_size=page_size,
            max_pages=max_pages,
            page_number=page_number,
            traffic_priority=request.traffic_priority,
            binding=binding,
        )

    def _find_binding(
        self,
        capability_id: CapabilityId,
        contract_version: int,
    ) -> ProtocolCapabilityBinding:
        for binding in self.manifest.bindings:
            if (
                binding.capability_id == capability_id
                and binding.contract_version == contract_version
            ):
                return binding

        raise CapabilityPlannerError(
            f"No binding for {capability_id.value} contract v{contract_version}"
        )
