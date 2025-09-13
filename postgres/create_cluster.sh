#!/bin/bash

mkdir -p /home/postgres/pgdata
chown -R postgres:postgres /home/postgres

sudo pg_dropcluster --stop 15 main
sudo pg_createcluster 15 home --start -d /home/postgres/pgdata -u postgres -g postgres
