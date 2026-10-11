
# JobOps Agent Network: System Architecture

## Overview

JobOps is a locally executed, multi-agent AI workflow
for evaluating job opportunities against a candidate's
career experience and preferences.

The implemented MVP combines a Streamlit dashboard, public-board discovery,
source-ID qualification screening, feedback, and editable Word application
packages with the original four-agent CLI workflow. Python manages execution,
Pydantic structures responses, and SQLite stores local history. Paid requests
require explicit user approval; generated drafts require human review.

## Architecture Diagram

```text
Public job boards -> discovery/ranking -> mvp_jobs <-> Streamlit dashboard
Private profile -> deterministic evidence catalog       |
                                                       +-> free local preview
Selected posting + explicit approval + catalog          |
    -> qualification agent -> ID/requirement validation -> mvp_screenings
    -> application selection agent -> profile validation -> Python rendering
         -> Markdown / DOCX / source provenance -> human review
Dashboard corrections -> mvp_feedback -> local diagnostic downloads
Generated package folder references -> mvp_packages

Original CLI workflow (separate approval):
Posting + profile -> extraction -> fit analyst -> skeptical reviewer
    -> application strategist -> Python decision rules
    -> latest evaluation JSON -> jobs / evaluations / applications
    -> SQL ranked queue and briefing
```

## Implemented Dashboard and Source Evidence

`streamlit_app.py` presents a fixed-height opportunity list and a selected-job
panel with Requirements, AI Assessment, Feedback, and Application tabs. Search,
geographic and classification filters distinguish discovered, unscreened, current
AI-screened, and historical results. Unscreened postings are not recommendations.
Dismiss, reject, and restore actions preserve history.

`candidate_evidence.py` creates deterministic paragraph/bullet IDs and source
context from the supplied profile. IDs are scoped to the profile snapshot and
catalog version. Aspirations, skills, employment, and documented achievements
have distinct evidence kinds; the profile's claims are not independently verified.

`qualification_agent.py` passes this catalog and full selected descriptions to
one approved model request, for up to five jobs. The model returns exact job IDs,
posting requirement excerpts, candidate evidence IDs, and structured assessments.
Python resolves candidate text from the catalog, validates job identity and
posting excerpts, and applies classification rules. It never trusts a
model-written candidate quotation as source evidence. Missing evidence remains
unknown with verification questions. Specialized requirements require direct
evidence; transferable skills and preferred qualifications do not establish
mandatory specialized experience. Safe independent results survive partial
batch failures; missing, duplicate, or invalid results remain unscreened.

`jobops_service.py` enforces approval at the paid boundary and reuses valid
cached results. Cache keys include the posting, profile, model, rule version and
catalog version, preserving older history without confusing evidence formats.
UI approval is consumed per submission and bound to the selected batch. Paid
requests are not automatically retried. `ai_runtime.py` disables hosted tracing,
Responses storage, and SDK retries; this is not a zero-retention promise.

Feedback saves corrections and assessment snapshots. `feedback_report.py`
produces local diagnostics and regression-case drafts without AI calls or code
changes. Reports can contain private evidence and require sanitization before
sharing.

`application_documents.py` defines the source-selection response schema. The
writer selects verified profile IDs and content-unit indices. `application_evidence.py`
and `application_rendering.py` validate selections against that profile snapshot
before export, then render source-grounded facts, actual employment fields,
separate project work, estimate qualifiers, and contact details or placeholders.
Internal guidance and IDs are excluded from employer-facing text. The cover
letter uses a Python-owned template with source-grounded examples and posting
context. It still needs editorial review; source grounding is not a guarantee
of persuasive writing or qualification accuracy.

`generate_application.py` exports each approved package to a new folder outside
the repository, including Markdown, a verification checklist, source provenance,
and editable DOCX files through `word_export.py`. Export completes before the
package is published locally. No automatic applications or messages are sent.
Review claims, dates, metrics, contact placeholders, and layout before submission.

Public candidate/job examples, evaluation examples, and candidate test fixtures
are fictional. Private profiles, local databases, credentials, generated
applications, and personal reports must remain excluded from Git. Ignoring a
file does not untrack it or remove it from existing history.

