#!/bin/sh
# Gives each worker a broker user of its own. RabbitMQ stamps a message with the user that
# published it, so the web accepts transcription results only from the ASR worker and notes only
# from the notes worker. Each user may use only its own queues. Safe to run again.
set -eu

: "${RABBITMQ_ASR_PASSWORD:?set RABBITMQ_ASR_PASSWORD in .env}"
: "${RABBITMQ_NOTES_PASSWORD:?set RABBITMQ_NOTES_PASSWORD in .env}"

admin() {
    rabbitmqadmin --non-interactive "$@"
}

# $1 user, $2 password, $3 the queue it takes jobs from
declare_worker() {
    admin declare user --name "$1" --password "$2" --tags ""
    # Declaring a queue that dead-letters needs read on it and write on the default exchange.
    admin --vhost whadio declare permissions --username "$1" \
        --configure "^($3|processing\\.results|processing\\.dead-letters)\$" \
        --read "^($3|processing\\.results)\$" \
        --write "^(amq\\.default|processing\\.results)\$"
}

declare_worker whadio-asr "$RABBITMQ_ASR_PASSWORD" 'transcription\.requests'
declare_worker whadio-notes "$RABBITMQ_NOTES_PASSWORD" 'notes\.requests'
