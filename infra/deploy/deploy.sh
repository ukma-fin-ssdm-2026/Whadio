#!/usr/bin/env bash
# Deploys a commit of main on the public instance from the images CI published for it, and rolls
# back to the running commit if the new one does not come up healthy. CI passes the SHA as the
# forced command of the deploy key; an operator passes it as the argument.
set -euo pipefail

main() {
    local sha=${1:-${SSH_ORIGINAL_COMMAND:-}}
    if [[ ! $sha =~ ^[0-9a-f]{40}$ ]]; then
        echo "usage: deploy.sh <full commit SHA of main>" >&2
        return 64
    fi

    cd "$(dirname "$(readlink -f "$0")")/../.."
    exec 9> /run/lock/whadio-deploy.lock
    if ! flock --nonblock 9; then
        echo "Another deploy is running" >&2
        return 75
    fi

    git fetch --quiet origin main
    if ! git merge-base --is-ancestor "$sha" origin/main; then
        echo "$sha is not on main" >&2
        return 65
    fi

    local previous revision dump
    previous=$(git rev-parse HEAD)
    dump=$HOME/backups/$previous.dump
    mkdir -p "$HOME/backups"
    cp .env .env.previous

    echo "Preparing $sha; $previous keeps running"
    if ! switch_to "$sha" || ! docker compose pull --quiet || ! revision=$(database_revision) ||
        ! docker compose exec -T postgres pg_dump --username=postgres --format=custom whadio > "$dump"; then
        echo "Could not prepare $sha; nothing was changed" >&2
        switch_back "$previous"
        return 1
    fi

    echo "Starting $sha"
    if start && healthy; then
        echo "Deployed $sha"
        docker image prune --all --force --filter "until=168h" > /dev/null
        find "$HOME/backups" -name '*.dump' -mtime +7 -delete
        return 0
    fi

    echo "$sha did not come up healthy; rolling back to $previous" >&2
    switch_back "$previous"
    if [[ $(database_revision) != "$revision" ]]; then
        echo "Restoring the database as it was before the migrations" >&2
        docker compose stop web scheduler notes-worker asr-worker
        # --create drops and recreates the database, so tables a new migration added go too.
        docker compose exec -T postgres pg_restore --username=postgres --dbname=postgres --clean \
            --create --exit-on-error < "$dump"
    fi
    if ! start || ! healthy; then
        echo "Rolling back to $previous failed: the instance needs a manual fix" >&2
        return 2
    fi
    echo "Rolled back to $previous" >&2
    return 1
}

# Checks out the commit and writes .env from the configuration secret, pinned to its images.
switch_to() {
    git checkout --quiet --detach "$1" &&
        (umask 077 && { gcloud secrets versions access latest --secret=whadio-env |
            grep -v '^IMAGE_TAG=' && echo "IMAGE_TAG=$1"; } > .env.next) &&
        mv .env.next .env &&
        docker compose config --quiet
}

switch_back() {
    git checkout --quiet --detach "$1"
    rm -f .env.next
    mv .env.previous .env
}

database_revision() {
    docker compose exec -T postgres psql --username=postgres --dbname=whadio --tuples-only \
        --no-align --command='SELECT version_num FROM alembic_version'
}

start() {
    docker compose up --detach --no-build --wait --wait-timeout 900 --remove-orphans
}

# Checks the public name through this host's own nginx: the certificate, the HTTPS port and web.
healthy() {
    local host
    host=$(sed -n 's|^WHADIO_PUBLIC_URL=https://\([^/]*\).*|\1|p' .env)
    curl --fail --silent --show-error --max-time 10 --retry 6 --retry-delay 5 --retry-all-errors \
        --resolve "$host:443:127.0.0.1" --output /dev/null "https://$host/health"
}

main "$@"; exit
