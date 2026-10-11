
# JobOps Agent Network

A Python-based, multi-agent AI system for evaluating job
opportunities, challenging candidate-fit assessments, and
managing a structured job-search pipeline using SQLite.

## Launch the local MVP (Windows PowerShell)

Open PowerShell in this project folder. The existing virtual environment can
be used without activating it or changing PowerShell's execution policy:

```powershell
# Run this only if .venv does not already exist:
python -m venv .venv

.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

Open **http://127.0.0.1:8501**. Stop the app with **Ctrl+C** in PowerShell.
Python 3.14 is the tested environment. Streamlit binds to your local machine,
and usage telemetry is disabled in `.streamlit/config.toml`.

Discovery, cached assessments, free local previews, feedback, and diagnostic
reports work without an OpenAI API key. For paid actions, set your key in the
same PowerShell window before starting the app:

```powershell
$jobOpsApiKey = Read-Host "OpenAI API key" -AsSecureString
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new("", $jobOpsApiKey).Password
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

For screening and application drafts, create an ignored `candidate_profile.md`
with verified background and contact details. `candidate_profile.example.md`,
`job_posting.example.txt`, `example_evaluation.json`, and test candidate fixtures
are fictional public examples, separate from private user data. Discovery can
run before a private profile is supplied. Never publish the private profile or
copy its contents into public examples or tests. Sanitize private diagnostic
reports before sharing them.

### Use the dashboard

1. Click **Refresh job discovery** to query the configured Ashby and Greenhouse
   boards. Results are stored locally; unavailable boards retain earlier jobs.
2. Search and filter the fixed-height opportunity list on the left. Click a job
   to open its details on the right. The selected job stays open across reruns,
   discovery refreshes and filter changes, including when it leaves the list.
3. Use **Requirements** for location, concise compensation, the application link,
   mandatory qualification excerpts and the full posting. Unknown eligibility
   remains available for review. **Show all locations** also includes outside-US,
   state-restricted remote and other relocation opportunities; nothing is deleted.
   This default geographic filter is a search preference, not a disqualification.
4. In **AI Assessment**, **Free local preview / use cache** makes no AI calls.
   Actions target the selected job by default. Expand **Screen a batch (up to
   five)** to select additional jobs. Check the paid approval box and click **Run
   approved AI screening** for paid work. Current cached results are reused unless
   reevaluation was requested. **Request reevaluation** queues the selected job;
   it still needs paid approval. Review the supporting evidence in the same tab.
5. In **Feedback**, save a correction under **Mark a recommendation incorrect**.
   **Suggest Fix** prepares a free diagnostic report and regression-case draft.
   Sanitize their private evidence before sharing. Dismiss, reject and restore
   controls preserve the job, feedback and assessment history. No code edits happen.
6. In **Application**, check its separate paid approval box and click **Generate
   approved application package**. The panel shows the selected job and output
   folder. Review all drafts before applying yourself.

Top metrics include the whole saved collection. **Discovered** includes every job;
**Unscreened** means no current qualification AI result; **AI Screened** means a
current cached AI result exists. Free previews and stale assessments remain
inspectable but are not confirmed recommendations. Use the review-stage and
qualification filters to distinguish these groups. Green, orange and red badges
identify Plausible Fit, Needs Verification and Likely Mismatch, with explicit
labels for local previews and historical assessments. Only current AI results
count toward classification totals. Page refreshes never trigger paid actions,
and each paid action needs fresh approval.

### Qualification screening and limits

The existing Agents SDK and `gpt-4.1-mini` screen one selected batch at a time.
`candidate_evidence.py` deterministically catalogs candidate-profile paragraphs
and bullets as source IDs such as P001, scoped to the profile snapshot. The
screener receives this catalog and returns candidate evidence IDs, not candidate
quotations. Python resolves IDs to the original passages, checks exact job IDs
and source-grounded posting requirements, and derives the classification:

- **Plausible Fit:** mandatory qualifications have supporting evidence.
- **Needs Verification:** qualifications or their mandatory status remain uncertain.
- **Likely Mismatch:** a mandatory qualification is contradicted, or multiple
  mandatory specialized requirements lack direct evidence.

Missing information stays **unknown**; a likely mismatch due to multiple evidence
gaps is a practical search assessment, not proof of absent credentials. Transferable
onboarding does not establish corporate-card or fintech implementation experience.
Preferred qualifications do not become blockers. Motive and Engine regression
fixtures protect against matching job titles outweighing specialized requirements.

The free preview uses conservative heading/phrase rules and cannot verify a
candidate's qualifications. It is labeled separately from AI screening. Live AI
results still need human review: source grounding cannot prove that an AI
interpreted the evidence correctly, or that it extracted every requirement.
Large batches are rejected rather than silently truncating descriptions. Exact API cost depends
on input/output length; no dollar estimate is guaranteed.

AI cache keys include the job description, candidate profile, model and rule version.
Changed input makes old results stale, while history remains inspectable. Failed
requests are not retried automatically. A failed request can still incur provider
charges if the provider processed it before the failure. The UI never resubmits it.

