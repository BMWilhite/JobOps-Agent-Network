"""Local JobOps dashboard. Discovery and paid work run only from explicit actions."""
import json
import os
from pathlib import Path

import streamlit as st

from database import DB_PATH
from jobops_store import JobOpsStore
from jobops_service import screen_selected
from qualification_agent import cache_key, dry_screen
from screening_errors import BatchScreeningError

ROOT = Path(__file__).resolve().parent
CLASSIFICATIONS = ["Plausible Fit", "Needs Verification", "Likely Mismatch"]
CLASSIFICATION_COLORS = {
    "Plausible Fit": "green", "Needs Verification": "orange", "Likely Mismatch": "red",
    "Unscreened": "gray",
}


def safe_url(url):
    return url if url and url.startswith(("https://", "http://")) else None


def compensation(job):
    """Keep salary metadata short; ranking commentary belongs in the details."""
    from job_discovery import compensation_priority
    if job.get("salary_min") or job.get("salary_max"):
        low = f"{job['salary_min']:,.0f}" if job.get("salary_min") else "?"
        high = f"{job['salary_max']:,.0f}" if job.get("salary_max") else "?"
        return f"{low}–{high} (currency unverified)"
    value = compensation_priority(job).split(" | ", 1)[0]
    if value.startswith("Salary not publicly"):
        return "Salary not disclosed"
    return "Salary unverified" if value.startswith("Salary unknown") else value


def geography(job):
    """Use existing discovery categories, including legacy jobs without geography metadata."""
    if job.get("geography"):
        return job["geography"]
    from job_discovery import geographic_priority
    normalized = dict(job)
    workplace = job.get("workplaceType") or job.get("work_arrangement") or ""
    location = job.get("location") or ""
    if not workplace or workplace == "Unknown":
        if "remote" in location.casefold():
            workplace = "Remote"
    normalized["workplaceType"] = workplace
    result = geographic_priority(normalized)
    if result == "Special Relocation Required" and location.strip().casefold() in (
        "", "unknown", "united states", "usa", "us",
    ):
        return "Work arrangement unknown - Verify"
    return result


def outside_default_geography(job):
    # This is a reversible search preference, not a claim that relocation is impossible.
    return geography(job).startswith(("Outside US", "Location-restricted", "Special Relocation"))


def select_job(job_id):
    st.session_state["selected_job_id"] = job_id


def show_error(error):
    if isinstance(error, (ValueError, PermissionError)):
        st.error(str(error))
    else:
        st.error("The operation failed. Saved history is retained. No automatic retry was made. Check your API key, dependencies, connection and folder permissions before trying again.")


def consume_approval(approval_key, receipt_key):
    """Capture consent for this click and reset it before the next render."""
    st.session_state[receipt_key] = bool(st.session_state.get(approval_key, False))
    st.session_state[approval_key] = False


def consume_screening_approval(approval_key, receipt_key, batch_key):
    """Bind this submission's explicit consent to its current batch, then clear consent."""
    st.session_state[receipt_key] = {
        "approved": bool(st.session_state.get(approval_key, False)),
        "job_ids": list(st.session_state.get(batch_key, [])),
    }
    st.session_state[approval_key] = False


def requirements_panel(job, record, profile, url):
    st.write(f"**Location:** {job.get('location') or 'Unknown'}")
    st.write(f"**Compensation:** {compensation(job)}")
    st.caption("Verify published pay currency, interval and location eligibility before applying.")
    st.caption(f"{geography(job)} · Travel: {job.get('travel', 'Verify')}")
    if url:
        st.link_button("Open application page", url)
    if record and record["cache_key"] == cache_key(job, profile):
        requirements = record["result"]["requirements"]
    else:
        # Free excerpt extraction for the selected posting only; no cache writes or fit claims.
        try:
            requirements = [r.model_dump() for r in dry_screen(job, profile).requirements]
        except ValueError:
            requirements = []
        st.caption("Qualification excerpts use local heading rules. Check the full posting for context.")
    mandatory = [r for r in requirements if r["importance"] == "mandatory"]
    with st.expander(f"Mandatory qualifications ({len(mandatory)})", expanded=True):
        for requirement in mandatory:
            st.text(requirement["job_quote"])
        if not mandatory:
            st.caption("No firm mandatory qualifications extracted. Review the full posting; this does not establish a fit.")
    other = [r for r in requirements if r["importance"] != "mandatory"]
    if other:
        with st.expander("Preferred / unclear qualifications"):
            for requirement in other:
                st.caption(requirement["importance"].title())
                st.text(requirement["job_quote"])
    with st.expander("Full job description and requirements"):
        st.text(job.get("descriptionPlain") or "Description unavailable.")


