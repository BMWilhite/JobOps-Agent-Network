WITH ranked_jobs AS (
    SELECT
        jobs.company,
        jobs.title,
        evaluations.reviewed_score,
        evaluations.recommendation,
        applications.status AS application_status
    FROM jobs
    JOIN evaluations
     ON jobs.id = evaluations.job_id
    JOIN applications
     ON jobs.id = applications.job_id
)

SELECT
    company,
    title,
    reviewed_score,
    recommendation,
    application_status
FROM ranked_jobs
WHERE reviewed_score >= 70
    AND application_status = 'Not Applied'
ORDER BY reviewed_score DESC;