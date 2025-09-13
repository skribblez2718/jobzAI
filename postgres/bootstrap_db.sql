--------------------------------------------------------------------
-- bootstrap.sql  (PostgreSQL ≥ 12)
-- Run as a super-user:   psql -f bootstrap.sql
--------------------------------------------------------------------

-- 1. ----------------------------------------------------------------
-- CREATE LEAST-PRIVILEGE LOGIN ROLES
--------------------------------------------------------------------
CREATE ROLE <YOUR_ROLE>   LOGIN PASSWORD '<YOUR_PASSWORD>';


--------------------------------------------------------------------
-- 2. ----------------------------------------------------------------
-- CREATE THE TWO DATABASES OWNED BY THEIR RESPECTIVE ROLES
--------------------------------------------------------------------
CREATE DATABASE <YOUR_DB>   OWNER <YOUR_ROLE>;

--------------------------------------------------------------------
-- 3. ----------------------------------------------------------------
-- DEFINE `job_applications` TABLE
--------------------------------------------------------------------
\connect <YOUR_DB>

-- Tighten public schema so only superusers can create objects
REVOKE ALL  ON SCHEMA public FROM PUBLIC;
GRANT  USAGE ON SCHEMA public TO PUBLIC;

/* ----- DROP the table if it already exists ----------------------- */
DROP TABLE IF EXISTS public.job_applications CASCADE;

/* ----- Create the new table -------------------------------------- */
CREATE TABLE public.job_applications (
    job_id                      TEXT PRIMARY KEY,
    company_name                TEXT,
    position                    TEXT,
    salary                      TEXT,
    location                    TEXT,
    posted_date                 TEXT,
    preference_matches          TEXT,
    preference_misses           TEXT,
    potential_preference_matches TEXT,
    preferences_rating          DOUBLE PRECISION,
    preference_references       TEXT,
    skill_matches               TEXT,
    skill_misses                TEXT,
    skill_translations          TEXT,
    skill_rating                DOUBLE PRECISION,
    overall_rating              DOUBLE PRECISION,
    years_of_experience         TEXT,
    evaluation                  TEXT,
    resume                      TEXT,
    joburl                      TEXT
);
-- Give role exactly what it needs on this table + its sequence
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE     public.job_applications       TO <YOUR_ROLE>;
GRANT USAGE,  SELECT                ON SEQUENCE  job_applications_id_seq        TO <YOUR_ROLE>;

--------------------------------------------------------------------
-- DONE ✅
--------------------------------------------------------------------