def assessment_panel(store, job, record, profile, batch_options):
    selected_id = job["id"]
    notice_key = "screening_failure_" + selected_id
    if notice_key in st.session_state:
        st.error(st.session_state[notice_key])
    if record:
        result = record["result"]
        is_current = record["cache_key"] == cache_key(job, profile)
        if not is_current:
            st.badge("Previous assessment: " + result["classification"], color="gray")
            st.warning("Stale assessment: posting, profile or rules changed. Approve reevaluation to update it.")
        elif record["mode"] == "local":
            st.badge("Local preview: " + result["classification"], color=CLASSIFICATION_COLORS[result["classification"]])
            st.caption("Free local preview — not an AI-screened recommendation.")
        else:
            st.badge(result["classification"], color=CLASSIFICATION_COLORS[result["classification"]])
            st.caption("Current AI assessment · cached result · no call made to display it.")
    else:
        st.info("Unscreened. No confirmed recommendation; use a free preview or approve AI screening.")

    options = {j["id"]: j for j in batch_options}
    options.setdefault(selected_id, job)
    batch_key = "screening_batch_" + selected_id
    with st.expander("Screen a batch (up to five)"):
        selected = st.multiselect(
            "Select up to five opportunities", list(options), default=[selected_id],
            format_func=lambda key: f"{options[key]['company']} — {options[key]['title']} ({key[:6]})",
            max_selections=5, key=batch_key,
        )
    selected_jobs = [options[key] for key in selected]
    preview_col, reevaluate_col = st.columns(2)
    if preview_col.button("Free local preview / use cache", disabled=not selected or not profile.strip(), width="stretch"):
        try:
            screen_selected(store, selected_jobs, profile)
            st.rerun()
        except Exception as error:
            show_error(error)
    if reevaluate_col.button("Request reevaluation", key="reeval_" + selected_id, width="stretch"):
        store.request_reevaluation(selected_id)
        st.rerun()
    if job["reevaluate"]:
        st.caption("Reevaluation queued for this job; paid approval is still required.")
    # Keep widget identity stable when pending batch changes arrive with a submit.
    # The callback reads freshly submitted state and binds consent to those IDs.
    approval_key = "screen_approval_for_" + selected_id
    receipt_key = "screen_receipt_for_" + selected_id
    with st.form("paid_screen_for_" + selected_id, clear_on_submit=True):
        st.caption("Targets: " + "; ".join(f"{j['company']} — {j['title']}" for j in selected_jobs))
        force = st.checkbox("Reevaluate selected jobs even if a current AI result is cached", value=False)
        st.checkbox("I approve paid OpenAI screening for these selected jobs using gpt-4.1-mini (one batch request, at most five jobs).", value=False, key=approval_key)
        submit = st.form_submit_button(
            "Run approved AI screening", disabled=not selected or not profile.strip(),
            on_click=consume_screening_approval, args=(approval_key, receipt_key, batch_key),
        )
        if submit:
            st.session_state.pop(notice_key, None)
            receipt = st.session_state.pop(receipt_key, {})
            approved = receipt.get("approved", False) and receipt.get("job_ids") == selected
            try:
                with st.spinner("Checking qualifications…"):
                    screen_selected(store, selected_jobs, profile, paid=True, approved=approved, force=force)
                st.rerun()
            except BatchScreeningError as error:
                st.session_state[notice_key] = str(error)
                st.rerun()  # Refresh cached successes and metrics; consent was consumed.
            except Exception as error:
                show_error(error)
    st.caption("Current AI cache is reused unless reevaluation is requested. Approval resets after each action.")
    if record:
        with st.expander("Supporting evidence and explanation", expanded=True):
            st.write(record["result"]["explanation"])
            for requirement in record["result"]["requirements"]:
                st.write(f"**{requirement['importance'].title()} · {requirement['status']}**")
                st.text(requirement["job_quote"])
                st.write(requirement["explanation"])
                ids = requirement.get("candidate_evidence_ids") or []
                for index, quote in enumerate(requirement["candidate_quotes"]):
                    reference = f" ({ids[index]})" if index < len(ids) else ""
                    st.text("Candidate evidence" + reference + ": " + quote)
                for warning in requirement.get("evidence_warnings", []):
                    st.warning(warning)
                if not requirement["candidate_quotes"] and requirement["status"] == "unknown":
                    st.caption("Not evidenced in the supplied profile; this does not establish absence of the qualification.")
                if requirement.get("verification_question"):
                    st.write("Verify: " + requirement["verification_question"])
                st.caption("Direct specialized evidence: " + ("Yes" if requirement["direct_evidence"] else "Not established"))
    if job.get("legacy_evaluation"):
        with st.expander("Previous four-agent evaluation (preserved)"):
            st.json(job["legacy_evaluation"])
    with st.expander("Screening history"):
        st.json(store.screening_history(selected_id))


