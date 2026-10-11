"""Shared screening exceptions; no model, UI, storage or network dependencies."""


class BatchScreeningError(ValueError):
    """Safe diagnostics plus independently validated results, never raw model text."""

    def __init__(self, jobs, failures, valid_results=(), unexpected_count=0):
        self.valid_results = list(valid_results)
        self.failures = dict(failures)
        self.unexpected_count = unexpected_count
        self.saved_count = 0
        self.labels = {j["id"]: f"{j.get('company', 'Unknown company')} — {j.get('title', 'Untitled job')} ({j['id'][:8]})" for j in jobs}
        super().__init__("Batch screening validation failed.")

    def __str__(self):
        details = [f"{self.labels[key]}: {reason}" for key, reason in self.failures.items()]
        if self.unexpected_count:
            details.append(f"Ignored {self.unexpected_count} result(s) with unrecognized job IDs; none were assigned to a selected job.")
        return (f"Saved {self.saved_count} valid new AI assessment(s). " + " ".join(details) +
                " Failed jobs received no new assessment; existing history is retained. "
                "Select only failed jobs (or a smaller batch) and check approval again to retry. No automatic retry was made.")
