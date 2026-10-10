
# JobOps Agent Network: System Architecture

## Overview

JobOps is a locally executed, multi-agent AI workflow
for evaluating job opportunities against a candidate's
career experience and preferences.

The system uses four specialized OpenAI Agents SDK
agents, a Python orchestrator, structured Pydantic
outputs, and a SQLite database.

## Architecture Diagram

```text
         Raw Job Posting
                |
                v
      +-------------------+
      | Extraction Agent  |
      | Structure the job |
      +-------------------+
                |
                v
      +-------------------+
      | Fit Analyst       |
      | Initial scoring   |<--- Candidate Profile
      +-------------------+
                |
                v
      +-------------------+
      | Skeptical Reviewer|
      | Audit and revise  |<--- Candidate Profile
      +-------------------+
                |
                v
      +-------------------+
      | Application       |
      | Strategist        |<--- Candidate Profile
      +-------------------+
                |
                v
      +-------------------+
      | Python Validation |
      | Decision Rules    |
      +-------------------+
                |
                v
       JSON Evaluation File
                |
                v
         SQLite Database
                |
                v
         SQL Ranked Queue
```

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

The database contains three tables.

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

The job ID connects records across the tables.

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

- No automated job discovery.
- No automatic application submission.
- No production deployment.
- No formal benchmark proving review accuracy.
- Scores can vary across executions.
- Hard blocker verification is incomplete.
- The application status is initially set
  to Not Applied, regardless of real history.
- The latest JSON file is overwritten.
- Job deduplication uses exact matching.
- AI usage requires API credits.
- Manual review remains necessary.

## 9. Future Improvements

Potential improvements include:

- Structured qualification confidence levels
- Better hard-blocker verification
- Scoring consistency tests
- Resume generation
- Automated job ingestion
- Application status editing
- Cost and token tracking
- Optional Streamlit dashboard

These are future improvements, not existing V1
features.

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
