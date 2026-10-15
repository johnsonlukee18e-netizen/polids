#!/bin/sh
# Aktualizacja na VPS: pobranie kodu, build obrazu, restart kontenera.
#   cd /opt/polids && sh deploy/update.sh
set -eu
cd "$(dirname "$0")/.."

git pull --ff-only
docker compose -f docker-compose.yml -f docker-compose.nginx.yml build --pull
docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d
docker image prune -f >/dev/null

# na VPS start po buildzie trwa nawet pół minuty: czekamy do 3 min
for _ in $(seq 1 90); do
    if curl -fsS http://127.0.0.1:1337/healthz; then echo; exit 0; fi
    sleep 2
done
echo "healthz nie odpowiada od 3 min - stan i log kontenera: sh deploy/diagnose.sh" >&2
exit 1
