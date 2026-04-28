@echo off
REM start_airflow.bat — Start the JBM Airflow ETL stack (Windows)

echo Starting JBM Airflow stack...

REM Create required directories
if not exist airflow\dags mkdir airflow\dags
if not exist airflow\logs mkdir airflow\logs
if not exist airflow\plugins mkdir airflow\plugins
if not exist data\staging mkdir data\staging

REM Start all services
docker-compose -f docker-compose.airflow.yml up -d

echo.
echo Airflow is starting up. Wait ~60 seconds for all services to be healthy.
echo.
echo   Web UI:   http://localhost:8080
echo   Login:    airflow / airflow
echo.
echo To trigger the ETL pipeline:
echo   docker-compose -f docker-compose.airflow.yml exec airflow-webserver airflow dags trigger jbm_etl_pipeline
echo.
echo To watch logs:
echo   docker-compose -f docker-compose.airflow.yml logs -f airflow-scheduler
