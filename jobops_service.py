"""Shared UI/CLI workflow with approval enforced at the paid-call boundary."""
from qualification_agent import cache_key, dry_screen, screen_batch
from screening_errors import BatchScreeningError


def screen_selected(store, jobs, profile, *, paid=False, approved=False, force=False):
    if paid and not approved:
        raise PermissionError("Confirm the paid screening request before proceeding.")
    if not profile.strip():
        raise ValueError("Candidate profile is empty.")
    if not 1 <= len(jobs) <= 5 or len({j["id"] for j in jobs}) != len(jobs):
        raise ValueError("Select one to five distinct jobs.")
    cached = []
    pending = []
    for job in jobs:
        key = cache_key(job, profile)
        result = store.screening(job["id"], key, ai_only=True)
        if result and not (paid and (force or job.get("reevaluate"))):
            cached.append(result["result"])
        else:
            pending.append(job)
    if not pending:
        return cached, 0
    failure = None
    if paid:
        corrections = [f["correction"] for j in pending for f in store.feedback(j["id"])]
        try:
            results = screen_batch(pending, profile, approved=approved, corrections=corrections)
        except BatchScreeningError as error:
            results = error.valid_results
            failure = error
    else:
        results = [dry_screen(j, profile) for j in pending]
    lookup = {j["id"]: j for j in pending}
    for result in results:
        store.save_screening(result.job_id, cache_key(lookup[result.job_id], profile),
                             "ai" if paid else "local", result.model_dump())
    if failure:
        failure.saved_count = len(results)
        raise failure
    return cached + [r.model_dump() for r in results], 1 if paid else 0
