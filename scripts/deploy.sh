#!/usr/bin/env bash
# Build, push, and plan. Every cloud resource comes from OpenTofu; this script
# only builds the image and hands the tag to `tofu plan`.
#
#   ./scripts/deploy.sh PROJECT_ID [REGION]
#
# It stops at the plan. Read the diff, then run `tofu apply` yourself — nothing
# here applies without a human looking at it first.

set -euo pipefail

PROJECT="${1:?usage: deploy.sh PROJECT_ID [REGION]}"
REGION="${2:-us-central1}"
# Where Vertex serves the model, which is not where the service runs. Gemini
# 3.x answers from `global` and 404s from a named region.
VERTEX_LOCATION="${VERTEX_LOCATION:-global}"
SERVICE="vendor-discovery"
TAG="$(git rev-parse --short HEAD 2>/dev/null || date +%s)"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${SERVICE}/api:${TAG}"

cd "$(dirname "$0")/.."

echo "==> Which Gemini models can ${PROJECT} reach from ${VERTEX_LOCATION}?"
(cd backend && .venv/bin/python scripts/check_models.py --project "${PROJECT}" --location "${VERTEX_LOCATION}") || true

echo
echo "==> Tests must pass before anything is built"
(cd backend && .venv/bin/python -m pytest -q)

echo
echo "==> Building ${IMAGE}"
gcloud builds submit backend --project "${PROJECT}" --tag "${IMAGE}" --quiet

echo
echo "==> Planning"
cd terraform
if [ ! -f backend.hcl ]; then
  echo "backend.hcl is missing. Copy backend.hcl.example and set your state bucket." >&2
  exit 1
fi
tofu init -backend-config=backend.hcl -upgrade
tofu fmt -check
tofu validate
tofu plan -var "project_id=${PROJECT}" -var "region=${REGION}" \
  -var "vertex_location=${VERTEX_LOCATION}" -var "image=${IMAGE}"

cat <<EOF

Plan written above. Nothing has been applied.

  cd terraform
  tofu apply -var project_id=${PROJECT} -var region=${REGION} \
    -var vertex_location=${VERTEX_LOCATION} -var image=${IMAGE}

Then wire the service's own URL so it can build webhook callbacks:

  tofu output next_steps
EOF
