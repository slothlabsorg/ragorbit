#!/usr/bin/env bash
# Despliega el artefacto generado en Google Cloud Run.
# Requisitos: gcloud auth login, proyecto con billing, APIs habilitadas.
#
# Uso (desde la raíz del artefacto exportado):
#   export GCP_PROJECT_ID=mi-proyecto
#   export GCP_REGION=us-central1
#   bash gcp/deploy.sh
set -euo pipefail

PROJECT="${GCP_PROJECT_ID:?export GCP_PROJECT_ID}"
REGION="${GCP_REGION:-us-central1}"
REPO="${ARTIFACT_REPO:-ragorbit}"
APP_SERVICE="${APP_SERVICE_NAME:-{{FLOW_ID}}-chat}"
SVC_SERVICE="${MOCK_SERVICE_NAME:-{{FLOW_ID}}-services}"

echo "▶ Proyecto: $PROJECT · región: $REGION"

gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com --project="$PROJECT"

if ! gcloud artifacts repositories describe "$REPO" --location="$REGION" --project="$PROJECT" &>/dev/null; then
  gcloud artifacts repositories create "$REPO" \
    --repository-format=docker --location="$REGION" --project="$PROJECT"
fi

IMAGE_BASE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}"

echo "▶ Build mock-services…"
gcloud builds submit --project="$PROJECT" --tag "${IMAGE_BASE}/${SVC_SERVICE}:latest" \
  --dockerfile=Dockerfile.services .

echo "▶ Deploy mock-services → Cloud Run"
gcloud run deploy "$SVC_SERVICE" \
  --project="$PROJECT" --region="$REGION" \
  --image "${IMAGE_BASE}/${SVC_SERVICE}:latest" \
  --port 8080 --allow-unauthenticated \
  --set-env-vars "RAGORBIT_HOST=0.0.0.0,PORT=8080"

SVC_URL=$(gcloud run services describe "$SVC_SERVICE" --project="$PROJECT" --region="$REGION" \
  --format='value(status.url)')

echo "▶ Build chat app…"
gcloud builds submit --project="$PROJECT" --tag "${IMAGE_BASE}/${APP_SERVICE}:latest" .

echo "▶ Deploy chat app → Cloud Run"
gcloud run deploy "$APP_SERVICE" \
  --project="$PROJECT" --region="$REGION" \
  --image "${IMAGE_BASE}/${APP_SERVICE}:latest" \
  --port 8000 --allow-unauthenticated \
  --set-env-vars "MOCK=false,INTEGRATION=true,FLOW_ID={{FLOW_ID}},SERVICES_BASE=${SVC_URL},PORT=8000"

APP_URL=$(gcloud run services describe "$APP_SERVICE" --project="$PROJECT" --region="$REGION" \
  --format='value(status.url)')

echo ""
echo "✅ Chat desplegado: ${APP_URL}"
echo "   Servicios mock: ${SVC_URL}"
echo "   Abre ${APP_URL} en el navegador para chatear."
