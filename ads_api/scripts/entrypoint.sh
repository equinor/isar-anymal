#!/bin/bash

if [ -z "$CREDENTIALS_CLI_PRIVATE_KEY" ]; then
    echo "CREDENTIALS_CLI_TOKEN is not set"
    exit 1
fi
if [ -z "$CREDENTIALS_CLI_CRT" ]; then
    echo "CREDENTIALS_CLI_CRT is not set"
    exit 1
fi

start_token='-----BEGIN PRIVATE KEY-----'
end_token='-----END PRIVATE KEY-----'
echo ${start_token} > /home/ads-api/credentials/ads-cli.pem
echo ${CREDENTIALS_CLI_PRIVATE_KEY} | tr -d "'" >> /home/ads-api/credentials/ads-cli.pem
echo ${end_token} >> /home/ads-api/credentials/ads-cli.pem


start_certificate='-----BEGIN CERTIFICATE-----'
end_certificate='-----END CERTIFICATE-----'

echo ${start_certificate} > /home/ads-api/credentials/ads-cli.crt
echo ${CREDENTIALS_CLI_CRT} | tr -d "'" >> /home/ads-api/credentials/ads-cli.crt
echo ${end_certificate} >> /home/ads-api/credentials/ads-cli.crt

source /opt/ros/noetic/setup.bash

# --- Startup: serve FastAPI via uvicorn ---
: "${HOST:=0.0.0.0}"
: "${PORT:=8081}"
: "${LOG_LEVEL:=info}"
: "${WORKERS:=1}"

: "${APP_MODULE:=api:api}"

cd "${APP_HOME}"

echo "Starting FastAPI service..."
echo "  APP_HOME=${APP_HOME}"
echo "  APP_MODULE=${APP_MODULE}"
echo "  HOST=${HOST}"
echo "  PORT=${PORT}"
echo "  WORKERS=${WORKERS}"
echo "  LOG_LEVEL=${LOG_LEVEL}"

exec uvicorn "${APP_MODULE}" \
  --host "${HOST}" \
  --port "${PORT}" \
  --log-level "${LOG_LEVEL}" \
  --workers "${WORKERS}"