### Private storage and application packages

The existing `jobops.db` is reused. On the first UI launch, additive `mvp_jobs`,
`mvp_screenings`, `mvp_feedback` and `mvp_packages` tables and an index are created.
Prior job/evaluation rows are imported as a dashboard view and remain untouched
in their original tables. Stable posting identifiers prevent repeat discovery
from duplicating jobs. Scans do not mark jobs displayed; dashboard rendering does.

Packages save under **your Windows home folder\Documents\JobOps Applications**,
outside this repository. Each package contains:

- `Resume.docx` and `Cover_Letter.docx` (editable Word files).
- `resume.md` and `cover_letter.md` (plain Markdown drafts).
- `verification_checklist.md`, `source_evidence.json` and `application_link.txt`.

The application writer selects IDs and numbered content units from the same
candidate evidence catalog. Python validates those selections against the supplied
profile before export and renders the factual document text itself; the model
does not reproduce quotations or write unrestricted candidate claims. Invalid
IDs and inappropriate aspiration or employment citations are rejected. The
renderer excludes internal guidance, preserves estimate qualifiers, groups
verified employment fields, and keeps project work separate from employment.
Missing verified contact details remain explicit placeholders. A provenance
sidecar retains resolved source passages; internal IDs stay out of the documents.

Grounding protects against invented source text but does not independently verify
the profile's truth or guarantee good relevance, complete qualifications, or
application-ready wording. Review every claim, employer, date, credential,
metric, placeholder, and the final Word layout before submitting a draft yourself.
Nothing submits applications, sends email, or modifies its own code.

