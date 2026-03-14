# JobzAI PostgreSQL Database Schema

## Overview

This directory contains the PostgreSQL bootstrap script for the JobzAI job application tracking system.

## Schema Notes

### Dimension Columns (Added 2026-03-13)

The following columns store quantitative job fit scores (1-5 scale):

| Column | Description |
|--------|-------------|
| `dim_employee_satisfaction` | Employee satisfaction rating from company research |
| `dim_salary_competitiveness` | Salary competitiveness rating |
| `dim_remote_work_flexibility` | Remote work flexibility rating |
| `dim_skills_alignment` | Skills alignment with job requirements |
| `dim_cultural_fit` | Cultural fit rating |

### Reserved Columns

| Column | Status | Purpose |
|--------|--------|---------|
| `resume` | Reserved | Intended for future use - may store tailored resume text per application |

## Setup

```bash
# Run as superuser
psql -f bootstrap_db.sql
```

Replace `<YOUR_ROLE>`, `<YOUR_PASSWORD>`, and `<YOUR_DB>` with your credentials.