## V2: Job Discovery and Human Review

V2 adds a discovery layer before the existing
four-agent evaluation pipeline.

### Discovery Sources

- `job_discovery.py` retrieves public Ashby postings.
- `greenhouse_discovery.py` retrieves public Greenhouse
  postings and normalizes their content.
- `boards.json` configures Ashby company boards.
- `greenhouse_boards.json` configures Greenhouse boards.

### Discovery Workflow

`batch_evaluate.py` coordinates the discovery workflow:

1. Fetch postings from configured public job boards.
2. Normalize job information across sources.
3. Exclude previously evaluated jobs using normalized
   posting URLs and tracked job titles.
4. Filter and prioritize opportunities using role,
   geography, compensation, and travel-related signals.
5. Display a ranked shortlist for human review.
6. Let the user select up to two jobs.
7. Require explicit confirmation before AI evaluation.
8. Run the four-agent evaluation workflow.
9. Save results to SQLite and display the briefing.

Discovery and ranking do not require OpenAI API calls.
AI evaluation incurs usage costs only after confirmation.

### Decision Support

- `decision_rules.py` applies deterministic final
  recommendation rules.
- `blocker_utils.py` normalizes blocker claims.
- `briefing.py` summarizes unapplied opportunities.
- `test_save_audit.py` verifies database persistence.
- `test_decision_pipeline.py` checks Apply, Hold, and Skip
  behavior using fictional public test data.

The system does not automatically submit applications.
Its job rankings and AI assessments require human review.

The existing manual job-evaluation workflow remains
available alongside automated discovery.

## 1. Orchestration Design

The system uses code-managed orchestration.

The Python function `evaluate_job()` coordinates
each agent through the OpenAI Agents SDK.

Each agent is a separate SDK Agent with its own
instructions and structured output schema.

The workflow is sequential:

1. Extract the job.
2. Evaluate candidate fit.
3. Independently review the assessment.
4. Develop an application strategy.
5. Validate scores and apply decision rules.
6. Return a structured result.

The Python orchestrator controls execution order.

This is not an autonomous manager LLM.
It is a deterministic workflow coordinating
multiple specialized AI agents.

### Why This Architecture?

The tasks have clear dependencies.

The reviewer needs the analyst's assessment.
The strategist needs the reviewer's findings.

Code-managed orchestration is appropriate because
it is simple, predictable, and easier to debug
than allowing another model to dynamically
decide which agents to invoke.

## 2. Specialized Agents

### Extraction Agent

File: extraction_agent.py

Input:
- Unstructured job posting text

Output:
- Company and job title
- Location and work arrangement
- Salary range
- Responsibilities
- Mandatory qualifications
- Preferred qualifications
- Technical and domain requirements
- Experience requirements

Uses a Pydantic schema to structure the result.

### Fit Analyst

File: fit_analyst.py

Inputs:
- Structured job data
- Candidate profile

Output:
- Category scores
- Strong and partial matches
- Missing qualifications
- Potential hard blockers
- Career and compensation assessment
- Supporting reasoning

Scores six categories totaling 100 points.

### Skeptical Reviewer

File: skeptical_reviewer.py

Inputs:
- Structured job data
- Candidate profile
- Initial fit assessment

Output:
- Revised category scores
- Disputed claims
- Justified strengths
- Blocker claims
- Unresolved questions
- Recruiter reality check

The reviewer runs as a separate model invocation
with deliberately skeptical instructions.

It provides an additional review layer but is
not guaranteed to be unbiased or correct.

### Application Strategist

File: application_strategist.py

Inputs:
- Candidate profile
- Structured posting
- Initial assessment
- Skeptical review
- Reviewed fit score

Output:
- Apply, Hold, or Skip recommendation
- Explanation
- Strongest evidence
- Hiring risks
- Resume positioning
- Application timing
- Skills worth developing

## 3. Scoring and Decision Rules

Scoring categories:

- Hard requirement fit: 30 points
- Work shape: 25 points
- Relevant experience: 15 points
- Compensation: 10 points
- Geography: 10 points
- Mission and trajectory: 10 points

