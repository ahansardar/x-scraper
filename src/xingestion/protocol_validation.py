from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from xingestion.xprotocol.runtime import parse_search_tweets_page
from xingestion.xprotocol.runtime import ProtocolError
from xingestion.xprotocol.protocol import ProtocolReleaseManifest
from xingestion.xprotocol.runtime import SearchTweetsRequest, WebSessionAuth
from xingestion.xprotocol.runtime.search_tweets import build_search_timeline_request
from xingestion.xprotocol.runtime.transport import (
    OneAttemptTransport,
    response_to_protocol_error,
)
from xingestion.xprotocol.evidence import RawEvidenceRef, RawEvidenceSink


DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "search_tweets"


@dataclass(frozen=True)
class ProtocolValidationResult:
    source: str
    source_type: str
    ok: bool
    tweet_count: int
    bottom_cursor_present: bool
    engagement_complete_count: int
    missing_engagement_count: int
    typename_fingerprint: str
    structural_fingerprint: str
    warnings: tuple[str, ...]
    error: str | None = None

    def public_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "source_type": self.source_type,
            "ok": self.ok,
            "tweet_count": self.tweet_count,
            "bottom_cursor_present": self.bottom_cursor_present,
            "engagement_complete_count": self.engagement_complete_count,
            "missing_engagement_count": self.missing_engagement_count,
            "typename_fingerprint": self.typename_fingerprint,
            "structural_fingerprint": self.structural_fingerprint,
            "warnings": list(self.warnings),
            "error": self.error,
        }


@dataclass(frozen=True)
class ProtocolValidationReport:
    generated_at: str
    checked_sources: int
    ok_sources: int
    failed_sources: int
    parser_revision_id: str
    results: tuple[ProtocolValidationResult, ...]

    @property
    def ok(self) -> bool:
        return self.checked_sources > 0 and self.failed_sources == 0

    def public_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "ok": self.ok,
            "checked_sources": self.checked_sources,
            "ok_sources": self.ok_sources,
            "failed_sources": self.failed_sources,
            "parser_revision_id": self.parser_revision_id,
            "results": [result.public_dict() for result in self.results],
        }


@dataclass(frozen=True)
class SavedProtocolValidationReport:
    name: str
    path: Path
    generated_at: str
    ok: bool
    checked_sources: int
    failed_sources: int

    def public_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": str(self.path),
            "generated_at": self.generated_at,
            "ok": self.ok,
            "checked_sources": self.checked_sources,
            "failed_sources": self.failed_sources,
        }


@dataclass(frozen=True)
class CaptureReplayComparison:
    browser_source: str
    direct_replay_source: str
    ok: bool
    browser_tweet_count: int
    direct_tweet_count: int
    browser_structural_fingerprint: str
    direct_structural_fingerprint: str
    mismatches: tuple[str, ...]

    def public_dict(self) -> dict[str, object]:
        return {
            "browser_source": self.browser_source,
            "direct_replay_source": self.direct_replay_source,
            "ok": self.ok,
            "browser_tweet_count": self.browser_tweet_count,
            "direct_tweet_count": self.direct_tweet_count,
            "browser_structural_fingerprint": self.browser_structural_fingerprint,
            "direct_structural_fingerprint": self.direct_structural_fingerprint,
            "mismatches": list(self.mismatches),
        }


@dataclass(frozen=True)
class CaptureReplayComparisonReport:
    generated_at: str
    checked_pairs: int
    ok_pairs: int
    failed_pairs: int
    browser_captures: int
    direct_replays: int
    comparisons: tuple[CaptureReplayComparison, ...]

    @property
    def ok(self) -> bool:
        return self.checked_pairs > 0 and self.failed_pairs == 0

    def public_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "ok": self.ok,
            "checked_pairs": self.checked_pairs,
            "ok_pairs": self.ok_pairs,
            "failed_pairs": self.failed_pairs,
            "browser_captures": self.browser_captures,
            "direct_replays": self.direct_replays,
            "comparisons": [item.public_dict() for item in self.comparisons],
        }