Paid approval authorizes sending your profile and selected posting to OpenAI.
Hosted tracing and Responses storage are disabled for model runs using the
[official SDK tracing controls](https://developers.openai.com/cookbook/examples/agents_sdk/sandboxed-code-migration/sandboxed_code_migration_agent).
This does not promise zero provider retention. API keys are read from the environment.
Private profiles, databases, environment files, Word files and private export folders
are excluded by `.gitignore`. Keep downloaded feedback reports outside the repository.

### Offline tests and CLI

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe test_save_audit.py
.\.venv\Scripts\python.exe test_decision_pipeline.py
```

Tests use fictional fixtures, temporary databases and mocked AI responses. They
make no paid calls and do not alter the real database. Streamlit tests exercise
discovery clicks, approval gates, page reruns, feedback, previews and dispositions.

Existing CLI commands remain available:

```powershell
.\.venv\Scripts\python.exe batch_evaluate.py
.\.venv\Scripts\python.exe briefing.py
.\.venv\Scripts\python.exe generate_application.py             # Free dry run
.\.venv\Scripts\python.exe generate_application.py --generate  # Prompts for approval
.\.venv\Scripts\python.exe orchestrator.py                     # Prompts for approval
```

`batch_evaluate.py` retains the full four-agent evaluation workflow after its
confirmation prompt. The cheaper qualification-only batch screener is available
in the dashboard. The orchestrator's `plan` reference and explicit save call are fixed.

## The Problem

Evaluating job opportunities manually is time-consuming,
inconsistent, and vulnerable to subjective bias.

Job seekers may overestimate their qualifications for
attractive opportunities or underestimate transferable
experience when entering new industries.

JobOps explores how specialized AI agents, structured
data, and independent review can improve that process.

## The Solution

The original CLI processes job descriptions through a four-agent
workflow, separate from dashboard qualification screening:

1. **Job Extraction Agent**
   Converts unstructured job descriptions into structured
   fields, including compensation, location, responsibilities,
   and required versus preferred qualifications.

2. **Fit Analyst Agent**
   Evaluates the opportunity against an editable candidate
   profile using a transparent 100-point scoring framework.

3. **Skeptical Reviewer Agent**
   Independently audits the first assessment, challenges
   unsupported assumptions, and revises category scores.

4. **Application Strategist Agent**
   Produces an Apply, Hold, or Skip recommendation,
   identifies hiring risks, and develops a resume strategy.

A Python orchestrator coordinates the agents sequentially
using the OpenAI Agents SDK.

## Architecture

```text
Public Ashby / Greenhouse boards
    -> discovery and ranking -> local SQLite opportunity history
                                  <-> Streamlit dashboard
Private candidate profile -> deterministic source-ID evidence catalog
                                  |
Selected posting + explicit approval
    -> qualification AI -> ID/source validation -> cached classification
    -> application selections -> profile validation -> Python renderer
         -> Markdown + editable DOCX + provenance -> human review/submission
Dashboard feedback -> saved corrections + local diagnostics

Separate four-agent CLI:
Posting + profile + approval -> extraction -> fit analyst -> skeptical reviewer
    -> application strategist -> decision rules -> JSON + SQLite + SQL briefing
```

The dashboard's qualification screening is separate from the original four-agent
scoring workflow. Both require explicit approval for paid requests. See
[ARCHITECTURE.md](ARCHITECTURE.md) for module and database details.

## Technology Stack

- Python 3.14
- OpenAI Agents SDK
- Pydantic for structured AI outputs
- Streamlit for the local dashboard
- python-docx for editable Word exports
- SQLite for persistent data storage
- SQL for pipeline analysis
- VS Code for development

The application runs locally without cloud infrastructure
or a separate database server.

## Scoring Framework

| Category | Maximum Points |
|---|---:|
| Hard requirement fit | 30 |
| Work shape and responsibilities | 25 |
| Relevant experience | 15 |
| Compensation fit | 10 |
| Geographic fit | 10 |
| Mission and career trajectory | 10 |
| **Total** | **100** |

Scores are AI-generated assessments, not objective
probabilities of receiving an interview or offer.

Python validates category score ranges and applies
additional decision rules.

Unresolved qualification concerns require human review.

## Database Design

The original four-agent workflow uses three relational tables; the dashboard
adds the private MVP tables described above.

### jobs
Stores company information, job descriptions, salary
ranges, location, and work arrangements.

### evaluations
Stores initial and reviewed scores, recommendations,
strengths, gaps, blocker claims, and reviewer findings.

### applications
Tracks application status, dates, and notes.

These original tables are connected through job IDs. The dashboard adds:

| Table | Stored data |
|---|---|
| `mvp_jobs` | Stable posting IDs, full postings, discovery timestamps and dispositions |
| `mvp_screenings` | Local/AI assessment snapshots and versioned cache keys |
| `mvp_feedback` | Corrections, expected classifications, snapshots and diagnostics |
| `mvp_packages` | Selected job IDs and generated package folder references |

Dashboard records preserve prior rows and screening history. Private document
contents remain in external output folders; all database data stays local.

## SQL Capabilities

The database supports queries involving:

- SELECT and WHERE
- ORDER BY
- INNER JOIN
- COUNT, AVG, and GROUP BY
- CASE expressions
- Common Table Expressions (CTEs)

These allow opportunities to be filtered, compared,
categorized, and ranked.

## Quick Demo

JobOps includes a fictional candidate profile and job posting so
the four-agent pipeline can be tested without personal information.

1. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

2. Set the OPENAI_API_KEY environment variable.

3. Run the demonstration:

   ```powershell
   python demo.py
   ```

After explicit paid confirmation, the demo runs all four agents and writes
example_evaluation.json using only the fictional inputs.
It does not modify the private job database. Running the agents
requires OpenAI API credits.

## CLI Discovery and Four-Agent Evaluation

JobOps now supports job discovery from public Ashby and
Greenhouse job boards.

The discovery pipeline:
1. Retrieves postings from configured company boards.
2. Filters previously evaluated jobs using normalized URLs
   and tracked job titles.
3. Prioritizes opportunities using job title, location,
   compensation, and travel-related signals.
4. Presents a ranked shortlist for human review.
5. Evaluates up to two selected jobs per batch, only after
   explicit confirmation.
6. Saves evaluations to SQLite and produces a briefing.

Supported board configurations:
- `boards.json` for Ashby
- `greenhouse_boards.json` for Greenhouse

Preview opportunities:

    python batch_evaluate.py

Discovery itself does not require OpenAI API calls.
AI evaluation runs only after user confirmation and
incurs API usage costs.

View previously evaluated, unapplied opportunities:

    python briefing.py

Run the offline tests:

    python test_save_audit.py
    python test_decision_pipeline.py

Both tests use fictional public example data and temporary
databases. They do not modify the user's real job database.

## Local Setup

Requirements:
- Python 3.14
- OpenAI API access with available credits for paid screening/evaluation/generation

Install dependencies:

    python -m pip install -r requirements.txt

Initialize the database:

    python database.py

Create a local candidate_profile.md file containing
the candidate's background and preferences.

Create job_posting.txt containing a job description.

Set OPENAI_API_KEY as an environment variable.

Run the complete workflow:

    python orchestrator.py

The system evaluates the posting, writes the latest
evaluation to JSON, and saves new records to SQLite.

Run the saved ranked-pipeline query:

    python -m sqlite3 jobops.db

Then execute the SQL in ranked_queue.sql.

## Initial Testing

The system was tested against five real job postings.

Testing demonstrated:
- Structured extraction of job requirements
- Multi-agent evaluation and independent review
- Different initial and reviewed fit scores
- Application recommendations and explanations
- SQLite persistence across multiple jobs
- SQL-based pipeline ranking

## Limitations

- AI scoring can vary between executions.
- The reviewer can still make unsupported assumptions.
- AI qualification classification requires evidence review.
- Application recommendations require human judgment.
- The system does not independently verify job availability.
- Discovery is limited to configured public job boards.
- Application submission and submitted-status tracking remain manual.
- The latest JSON output is overwritten on each run.
- The project is a local prototype, not a production service.

## Future Improvements

- Expanded job-board coverage
- Score consistency testing
- Job deduplication improvements
- Application status management
- PDF export and additional application-document validation

## Project Purpose

JobOps was built to explore practical AI-agent
orchestration, structured outputs, SQL, and the design
of operational decision-support systems.

The emphasis is on creating a useful workflow while
critically evaluating AI-generated recommendations.
