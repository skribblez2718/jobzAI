# jobzAI PostgreSQL setup

This directory contains:

- `bootstrap_db.sql` — the non-destructive schema bootstrap used by the current workflows;
- `create_cluster.sh` — an optional setup helper for existing databases and local Docker installations.

Despite its historical filename, `create_cluster.sh` no longer manages Debian PostgreSQL clusters. It never invokes `sudo`, installs operating-system packages, drops a cluster, deletes a table, or removes a Docker container or volume.

## Choose a setup path

### Already-provisioned or cloud PostgreSQL

Use this path when a PostgreSQL 12+ database is already available. Install the `psql` client and create or identify two roles through the provider's normal administration process:

- a schema-owner role used only for setup and migrations;
- a separate least-privilege runtime role used by n8n.

Make the schema-owner role the database owner. Before bootstrapping, have the provider administrator or current owner of schema `public` prepare its privileges; database ownership alone may not grant this authority on PostgreSQL 12–14 or an upgraded database:

```sql
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO jobzai_owner;
GRANT USAGE ON SCHEMA public TO jobzai_runtime;
```

Adapt and quote the example role names as required by your provider. Then apply the schema as the owner:

```bash
PGHOST=HOST \
PGPORT=5432 \
PGDATABASE=DATABASE \
PGUSER=jobzai_owner \
  ./postgres/create_cluster.sh existing
```

