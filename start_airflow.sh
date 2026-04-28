#!/usr/bin/env bash
# start_airflow.sh — Start the JBM Airflow ETL stack
set -e

echo "Starting JBM Airflow stack..."

# On Linux/Mac, set the Airflow UID to avoid permission issues with mounted volumes
if [[ "$OSTYPE" == "linux-gnu"* || "$OSTYPE" == "darwin"* ]]; then
    export AIRFLOW_UID=$(id -u)
    echo "AIRFLOW_UID=$AIRFLOW_UID" >> .env
fi

# Create required directories
mkdir -p airflow/dags airflow/logs airflow/plugins data/staging

# Start all services (airflow-init runs first, then webserver/scheduler/worker)
docker-compose -f docker-compose.airflow.yml up -d

echo ""
echo "Airflow is starting up. Wait ~60 seconds for all services to be healthy."
echo ""
echo "  Web UI:   http://localhost:8080"
echo "  Login:    airflow / airflow"
echo ""
echo "To trigger the ETL pipeline:"
echo "  docker-compose -f docker-compose.airflow.yml exec airflow-webserver \\"
echo "    airflow dags trigger jbm_etl_pipeline"
echo ""
echo "To watch logs:"
echo "  docker-compose -f docker-compose.airflow.yml logs -f airflow-scheduler"
