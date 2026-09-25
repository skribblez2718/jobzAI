#!/usr/bin/env bash

# Safe PostgreSQL setup helper for jobzAI.
#
# This script never installs operating-system packages, invokes sudo, drops a
# PostgreSQL cluster, or deletes a Docker volume. It supports two explicit
# setup paths:
#   existing  Apply bootstrap_db.sql to an existing/local/cloud database.
#   docker    Create or reuse a local PostgreSQL container and apply the schema.

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SCHEMA_FILE="${SCRIPT_DIR}/bootstrap_db.sql"
PROGRAM_DISPLAY="$0"
DRY_RUN=0
ASSUME_YES=0

usage() {
  cat <<EOF
Usage:
  ${PROGRAM_DISPLAY} existing [--dry-run] [--yes]
  ${PROGRAM_DISPLAY} docker   [--dry-run] [--yes]
  ${PROGRAM_DISPLAY} help

Modes:
  existing  Apply the jobzAI schema to an existing PostgreSQL 12+ database.
            Requires psql plus PGDATABASE and a schema-owner/migration PGUSER.
            PGHOST is optional for local sockets; PGPORT defaults to 5432.
            The role must have USAGE, CREATE on schema public and own any
            existing target table. Authentication may use .pgpass, PGPASSFILE,
            PGPASSWORD, or another libpq-supported mechanism.

  docker    Create or reuse an isolated local PostgreSQL container, wait for
            readiness, and apply the jobzAI schema. Requires Docker. The
            container binds only to 127.0.0.1 by default.

Options:
  --dry-run  Validate configuration and show the planned action without
             connecting, creating resources, or applying the schema.
  --yes      Skip the interactive confirmation. Required for non-interactive
             execution.
  -h, --help Show this help.

Existing-database variables:
  PGHOST       Database host; omit to use libpq's default local socket
  PGPORT       PostgreSQL port (default: 5432)
  PGDATABASE   Required database name
  PGUSER       Required schema-owner or migration role
  PGSSLMODE    Optional libpq SSL mode, commonly required for cloud databases

Docker variables:
  PGDATABASE                 Database name (default: jobzai)
  PGUSER                     Combined owner/runtime role for local development (default: jobzai)
  JOBZAI_DB_PASSWORD          Password for a new container; prompted when unset
  JOBZAI_POSTGRES_VERSION     Image tag suffix (default: 16-alpine; minimum: 12)
  JOBZAI_POSTGRES_CONTAINER   Container name (default: jobzai-postgres)
  JOBZAI_POSTGRES_VOLUME      Persistent volume (default: jobzai-postgres-data)
  JOBZAI_POSTGRES_PORT        Host port bound to 127.0.0.1 (default: 5432)
  JOBZAI_POSTGRES_RESTART     Restart policy (default: unless-stopped)
  JOBZAI_DOCKER_NETWORK       Optional existing Docker network for containerized n8n

Examples:
  PGHOST=db.example.com PGDATABASE=jobzai PGUSER=jobzai_owner \\
    PGSSLMODE=require ${PROGRAM_DISPLAY} existing

  ${PROGRAM_DISPLAY} docker

  # Inject JOBZAI_DB_PASSWORD through the automation runner's secret store.
  ${PROGRAM_DISPLAY} docker --yes
EOF
}

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

