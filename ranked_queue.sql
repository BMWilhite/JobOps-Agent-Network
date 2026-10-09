SELECT
    jobs.company,
    jobs.title,
    evaluations.reviewed_score,
    evaluations.recommendation,
    jobs.salary_min,
    jobs.salary_max,
    jobs.work_arrangement,
    applications.status AS application_status
FROM jobs
JOIN evaluations
    ON jobs.id = evaluations.job_id
JOIN applications
    ON jobs.id = applications.job_id
WHERE applications.status = 'Not Applied'
ORDER BY
    CASE evaluations.recommendation
        WHEN 'Apply' THEN 0
        WHEN 'Hold' THEN 1
        WHEN 'Skip' THEN 2
        ELSE 3
    END,
    evaluations.reviewed_score DESC,
    jobs.id ASC;