def feedback_panel(store, job, record):
    selected_id = job["id"]
    actions = st.columns(3)
    for col, name, status in zip(actions, ["Dismiss opportunity", "Reject opportunity", "Restore opportunity"], ["Dismissed", "Rejected", "Active"]):
        if col.button(name, key=f"{status}_{selected_id}", width="stretch"):
            store.set_status(selected_id, status)
            st.rerun()
    with st.form("feedback_" + selected_id, clear_on_submit=True):
        st.write("**Mark a recommendation incorrect**")
        correction = st.text_area("Explain what was wrong", placeholder="The role requires direct industry experience that my profile does not establish.", height=90)
        expected = st.selectbox("Correct classification", CLASSIFICATIONS, index=2)
        if st.form_submit_button("Save correction"):
            try:
                store.add_feedback(job, record, correction, expected)
                st.success("Correction and original evidence saved. Suggest Fix prepares a report below.")
            except Exception as error:
                show_error(error)
    feedback = store.feedback(selected_id)
    if feedback:
        if st.button("Suggest Fix", key="fix_" + selected_id):
            st.session_state["report_" + selected_id] = feedback[0]["report"]
        report = st.session_state.get("report_" + selected_id)
        if report:
            st.download_button("Download private diagnostic report", json.dumps(report, indent=2),
                               file_name="jobops_diagnostic.json", mime="application/json")
            st.download_button("Download regression-case draft", json.dumps(report["regression_case_draft"], indent=2),
                               file_name="jobops_regression_draft.json", mime="application/json")
            with st.expander("Diagnostic report"):
                st.json(report)
        with st.expander("Saved feedback", expanded=True):
            for item in feedback:
                st.write(item["correction"])
                st.caption("Expected: " + item["expected"])
        st.caption("Reports contain private evidence. Sanitize before sharing. Suggest Fix makes no API call or code change.")


def application_panel(store, job, profile, url):
    from generate_application import OUTPUT_ROOT, generate_package
    selected_id = job["id"]
    st.write("**Prepare an application package**")
    st.caption(f"For: {job['company']} — {job['title']}")
    st.caption("Resume, cover letter, editable Word files, evidence and a verification checklist.")
    st.text("Output location: " + str(OUTPUT_ROOT))
    approval_key = "document_approval_" + selected_id
    receipt_key = "document_receipt_" + selected_id
    with st.form("generate_" + selected_id, clear_on_submit=True):
        st.checkbox("I approve one paid OpenAI document-generation request for this opportunity using gpt-4.1-mini.", value=False, key=approval_key)
        if st.form_submit_button(
            "Generate approved application package", disabled=not profile.strip(),
            on_click=consume_approval, args=(approval_key, receipt_key),
        ):
            approval = st.session_state.pop(receipt_key, False)
            try:
                from job_discovery import format_job_for_evaluation
                with st.spinner("Preparing evidence-based drafts…"):
                    folder = generate_package(profile, format_job_for_evaluation(job["company"], job), url or "", approved=approval)
                    store.save_package(selected_id, folder)
                st.success("Draft package saved. Review every claim before applying.")
            except Exception as error:
                show_error(error)
    for package in store.packages(selected_id):
        st.text("Saved package: " + package["folder"])


