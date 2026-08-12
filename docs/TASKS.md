# Implementation Tasks

This is the living checklist for the remaining product work. Completed items are marked with a checked box and strikethrough text so the file shows both status and history.

## Production Release Control

- [ ] Pin an approved `ProtocolReleaseManifest` in the production execution path.
- [ ] Persist recipe-level validation records with `release_id`, `recipe_revision_id`, `composition_hash`, and runtime version.
- [ ] Reject production execution when the pinned release is not approved.

## SEARCH_TWEETS Vertical Slice

- [x] ~~Integrate `SEARCH_TWEETS` pagination validation into the production worker path.~~
- [ ] Add explicit cursor-loop evidence to the investigation package when pagination fails.
- [ ] Expand search request inputs to cover the remaining stable contract fields from the product spec.
- [ ] Validate the full `SEARCH_TWEETS` acquisition recipe as a single release-bound unit.

## Runtime and Drift

- [ ] Surface protocol drift reports when the approved recipe starts failing in production.
- [ ] Add recipe-compatibility checks so a parser or operation change forces a fresh validation run.
- [ ] Promote current raw-evidence validation to record the validated recipe composition hash.

## Production Hardening

- [ ] Drain and reconcile any stale outbox backlog before widening rollout.
- [ ] Expand monitoring and release-risk handling around the approved search route.
- [ ] Add the next capability vertical slice after `SEARCH_TWEETS` is fully release-governed.