Python validates each category's range and
calculates the total.

Current decision rules:

- Scores below 60 produce Skip.
- AI-identified confirmed blocker claims at
  scores of 60+ cause Hold pending verification.
- Apply recommendations below 70 become Hold.
- Other recommendations follow the strategist.

Important: AI blocker claims are not independently
verified by the current system.

Scores are advisory judgments, not probabilities
of recruitment success.

## 4. Database Architecture

File: database.py
Database: jobops.db

The original CLI uses the following three tables. `jobops_store.py` adds four
MVP tables to the same local database without rewriting the original records.

### jobs
Stores job descriptions and extracted information.

Primary key: id

### evaluations
Stores fit assessments and reviewer findings.

Primary key: id
Foreign key: job_id -> jobs.id

### applications
Stores application status, dates, and notes.

Primary key: id
Foreign key: job_id -> jobs.id

The job ID connects records across the original tables. Dashboard tables use
stable posting IDs, with additive initialization:

| Table | Purpose |
|---|---|
| `mvp_jobs` | Posting payloads, discovery timestamps, displayed state, dispositions and reevaluation requests |
| `mvp_screenings` | Local/AI snapshots, cache keys and screening history |
| `mvp_feedback` | Corrections, expected classifications, source snapshots and diagnostic reports |
| `mvp_packages` | Job associations and external package folder paths |

An index supports screening-cache lookup. Legacy jobs and their latest evaluations
are imported as dashboard views while their original rows remain intact. Full
application documents stay outside the repository in private output folders.

## 5. Persistence

File: save_evaluation.py

The main workflow:

1. Evaluates the job using four agents.
2. Saves the complete result to
   latest_evaluation.json.
3. Reads that JSON into the SQLite importer.
4. Inserts job, evaluation, and application records.

The importer checks for existing jobs using
the company, title, and original description.

The current JSON output is overwritten on
each successful evaluation.

## 6. SQL Analytics

File: ranked_queue.sql

The ranked pipeline query:

- Joins jobs, evaluations, and applications.
- Filters out applied opportunities.
- Prioritizes Apply over Hold and Skip.
- Sorts by reviewed fit score within each category.

Additional SQL concepts demonstrated include:

- SELECT
- WHERE
- ORDER BY
- JOIN
- COUNT and AVG
- GROUP BY
- CASE
- Common Table Expressions

## 7. Design Tradeoffs

### Why SQLite?

SQLite is lightweight, local, inexpensive,
and sufficient for a single-user prototype.

A cloud database would add unnecessary
infrastructure at this stage.

### Why Four Agents?

Specialization separates extraction, evaluation,
criticism, and application strategy.

This makes each responsibility easier to inspect
and improve independently.

It does not guarantee better performance than
a single well-designed model call.

### Why Structured Outputs?

Pydantic schemas make output fields predictable
and easier to pass between agents and into SQLite.

They enforce data structure, not factual accuracy.

## 8. Known Limitations

- Discovery covers configured public Ashby and Greenhouse boards, not the entire job market.
- No automatic application submission.
- No production deployment.
- No formal benchmark proving review accuracy.
- Scores can vary across executions.
- Hard blocker verification is incomplete.
- The application status is initially set
  to Not Applied, regardless of real history.
- The latest JSON file is overwritten.
- Discovery deduplicates by normalized posting URL and tracked title; database import uses separate matching rules.
- AI usage requires API credits.
- Manual review remains necessary.

## 9. Future Improvements

Potential improvements include:

- Structured qualification confidence levels
- Better hard-blocker verification
- Scoring consistency tests
- Broader job-board coverage and improved discovery filtering
- Submitted-application status editing
- Cost and token tracking

These remaining ideas are outside the implemented MVP scope.

## 10. Engineering Lessons

This project demonstrates hands-on experience with:

- Python application structure
- Multi-agent SDK execution
- Structured AI output schemas
- Sequential workflow orchestration
- Model output validation
- Basic relational database design
- Practical SQL queries
- Debugging Python and SQL errors
- Evaluating weaknesses in AI-generated decisions

JobOps is a functioning local prototype and
decision-support tool, not a production-grade
automated recruiting system.
