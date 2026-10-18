#!/bin/sh
set -eu

: "${LLM_MODEL:?set WHADIO_NOTES__LLM__MODEL in .env}"

exec ollama pull "$LLM_MODEL"