The helper displays the target and asks for confirmation before applying `bootstrap_db.sql`. Let `psql` prompt for the schema-owner password or use a libpq-supported credential mechanism such as `.pgpass` or `PGPASSFILE`. `PGPASSWORD` is supported for automation but can expose a secret to the local process environment. Never commit credentials. After setup, grant the permissions in [Runtime privileges](#runtime-privileges-and-postgresql-features) to the runtime role and configure only that role in n8n.

Cloud providers commonly require TLS. Set the provider-required libpq options, such as `PGSSLMODE=require`, before running the helper.

To inspect the plan without connecting:

```bash
PGHOST=HOST PGDATABASE=DATABASE PGUSER=jobzai_owner \
  ./postgres/create_cluster.sh existing --dry-run
```

You can also apply the schema without the helper:

```bash
psql --host HOST --username SCHEMA_OWNER --dbname DATABASE --file postgres/bootstrap_db.sql
```

### Optional local Docker database

Use this path when you want a self-contained local PostgreSQL installation and already have Docker:

```bash
./postgres/create_cluster.sh docker
```

The helper securely prompts for a new password, then creates:

- a PostgreSQL 16 Alpine container named `jobzai-postgres`;
- a persistent Docker volume named `jobzai-postgres-data`;
- a `jobzai` database owned by a `jobzai` login; and
- the `public.job_applications` schema.

For convenience, this local-development mode uses the `jobzai` role as both database owner and n8n runtime. Do not use that elevated role model for a shared, cloud, or production database; use separate schema-owner and runtime roles there.

The database port is published on `127.0.0.1:5432`, not on every network interface. If n8n also runs in Docker, attach PostgreSQL to an existing shared network:

```bash
JOBZAI_DOCKER_NETWORK=YOUR_EXISTING_NETWORK \
  ./postgres/create_cluster.sh docker
```

From a container on that network, use `jobzai-postgres` as the database host. From the local machine, use `127.0.0.1`.

The Docker path is idempotent when rerun with the same settings. Before reuse, it verifies the management labels, image, role, database, volume, loopback port binding, restart policy, and network. It rejects unrelated containers and volumes, configuration drift, and an orphaned volume whose original password cannot be confirmed. Existing rows remain in the named volume.

New containers use Docker's `unless-stopped` restart policy, so PostgreSQL starts again when Docker or the host restarts unless you previously stopped it manually. Set `JOBZAI_POSTGRES_RESTART=no` before the first run to disable automatic restart.

For non-interactive automation, inject `JOBZAI_DB_PASSWORD` through the automation runner's secret store, then provide explicit approval:

```bash
./postgres/create_cluster.sh docker --yes
```

Do not put the password in a tracked shell script or committed environment file. Docker stores the initialization password in the container configuration; use this mode for local development, not as a substitute for a production secret-management design. An ambient `PGPASSWORD` is never reused for Docker initialization.

Common Docker overrides:

| Variable | Default | Purpose |
|---|---|---|
| `PGDATABASE` | `jobzai` | Database name |
| `PGUSER` | `jobzai` | Database role |
| `JOBZAI_POSTGRES_VERSION` | `16-alpine` | Numeric PostgreSQL image tag, optionally ending in `-alpine`; major version must be 12+ |
| `JOBZAI_POSTGRES_CONTAINER` | `jobzai-postgres` | Container name |
| `JOBZAI_POSTGRES_VOLUME` | `jobzai-postgres-data` | Persistent volume name |
| `JOBZAI_POSTGRES_PORT` | `5432` | Host port bound to `127.0.0.1` |
| `JOBZAI_POSTGRES_RESTART` | `unless-stopped` | Docker restart policy: `no`, `on-failure` without a retry-count suffix, `always`, or `unless-stopped` |
| `JOBZAI_DOCKER_NETWORK` | unset | Existing network shared with containerized n8n |

Run `./postgres/create_cluster.sh docker --dry-run` to inspect defaults without creating anything, or `./postgres/create_cluster.sh help` for the complete interface.

The helper deliberately does not include destructive lifecycle commands. With the default names:

```bash
# Stop temporarily; data and container remain, and the helper can restart it.
docker stop jobzai-postgres

# Remove only the container; the database volume remains for manual recovery.
docker rm jobzai-postgres

# PERMANENT DATA LOSS: remove the retained database volume only after backup.
docker volume rm jobzai-postgres-data
```

If you used overrides, substitute the configured container and volume names. Once the container is removed, the helper refuses to guess the credentials stored in an orphaned volume; recover it manually with the original role/password or deliberately choose new names.

### Native local PostgreSQL

Install PostgreSQL with the supported method for your operating system or from the [PostgreSQL project](https://www.postgresql.org/download/). Keeping package installation outside the helper avoids hidden `sudo` operations, distribution-specific assumptions, and the original Qubes OS directory layout.

Connect with an administrative role and create separate schema-owner and runtime roles without putting either password in command history:

```text
psql --username ADMIN_ROLE --dbname postgres
postgres=# CREATE ROLE jobzai_owner LOGIN;
postgres=# \password jobzai_owner
postgres=# CREATE ROLE jobzai_runtime LOGIN;
postgres=# \password jobzai_runtime
postgres=# CREATE DATABASE jobzai OWNER jobzai_owner;
postgres=# \connect jobzai ADMIN_ROLE
jobzai=# REVOKE CREATE ON SCHEMA public FROM PUBLIC;
jobzai=# GRANT USAGE, CREATE ON SCHEMA public TO jobzai_owner;
jobzai=# GRANT USAGE ON SCHEMA public TO jobzai_runtime;
jobzai=# \q
```

Apply the schema through the local socket as the owner:

```bash
PGDATABASE=jobzai PGUSER=jobzai_owner \
  ./postgres/create_cluster.sh existing
```

Omit `PGHOST` to use libpq's default local socket, or set `PGHOST=localhost` for TCP. Then grant the privileges below to `jobzai_runtime` and configure only that role in n8n.

## Existing jobzAI installation

Back up the database, then identify the current table owner:

```sql
SELECT tableowner
FROM pg_tables
WHERE schemaname = 'public' AND tablename = 'job_applications';
```

Run `bootstrap_db.sql` or the helper's `existing` mode as that table owner or a database administrator. Have the owner of schema `public` revoke `CREATE` from `PUBLIC`, grant `USAGE, CREATE` to the schema-owner role, and grant only `USAGE` to the runtime role as shown above. The original jobzAI bootstrap created the table while connected as the PostgreSQL administrator, then granted the n8n role only CRUD privileges. A runtime role installed that way cannot execute the current script's `ALTER TABLE` and `COMMENT ON COLUMN` statements.

Use the owner/administrator only for migration. Never configure n8n with administrative credentials. After migration, continue using or create a dedicated runtime role and grant only the privileges listed below.

The bootstrap:

- creates `public.job_applications` when it does not exist;
- adds the five score-dimension columns used by the current workflows;
- preserves existing rows;
- does not create roles or databases itself;
- does not contain credentials; and
- does not drop tables or data.

It supports the known historical pre-dimension schema. It does not reconcile arbitrary missing base columns, incompatible types, altered constraints, or other locally modified schemas.

## Runtime privileges and PostgreSQL features

The n8n database role requires:

- `CONNECT` on the selected database;
- `USAGE` on schema `public`; and
- `SELECT`, `INSERT`, and `UPDATE` on `public.job_applications`.

For the native-install example names, the schema owner or an administrator can grant:

```sql
GRANT CONNECT ON DATABASE jobzai TO jobzai_runtime;
GRANT USAGE ON SCHEMA public TO jobzai_runtime;
GRANT SELECT, INSERT, UPDATE ON public.job_applications TO jobzai_runtime;
```

Change both identifiers if you chose different database or role names. Do not grant the runtime role ownership or administrative privileges solely to run the workflow. The Docker-only convenience path is the documented exception for isolated local development.

The workflows require no PostgreSQL extension, sequence, or `DELETE` privilege. They use built-in JSONB functions and conflict-based upsert through n8n's PostgreSQL node.

## Schema notes

### Dimension columns

The following columns store quantitative job-fit scores on a 1–5 scale:

| Column | Description |
|---|---|
| `dim_employee_satisfaction` | Employee-satisfaction rating from company research |
| `dim_salary_competitiveness` | Salary-competitiveness rating |
| `dim_remote_work_flexibility` | Remote-work flexibility rating |
| `dim_skills_alignment` | Skills alignment with job requirements |
| `dim_cultural_fit` | Cultural-fit rating |

### Reserved columns

| Column | Status | Purpose |
|---|---|---|
| `resume` | Reserved | May store tailored résumé text per application in a future workflow version |