@dataclass(frozen=True)
class DirectReplayRunResult:
    browser_source: str
    stored: bool
    skipped: bool
    direct_replay_ref: RawEvidenceRef | None = None
    reason: str | None = None

    def public_dict(self) -> dict[str, object]:
        return {
            "browser_source": self.browser_source,
            "stored": self.stored,
            "skipped": self.skipped,
            "direct_replay_ref": (
                {
                    "evidence_id": self.direct_replay_ref.evidence_id,
                    "content_sha256": self.direct_replay_ref.content_sha256,
                    "storage_uri": self.direct_replay_ref.storage_uri,
                }
                if self.direct_replay_ref is not None
                else None
            ),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DirectReplayRunReport:
    generated_at: str
    candidates: int
    attempted: int
    stored: int
    skipped: int
    failed: int
    results: tuple[DirectReplayRunResult, ...]

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def public_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "ok": self.ok,
            "candidates": self.candidates,
            "attempted": self.attempted,
            "stored": self.stored,
            "skipped": self.skipped,
            "failed": self.failed,
            "results": [result.public_dict() for result in self.results],
        }


def build_protocol_validation_report(
    *,
    raw_evidence_dir: Path | None,
    parser_revision_id: str,
    limit: int = 10,
    include_fixtures: bool = True,
) -> ProtocolValidationReport:
    if limit < 1:
        raise ValueError("limit must be at least 1")

    sources = []
    if include_fixtures:
        sources.extend((path, "fixture") for path in _fixture_files())
    if raw_evidence_dir is not None:
        sources.extend((path, "raw_evidence") for path in _raw_evidence_files(raw_evidence_dir, limit=limit))

    results = tuple(
        validate_search_tweets_payload(
            path,
            source_type=source_type,
        )
        for path, source_type in sources[:limit]
    )
    ok_sources = sum(1 for result in results if result.ok)
    return ProtocolValidationReport(
        generated_at=datetime.now(UTC).isoformat(),
        checked_sources=len(results),
        ok_sources=ok_sources,
        failed_sources=len(results) - ok_sources,
        parser_revision_id=parser_revision_id,
        results=results,
    )


def run_direct_replays_for_browser_captures(
    *,
    raw_evidence_dir: Path,
    manifest: ProtocolReleaseManifest,
    auth: WebSessionAuth,
    transport: OneAttemptTransport,
    raw_evidence_sink: RawEvidenceSink,
    limit: int = 3,
) -> DirectReplayRunReport:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    browser_captures = _classified_raw_evidence_files(raw_evidence_dir, "browser")
    results = []
    for browser_path in browser_captures[:limit]:
        result = _run_direct_replay_for_capture(
            browser_path,
            manifest=manifest,
            auth=auth,
            transport=transport,
            raw_evidence_sink=raw_evidence_sink,
            raw_evidence_dir=raw_evidence_dir,
        )
        results.append(result)

    stored = sum(1 for result in results if result.stored)
    skipped = sum(1 for result in results if result.skipped)
    failed = len(results) - stored - skipped
    return DirectReplayRunReport(
        generated_at=datetime.now(UTC).isoformat(),
        candidates=len(browser_captures),
        attempted=len(results) - skipped,
        stored=stored,
        skipped=skipped,
        failed=failed,
        results=tuple(results),
    )


def build_capture_replay_comparison_report(
    *,
    raw_evidence_dir: Path,
    limit: int = 10,
) -> CaptureReplayComparisonReport:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    browser_captures = _classified_raw_evidence_files(raw_evidence_dir, "browser")
    direct_replays = _classified_raw_evidence_files(raw_evidence_dir, "direct_replay")
    comparisons = []
    used_browser_sources: set[str] = set()
    for direct_path in direct_replays[:limit]:
        direct_meta = _metadata_for_payload(direct_path)
        browser_path = _matching_browser_capture(
            direct_meta,
            browser_captures,
            used_sources=used_browser_sources,
        )
        if browser_path is None:
            continue
        used_browser_sources.add(str(browser_path))
        comparison = _compare_capture_pair(
            browser_path,
            direct_path,
        )
        comparisons.append(comparison)

    ok_pairs = sum(1 for item in comparisons if item.ok)
    return CaptureReplayComparisonReport(
        generated_at=datetime.now(UTC).isoformat(),
        checked_pairs=len(comparisons),
        ok_pairs=ok_pairs,
        failed_pairs=len(comparisons) - ok_pairs,
        browser_captures=len(browser_captures),
        direct_replays=len(direct_replays),
        comparisons=tuple(comparisons),
    )


