--------------------------------------------------------------------
-- jobzAI schema bootstrap (PostgreSQL 12+)
--
-- Fresh install: before running this file, have the owner of schema public (or
-- a database administrator) revoke CREATE on public from PUBLIC and grant
-- USAGE, CREATE on public to the schema-owner/migration role. Run this file as
-- that role. Configure n8n with a separate runtime role holding only the
-- documented CONNECT, USAGE, SELECT, INSERT, and UPDATE grants.
-- Existing install: run it as the current owner of public.job_applications
-- (or a database administrator). A role with only CRUD grants cannot alter
-- the table. This script does not create roles or databases, store passwords,
-- or drop existing data.
--------------------------------------------------------------------

\set ON_ERROR_STOP on

BEGIN;

DO $jobzai$
BEGIN
    IF current_setting('server_version_num')::INTEGER < 120000 THEN
        RAISE EXCEPTION 'jobzAI requires PostgreSQL 12 or newer';
    END IF;
END
$jobzai$;

CREATE TABLE IF NOT EXISTS public.job_applications (
    job_id                       TEXT PRIMARY KEY,
    company_name                 TEXT,
    position                     TEXT,
    salary                       TEXT,
    location                     TEXT,
    posted_date                  TEXT,
    preference_matches           TEXT,
    preference_misses            TEXT,
    potential_preference_matches TEXT,
    preferences_rating           DOUBLE PRECISION,
    preference_references        TEXT,
    skill_matches                TEXT,
    skill_misses                 TEXT,
    skill_translations           TEXT,
    skill_rating                 DOUBLE PRECISION,
    overall_rating               DOUBLE PRECISION,
    years_of_experience          TEXT,
    evaluation                   TEXT,
    resume                       TEXT,
    joburl                       TEXT,
    dim_employee_satisfaction    DOUBLE PRECISION,
    dim_salary_competitiveness   DOUBLE PRECISION,
    dim_remote_work_flexibility  DOUBLE PRECISION,
    dim_skills_alignment         DOUBLE PRECISION,
    dim_cultural_fit             DOUBLE PRECISION
);

-- Preserve installations created from an older jobzAI schema while adding
-- the current scoring dimensions. Existing columns and rows are untouched.
ALTER TABLE public.job_applications
    ADD COLUMN IF NOT EXISTS dim_employee_satisfaction    DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS dim_salary_competitiveness   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS dim_remote_work_flexibility  DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS dim_skills_alignment         DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS dim_cultural_fit             DOUBLE PRECISION;

COMMENT ON COLUMN public.job_applications.resume IS
    'Reserved for future use, such as storing a tailored resume per application.';

COMMIT;
