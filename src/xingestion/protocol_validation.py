from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from xingestion.xprotocol.runtime import parse_search_tweets_page


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
            bottom_cursor_present=page.next_cursor is not None,
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