def write_protocol_validation_report(
    report: ProtocolValidationReport,
    *,
    report_dir: Path,
) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = _safe_stamp(report.generated_at)
    path = report_dir / f"protocol-validation-{stamp}.json"
    path.write_text(
        json.dumps(report.public_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def list_protocol_validation_reports(
    report_dir: Path,
    *,
    limit: int = 25,
) -> tuple[SavedProtocolValidationReport, ...]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if not report_dir.exists():
        return ()
    reports = []
    for path in sorted(
        report_dir.glob("protocol-validation-*.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )[:limit]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        reports.append(
            SavedProtocolValidationReport(
                name=path.name,
                path=path,
                generated_at=str(payload.get("generated_at") or ""),
                ok=bool(payload.get("ok")),
                checked_sources=int(payload.get("checked_sources") or 0),
                failed_sources=int(payload.get("failed_sources") or 0),
            )
        )
    return tuple(reports)


def validate_search_tweets_payload(
    path: Path,
    *,
    source_type: str,
) -> ProtocolValidationResult:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        page = parse_search_tweets_page(payload)
        warnings = _warnings_for_page(page)
        typenames = sorted(_typenames(payload))
        structural_paths = sorted(_structural_paths(payload))
        return ProtocolValidationResult(
            source=str(path),
            source_type=source_type,
            ok=bool(page.tweets) and not warnings,
            tweet_count=len(page.tweets),
            bottom_cursor_present=page.cursor_present,
            engagement_complete_count=sum(
                1 for tweet in page.tweets if _engagement_complete(tweet)
            ),
            missing_engagement_count=sum(
                1 for tweet in page.tweets if not _engagement_complete(tweet)
            ),
            typename_fingerprint=_fingerprint(typenames),
            structural_fingerprint=_fingerprint(structural_paths),
            warnings=warnings,
        )
    except Exception as exc:
        return ProtocolValidationResult(
            source=str(path),
            source_type=source_type,
            ok=False,
            tweet_count=0,
            bottom_cursor_present=False,
            engagement_complete_count=0,
            missing_engagement_count=0,
            typename_fingerprint="",
            structural_fingerprint="",
            warnings=(),
            error=str(exc),
        )


def _fixture_files() -> tuple[Path, ...]:
    if not DEFAULT_FIXTURE_DIR.exists():
        return ()
    return tuple(sorted(DEFAULT_FIXTURE_DIR.glob("*.json")))


def _raw_evidence_files(raw_evidence_dir: Path, *, limit: int) -> tuple[Path, ...]:
    if not raw_evidence_dir.exists():
        return ()
    files = [
        path
        for path in raw_evidence_dir.glob("*.json")
        if not path.name.endswith(".metadata.json")
    ]
    return tuple(sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)[:limit])


def _classified_raw_evidence_files(raw_evidence_dir: Path, capture_kind: str) -> tuple[Path, ...]:
    if not raw_evidence_dir.exists():
        return ()
    files = []
    for path in raw_evidence_dir.glob("*.json"):
        if path.name.endswith(".metadata.json"):
            continue
        metadata = _metadata_for_payload(path)
        if metadata.get("capture_kind") == capture_kind:
            files.append(path)
    return tuple(sorted(files, key=lambda path: path.stat().st_mtime, reverse=True))


def _metadata_for_payload(path: Path) -> dict[str, str]:
    payload = _metadata_envelope_for_payload(path)
    metadata = payload.get("metadata")
    return {str(key): str(value) for key, value in dict(metadata or {}).items()}


def _metadata_envelope_for_payload(path: Path) -> dict[str, Any]:
    metadata_path = path.with_name(f"{path.stem}.metadata.json")
    if not metadata_path.exists():
        return {}
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload or {})


def _run_direct_replay_for_capture(
    browser_path: Path,
    *,
    manifest: ProtocolReleaseManifest,
    auth: WebSessionAuth,
    transport: OneAttemptTransport,
    raw_evidence_sink: RawEvidenceSink,
    raw_evidence_dir: Path,
) -> DirectReplayRunResult:
    metadata_payload = _metadata_envelope_for_payload(browser_path)
    browser_content_sha = str(metadata_payload.get("content_sha256") or "")
    metadata = _metadata_for_payload(browser_path)
    if not browser_content_sha:
        return DirectReplayRunResult(
            browser_source=str(browser_path),
            stored=False,
            skipped=True,
            reason="missing_browser_content_sha256",
        )
    if _direct_replay_exists(raw_evidence_dir, replay_of_content_sha256=browser_content_sha):
        return DirectReplayRunResult(
            browser_source=str(browser_path),
            stored=False,
            skipped=True,
            reason="direct_replay_already_exists",
        )

    recipe_revision_id = metadata.get("recipe_revision_id")
    recipe = _recipe_by_revision(manifest, recipe_revision_id)
    if recipe is None:
        return DirectReplayRunResult(
            browser_source=str(browser_path),
            stored=False,
            skipped=True,
            reason="missing_or_unapproved_recipe_revision",
        )

    request = _search_request_from_metadata(metadata)
    if request is None:
        return DirectReplayRunResult(
            browser_source=str(browser_path),
            stored=False,
            skipped=True,
            reason="missing_replay_request_metadata",
        )

    try:
        http_response = transport.send(build_search_timeline_request(recipe, auth, request))
    except (ProtocolError, ValueError) as exc:
        return DirectReplayRunResult(
            browser_source=str(browser_path),
            stored=False,
            skipped=False,
            reason=str(exc),
        )

    error = response_to_protocol_error(http_response)
    if error:
        return DirectReplayRunResult(
            browser_source=str(browser_path),
            stored=False,
            skipped=False,
            reason=f"{error.error_class}:{error.message}",
        )

    ref = raw_evidence_sink.store_json(
        http_response.json_body,
        metadata={
            "capture_kind": "direct_replay",
            "capability_id": "SEARCH_TWEETS",
            "replay_of_content_sha256": browser_content_sha,
            "browser_capture_source": str(browser_path),
            "release_id": manifest.release_id,
            "recipe_revision_id": recipe.revision_id,
            "operation_revision_id": recipe.operation.revision_id,
            "parser_revision_id": recipe.parser.revision_id,
            "pagination_revision_id": recipe.pagination.revision_id,
            "acquisition_query": request.query,
            "acquisition_product": request.product,
            "acquisition_count": str(request.count),
            "acquisition_cursor": request.cursor or "",
        },
    )
    return DirectReplayRunResult(
        browser_source=str(browser_path),
        stored=True,
        skipped=False,
        direct_replay_ref=ref,
    )


def _direct_replay_exists(raw_evidence_dir: Path, *, replay_of_content_sha256: str) -> bool:
    for path in _classified_raw_evidence_files(raw_evidence_dir, "direct_replay"):
        metadata = _metadata_for_payload(path)
        if metadata.get("replay_of_content_sha256") == replay_of_content_sha256:
            return True
    return False


def _recipe_by_revision(manifest: ProtocolReleaseManifest, revision_id: str | None):
    if not revision_id:
        return None
    for binding in manifest.bindings:
        if binding.recipe.revision_id == revision_id:
            return binding.recipe
    return None


def _search_request_from_metadata(metadata: Mapping[str, str]) -> SearchTweetsRequest | None:
    query = str(metadata.get("acquisition_query") or "").strip()
    if not query:
        return None
    count = int(metadata.get("acquisition_count") or "20")
    return SearchTweetsRequest(
        query=query,
        product=str(metadata.get("acquisition_product") or "Top"),
        count=count,
        cursor=str(metadata.get("acquisition_cursor") or "") or None,
    )


def _matching_browser_capture(
    direct_meta: Mapping[str, str],
    browser_captures: tuple[Path, ...],
    *,
    used_sources: set[str],
) -> Path | None:
    replay_of = direct_meta.get("replay_of_content_sha256")
    if replay_of:
        for path in browser_captures:
            if str(path) in used_sources:
                continue
            metadata_path = path.with_name(f"{path.stem}.metadata.json")
            try:
                metadata_payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if metadata_payload.get("content_sha256") == replay_of:
                return path
    for path in browser_captures:
        if str(path) not in used_sources:
            return path
    return None


def _compare_capture_pair(browser_path: Path, direct_path: Path) -> CaptureReplayComparison:
    browser = validate_search_tweets_payload(browser_path, source_type="browser")
    direct = validate_search_tweets_payload(direct_path, source_type="direct_replay")
    mismatches = []
    if not _parse_succeeded(browser):
        mismatches.append("browser_parse_failed")
    if not _parse_succeeded(direct):
        mismatches.append("direct_replay_parse_failed")
    if browser.bottom_cursor_present != direct.bottom_cursor_present:
        mismatches.append("bottom_cursor_present")
    if browser.typename_fingerprint != direct.typename_fingerprint:
        mismatches.append("typename_fingerprint")
    if browser.structural_fingerprint != direct.structural_fingerprint:
        mismatches.append("structural_fingerprint")
    return CaptureReplayComparison(
        browser_source=browser.source,
        direct_replay_source=direct.source,
        ok=not mismatches,
        browser_tweet_count=browser.tweet_count,
        direct_tweet_count=direct.tweet_count,
        browser_structural_fingerprint=browser.structural_fingerprint,
        direct_structural_fingerprint=direct.structural_fingerprint,
        mismatches=tuple(mismatches),
    )


def _parse_succeeded(result: ProtocolValidationResult) -> bool:
    return result.error is None and result.tweet_count > 0


def _warnings_for_page(page) -> tuple[str, ...]:
    warnings = []
    if not page.tweets:
        warnings.append("no_tweets_parsed")
    for tweet in page.tweets:
        missing = []
        if not tweet.tweet_id:
            missing.append("tweet_id")
        if not tweet.username:
            missing.append("username")
        if not tweet.text:
            missing.append("text")
        if tweet.view_count in (None, ""):
            missing.append("view_count")
        if missing:
            warnings.append(f"{tweet.tweet_id or 'unknown'} missing {','.join(missing)}")
    return tuple(warnings)


def _engagement_complete(tweet) -> bool:
    return (
        tweet.reply_count is not None
        and tweet.repost_count is not None
        and tweet.like_count is not None
        and tweet.quote_count is not None
        and tweet.bookmark_count is not None
        and tweet.view_count not in (None, "")
    )


def _typenames(obj: Any) -> set[str]:
    values = set()
    if isinstance(obj, Mapping):
        typename = obj.get("__typename")
        if typename:
            values.add(str(typename))
        for value in obj.values():
            values.update(_typenames(value))
    elif isinstance(obj, list):
        for item in obj:
            values.update(_typenames(item))
    return values


def _structural_paths(obj: Any, *, prefix: str = "$", depth: int = 0) -> set[str]:
    if depth > 6:
        return {f"{prefix}.*"}
    paths = set()
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            next_prefix = f"{prefix}.{key}"
            paths.add(next_prefix)
            paths.update(_structural_paths(value, prefix=next_prefix, depth=depth + 1))
    elif isinstance(obj, list):
        paths.add(f"{prefix}[]")
        for item in obj[:5]:
            paths.update(_structural_paths(item, prefix=f"{prefix}[]", depth=depth + 1))
    return paths


def _fingerprint(values: list[str]) -> str:
    digest = hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()
    return digest[:16]


def _safe_stamp(value: str) -> str:
    return (
        value.replace(":", "")
        .replace("-", "")
        .replace("+", "Z")
        .replace(".", "-")
    )