reject_control_characters() {
  local label="$1"
  local value="$2"
  [[ -n "$value" ]] || fail "${label} must not be empty"
  [[ ${#value} -le 255 ]] || fail "${label} is too long"
  [[ "$value" != *$'\n'* && "$value" != *$'\r'* && "$value" != *$'\t'* ]] || \
    fail "${label} must not contain control characters"
}

validate_identifier() {
  local label="$1"
  local value="$2"
  [[ "$value" =~ ^[A-Za-z_][A-Za-z0-9_-]{0,62}$ ]] || \
    fail "${label} must start with a letter or underscore and contain at most 63 letters, digits, underscores, or hyphens"
}

validate_resource_name() {
  local label="$1"
  local value="$2"
  [[ "$value" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]] || \
    fail "${label} contains unsupported characters or is longer than 128 characters"
}

validate_port() {
  local value="$1"
  [[ "$value" =~ ^[0-9]{1,5}$ ]] || fail "port must be an integer from 1 to 65535"
  (( value >= 1 && value <= 65535 )) || fail "port must be an integer from 1 to 65535"
}

confirm() {
  local prompt="$1"
  if (( ASSUME_YES )); then
    return 0
  fi
  [[ -t 0 ]] || fail "non-interactive execution requires --yes"
  local reply
  read -r -p "${prompt} [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]] || fail "cancelled"
}

apply_to_existing() {
  require_command psql

  local host="${PGHOST:-}"
  local port="${PGPORT:-5432}"
  local database="${PGDATABASE:-}"
  local user="${PGUSER:-}"

  if [[ -n "$host" ]]; then
    reject_control_characters PGHOST "$host"
  fi
  validate_port "$port"
  reject_control_characters PGDATABASE "$database"
  reject_control_characters PGUSER "$user"

  printf 'Existing PostgreSQL target:\n'
  printf '  host:     %s\n' "${host:-libpq default local socket}"
  printf '  port:     %s\n' "$port"
  printf '  database: %s\n' "$database"
  printf '  role:     %s\n' "$user"
  printf '  schema:   %s\n' "$SCHEMA_FILE"

  if (( DRY_RUN )); then
    printf 'Dry run complete; no connection was made and no schema was applied.\n'
    return 0
  fi

  confirm "Apply the non-destructive jobzAI schema to this database?"

  local -a psql_args=(
    --port "$port"
    --username "$user"
    --dbname "$database"
    --set ON_ERROR_STOP=1
  )
  if [[ -n "$host" ]]; then
    psql_args=(--host "$host" "${psql_args[@]}")
  fi

  local version_check
  version_check="DO \$jobzai\$ BEGIN IF current_setting('server_version_num')::integer < 120000 THEN RAISE EXCEPTION 'jobzAI requires PostgreSQL 12 or newer'; END IF; END \$jobzai\$;"

  psql "${psql_args[@]}" \
    --command "$version_check" \
    --file "$SCHEMA_FILE"

  printf 'jobzAI schema applied successfully.\n'
}

prompt_for_password() {
  local password="${JOBZAI_DB_PASSWORD:-}"
  if [[ -z "$password" ]]; then
    [[ -t 0 ]] || fail "set JOBZAI_DB_PASSWORD for non-interactive Docker setup"

    local first second
    read -r -s -p 'New PostgreSQL password: ' first
    printf '\n' >&2
    read -r -s -p 'Confirm PostgreSQL password: ' second
    printf '\n' >&2
    [[ "$first" == "$second" ]] || fail "passwords do not match"
    password="$first"
  fi

  [[ ${#password} -ge 12 ]] || fail "password must contain at least 12 characters"
  [[ "$password" != *$'\n'* && "$password" != *$'\r'* && "$password" != *$'\t'* ]] || \
    fail "password must not contain control characters"
  printf '%s' "$password"
}

wait_for_postgres() {
  local container="$1"
  local user="$2"
  local database="$3"
  local attempt

  for attempt in $(seq 1 60); do
    # The official image briefly starts a temporary server before creating the
    # requested database. A successful query prevents that intermediate state
    # from being mistaken for full readiness.
    if docker exec "$container" \
      psql --username "$user" --dbname "$database" --tuples-only --command 'SELECT 1;' \
      >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done

  docker logs --tail 30 "$container" >&2 || true
  fail "PostgreSQL did not become ready within 60 seconds"
}

docker_env_value() {
  local container="$1"
  local key="$2"
  docker container inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$container" |
    awk -F= -v key="$key" '$1 == key { print substr($0, length(key) + 2); exit }'
}

require_match() {
  local label="$1"
  local actual="$2"
  local expected="$3"
  [[ "$actual" == "$expected" ]] || \
    fail "existing container ${label} mismatch: expected '${expected}', found '${actual}'. Use the original settings or choose a new container and volume name"
}

apply_with_docker() {
  require_command docker
  docker info >/dev/null 2>&1 || fail "Docker is installed but its daemon is unavailable"

  local database="${PGDATABASE:-jobzai}"
  local user="${PGUSER:-jobzai}"
  local version="${JOBZAI_POSTGRES_VERSION:-16-alpine}"
  local container="${JOBZAI_POSTGRES_CONTAINER:-jobzai-postgres}"
  local volume="${JOBZAI_POSTGRES_VOLUME:-jobzai-postgres-data}"
  local host_port="${JOBZAI_POSTGRES_PORT:-5432}"
  local restart_policy="${JOBZAI_POSTGRES_RESTART:-unless-stopped}"
  local network="${JOBZAI_DOCKER_NETWORK:-}"

  validate_identifier PGDATABASE "$database"
  validate_identifier PGUSER "$user"
  [[ "$version" =~ ^[0-9]+([.][0-9]+)?(-alpine)?$ ]] || \
    fail "JOBZAI_POSTGRES_VERSION must look like 16, 16.4, or 16-alpine"
  local major_version="${version%%.*}"
  major_version="${major_version%%-*}"
  (( major_version >= 12 )) || fail "PostgreSQL 12 or newer is required"
  validate_resource_name JOBZAI_POSTGRES_CONTAINER "$container"
  validate_resource_name JOBZAI_POSTGRES_VOLUME "$volume"
  validate_port "$host_port"
  case "$restart_policy" in
    no|on-failure|always|unless-stopped) ;;
    *) fail "JOBZAI_POSTGRES_RESTART must be no, on-failure, always, or unless-stopped" ;;
  esac
  if [[ -n "$network" ]]; then
    validate_resource_name JOBZAI_DOCKER_NETWORK "$network"
    docker network inspect "$network" >/dev/null 2>&1 || \
      fail "Docker network does not exist: $network"
  fi

  local container_exists=0
  local volume_exists=0
  docker container inspect "$container" >/dev/null 2>&1 && container_exists=1
  docker volume inspect "$volume" >/dev/null 2>&1 && volume_exists=1

  if (( container_exists )); then
    local managed_label
    managed_label="$(docker container inspect --format '{{ index .Config.Labels "io.jobzai.postgres" }}' "$container")"
    [[ "$managed_label" == "true" ]] || \
      fail "container already exists but is not managed by this helper: $container"
    (( volume_exists )) || fail "managed container references a missing requested volume: $volume"

    local volume_label
    volume_label="$(docker volume inspect --format '{{ index .Labels "io.jobzai.postgres" }}' "$volume")"
    [[ "$volume_label" == "true" ]] || \
      fail "volume already exists but is not managed by this helper: $volume"

    local actual_image actual_user actual_database actual_volume actual_bindings actual_restart actual_restart_count expected_network
    actual_image="$(docker container inspect --format '{{.Config.Image}}' "$container")"
    actual_user="$(docker_env_value "$container" POSTGRES_USER)"
    actual_database="$(docker_env_value "$container" POSTGRES_DB)"
    actual_volume="$(docker container inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{println .Name}}{{end}}{{end}}' "$container")"
    actual_bindings="$(docker container inspect --format '{{range $port, $bindings := .HostConfig.PortBindings}}{{range $bindings}}{{println $port .HostIp .HostPort}}{{end}}{{end}}' "$container")"
    actual_restart="$(docker container inspect --format '{{.HostConfig.RestartPolicy.Name}}' "$container")"
    actual_restart_count="$(docker container inspect --format '{{.HostConfig.RestartPolicy.MaximumRetryCount}}' "$container")"
    expected_network="${network:-bridge}"

    require_match image "$actual_image" "postgres:${version}"
    require_match database "$actual_database" "$database"
    require_match role "$actual_user" "$user"
    require_match volume "${actual_volume%$'\n'}" "$volume"
    require_match 'published ports' "$actual_bindings" "5432/tcp 127.0.0.1 ${host_port}"
    require_match 'restart policy' "$actual_restart" "$restart_policy"
    require_match 'restart retry limit' "$actual_restart_count" "0"
    local actual_networks
    actual_networks="$(docker container inspect --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' "$container")"
    require_match 'Docker network' "$actual_networks" "$expected_network"
  elif (( volume_exists )); then
    fail "volume exists without its managed container: $volume. Recover it manually with the original database role/password, or choose new container and volume names"
  fi

  printf 'Local Docker PostgreSQL plan:\n'
  printf '  image:     postgres:%s\n' "$version"
  printf '  container: %s%s\n' "$container" "$([[ $container_exists -eq 1 ]] && printf ' (reuse)' || printf ' (create)')"
  printf '  volume:    %s\n' "$volume"
  printf '  host bind: 127.0.0.1:%s\n' "$host_port"
  printf '  database:  %s\n' "$database"
  printf '  role:      %s\n' "$user"
  printf '  restart:   %s\n' "$restart_policy"
  printf '  network:   %s\n' "${network:-bridge}"
  printf '  schema:    %s\n' "$SCHEMA_FILE"

  if (( DRY_RUN )); then
    printf 'Dry run complete; no container, volume, or database was changed.\n'
    return 0
  fi

  confirm "Continue with this Docker setup?"

  if (( ! container_exists )); then
    local password
    password="$(prompt_for_password)"

    docker volume create \
      --label io.jobzai.postgres=true \
      --label "io.jobzai.database=${database}" \
      --label "io.jobzai.role=${user}" \
      "$volume" >/dev/null

    local -a docker_args=(
      run --detach
      --name "$container"
      --label io.jobzai.postgres=true
      --label "io.jobzai.database=${database}"
      --label "io.jobzai.role=${user}"
      --restart "$restart_policy"
      --publish "127.0.0.1:${host_port}:5432"
      --volume "${volume}:/var/lib/postgresql/data"
      --env POSTGRES_USER
      --env POSTGRES_PASSWORD
      --env POSTGRES_DB
    )
    if [[ -n "$network" ]]; then
      docker_args+=(--network "$network")
    fi
    docker_args+=("postgres:${version}")

    POSTGRES_USER="$user" \
    POSTGRES_PASSWORD="$password" \
    POSTGRES_DB="$database" \
      docker "${docker_args[@]}" >/dev/null

    unset password
  elif [[ "$(docker container inspect --format '{{.State.Running}}' "$container")" != "true" ]]; then
    docker start "$container" >/dev/null
  fi

  wait_for_postgres "$container" "$user" "$database"

  local server_version_num
  server_version_num="$(docker exec "$container" \
    psql --username "$user" --dbname "$database" --tuples-only --no-align \
      --command 'SHOW server_version_num;')"
  [[ "$server_version_num" =~ ^[0-9]+$ ]] || fail "unable to determine PostgreSQL server version"
  (( server_version_num >= 120000 )) || fail "PostgreSQL 12 or newer is required"

  docker exec --interactive "$container" \
    psql --username "$user" --dbname "$database" --set ON_ERROR_STOP=1 \
    < "$SCHEMA_FILE"

  printf '\nLocal PostgreSQL is ready.\n'
  printf '  Host from this machine: 127.0.0.1\n'
  printf '  Port:                   %s\n' "$host_port"
  printf '  Database:               %s\n' "$database"
  printf '  User:                   %s\n' "$user"
  printf '  Restart policy:         %s\n' "$restart_policy"
  if [[ -n "$network" ]]; then
    printf '  Host from Docker network %s: %s\n' "$network" "$container"
  fi
  printf 'The password was not printed. Keep it in an approved secret store.\n'
  printf 'This helper never removes the container or its persistent volume.\n'
}

main() {
  [[ -f "$SCHEMA_FILE" ]] || fail "schema file not found: $SCHEMA_FILE"

  local mode="${1:-help}"
  if [[ $# -gt 0 ]]; then
    shift
  fi

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run)
        DRY_RUN=1
        ;;
      --yes)
        ASSUME_YES=1
        ;;
      -h|--help)
        usage
        return 0
        ;;
      *)
        fail "unknown option: $1"
        ;;
    esac
    shift
  done

  case "$mode" in
    existing)
      apply_to_existing
      ;;
    docker)
      apply_with_docker
      ;;
    help|-h|--help)
      usage
      ;;
    *)
      usage >&2
      fail "unknown mode: $mode"
      ;;
  esac
}

main "$@"