def main():
    st.set_page_config(page_title="JobOps", page_icon="🧭", layout="wide")
    st.html("""<style>
        .stMainBlockContainer {padding-top: 1.25rem; padding-bottom: 1rem;}
        .st-key-opportunity_list button p {white-space: normal; text-align: left;}
        .st-key-opportunity_list p, .st-key-job_details [data-testid="stText"] {
            overflow-wrap: anywhere; white-space: pre-wrap;
        }
    </style>""")
    st.header("JobOps")
    store = JobOpsStore(os.environ.get("JOBOPS_DB_PATH", str(DB_PATH)))
    store.initialize()
    profile_path = Path(os.environ.get("JOBOPS_PROFILE_PATH", str(ROOT / "candidate_profile.md")))
    try:
        profile = profile_path.read_text(encoding="utf-8")
    except OSError:
        profile = ""
    if not profile.strip():
        st.warning("Add your private candidate_profile.md before screening or generating documents. Discovery remains available.")

    with st.sidebar:
        st.header("Discovery")
        st.caption("Free public job boards. Refresh runs only when clicked. Unavailable boards retain saved listings.")
        if st.button("Refresh job discovery", width="stretch"):
            from batch_evaluate import find_candidates
            notices = []
            try:
                with st.spinner("Checking configured Ashby and Greenhouse boards…"):
                    candidates = find_candidates(include_tracked=True, include_filtered=True, warnings=notices)
                    count = store.upsert_candidates(candidates)
                st.success(f"Found {len(candidates)} relevant postings; {count} newly saved.")
            except Exception as error:
                show_error(error)
            for notice in notices:
                st.warning(notice)
        st.caption("Local storage: " + str(store.path))
        st.caption("Your profile and selected posting go to OpenAI only after paid approval. Reports and drafts contain private information.")

    jobs = store.jobs()
    lookup = {j["id"]: j for j in jobs}
    current = {}
    records = {}
    for job in jobs:
        current[job["id"]] = store.screening(job["id"], cache_key(job, profile), ai_only=True) if profile else None
        records[job["id"]] = current[job["id"]] or store.screening(job["id"])

    def label_for(job):
        record = current[job["id"]]
        return record["result"]["classification"] if record else "Unscreened"

    screened_count = sum(bool(v) for v in current.values())
    counts = [sum(label_for(j) == label for j in jobs) for label in CLASSIFICATIONS]
    for col, label, value in zip(st.columns(6), ["Discovered", "Unscreened", "AI Screened"] + CLASSIFICATIONS,
                               [len(jobs), len(jobs) - screened_count, screened_count] + counts):
        col.metric(label, value)
    st.caption("Counts include saved history. Discovered is the whole collection; only current AI results qualify as AI Screened.")
    if not jobs:
        st.info("Click Refresh job discovery to begin. No paid work runs on page load.")
        return

    list_col, detail_col = st.columns([5, 7], gap="medium")
    with list_col:
        st.subheader("Opportunities")
        search = st.text_input("Search company or title", key="job_search").casefold().strip()
        stage_col, qualification_col = st.columns(2)
        stage = stage_col.selectbox("Review stage", ["Discovered", "Unscreened", "AI Screened"], key="review_stage")
        classification = qualification_col.selectbox("Qualification filter", ["All"] + CLASSIFICATIONS, key="qualification_filter")
        status_col, location_col = st.columns(2)
        status = status_col.selectbox("Opportunity status", ["Active", "All", "Dismissed", "Rejected"], key="opportunity_status")
        show_all_locations = location_col.checkbox("Show all locations", value=False, key="show_all_locations",
            help="Include outside-US, state-restricted remote and other relocation locations. Unknown eligibility remains visible for review.")
        visible = [j for j in jobs
                   if (status == "All" or j["status"] == status)
                   and (stage == "Discovered" or (stage == "AI Screened") == bool(current[j["id"]]))
                   and (classification == "All" or label_for(j) == classification)
                   and (show_all_locations or not outside_default_geography(j))
                   and (not search or search in (j["company"] + " " + j["title"]).casefold())]
        from batch_evaluate import priority_score
        visible.sort(key=lambda j: (
            CLASSIFICATIONS.index(label_for(j)) if label_for(j) in CLASSIFICATIONS else 3,
            -priority_score((j["company"], j, geography(j), j.get("travel", ""))),
        ))
        if st.session_state.get("selected_job_id") not in lookup:
            st.session_state["selected_job_id"] = visible[0]["id"] if visible else None
        selected_id = st.session_state.get("selected_job_id")
        st.caption(f"{len(visible)} shown / {len(jobs)} discovered · click a job to review")
        with st.container(height=420, border=True, key="opportunity_list"):
            if not visible:
                st.info("No jobs match. Broaden filters or enable Show all locations to inspect history.")
            for job in visible:
                st.button(f"{job['company']} · {job['title']}", key="select_job_" + job["id"],
                          type="primary" if job["id"] == selected_id else "secondary", width="stretch",
                          on_click=select_job, args=(job["id"],))
                label = label_for(job)
                st.badge(label, color=CLASSIFICATION_COLORS[label])
                st.caption(f"{job.get('location') or 'Unknown location'} · {compensation(job)}")
                # This list was rendered for inspection; scanning and filtering do not mark hidden jobs.
                store.mark_displayed(job["id"])

    with detail_col, st.container(key="job_details"):
        if selected_id is None:
            st.info("Select an opportunity from the list to review requirements and take action.")
            return
        job = lookup[selected_id]
        record = records[selected_id]
        st.subheader(job["title"])
        st.caption(f"{job['company']} · {job['status']}")
        st.badge(label_for(job), color=CLASSIFICATION_COLORS[label_for(job)])
        if selected_id not in {j["id"] for j in visible}:
            st.caption("Selected job is outside the current list filters. Details remain open until you select another job.")
        store.mark_displayed(selected_id)
        url = safe_url(job.get("applyUrl") or job.get("jobUrl"))
        requirements, assessment, feedback, application = st.tabs(
            ["Requirements", "AI Assessment", "Feedback", "Application"],
            height=500, key="job_detail_tabs",
        )
        with requirements:
            requirements_panel(job, record, profile, url)
        with assessment:
            assessment_panel(store, job, record, profile, visible)
        with feedback:
            feedback_panel(store, job, record)
        with application:
            application_panel(store, job, profile, url)


if __name__ == "__main__":
    main()
