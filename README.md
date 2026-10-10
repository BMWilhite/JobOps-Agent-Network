
# JobOps Agent Network

A Python-based, multi-agent AI system for evaluating job
opportunities, challenging candidate-fit assessments, and
managing a structured job-search pipeline using SQLite.

## The Problem

Evaluating job opportunities manually is time-consuming,
inconsistent, and vulnerable to subjective bias.

Job seekers may overestimate their qualifications for
attractive opportunities or underestimate transferable
experience when entering new industries.

JobOps explores how specialized AI agents, structured
data, and independent review can improve that process.

## The Solution

JobOps processes job descriptions through a four-agent
workflow:

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

Job Posting
    |
    v
Extraction Agent
    |
    v
Fit Analyst
    |
    v
Skeptical Reviewer
    |
    v
Application Strategist
    |
    v
Python Validation & Decision Rules
    |
    v
JSON Output
    |
    v
SQLite Database
    |
    v
SQL Queries & Ranked Pipeline

## Technology Stack

- Python 3.14
- OpenAI Agents SDK
- Pydantic for structured AI outputs
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

JobOps uses three relational tables.

### jobs
Stores company information, job descriptions, salary
ranges, location, and work arrangements.

### evaluations
Stores initial and reviewed scores, recommendations,
strengths, gaps, blocker claims, and reviewer findings.

### applications
Tracks application status, dates, and notes.

Tables are connected through job IDs.

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

The demo runs all four agents and writes example_evaluation.json.
It does not modify the private job database. Running the agents
requires OpenAI API credits.

## V2: Automated Job Discovery

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
- OpenAI API access with available credits

Install dependencies:

    python -m pip install openai-agents

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
- Qualification classification is not always reliable.
- Application recommendations require human judgment.
- The system does not independently verify job availability.
- Discovery is limited to configured public job boards.
- Application statuses require manual updates.
- The latest JSON output is overwritten on each run.
- The project is a local prototype, not a production service.

## Future Improvements

- Better qualification and blocker classification
- Expanded job-board coverage and discovery reliability
- Score consistency testing
- Job deduplication improvements
- Application status management
- Resume and cover-letter generation
- Optional Streamlit dashboard

## Project Purpose

JobOps was built to explore practical AI-agent
orchestration, structured outputs, SQL, and the design
of operational decision-support systems.

The emphasis is on creating a useful workflow while
critically evaluating AI-generated recommendations.
