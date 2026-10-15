#!/bin/sh
# Stan kontenera aplikacji, gdy nie odpowiada /healthz (workflow Deploy (VPS) uruchamia to sam po nieudanym update.sh).
#   cd /opt/polids && sh deploy/diagnose.sh
# Wynik trafia do logu GitHub Actions, który w publicznym repo widzi każdy: z logu aplikacji wypadają linie zapytań
# HTTP (adresy IP użytkowników) i logowań (CID), a wartości z .env w błędach walidacji ustawień są zamazane.
cd "$(dirname "$0")/.."
DC="docker compose -f docker-compose.yml -f docker-compose.nginx.yml"

echo "== docker compose ps"
$DC ps -a

echo "== stan kontenera app"
cid=$($DC ps -aq app 2>/dev/null)
if [ -n "$cid" ]; then
    docker inspect -f 'status={{.State.Status}} exit={{.State.ExitCode}} oom_killed={{.State.OOMKilled}} restarts={{.RestartCount}} started={{.State.StartedAt}} finished={{.State.FinishedAt}} error={{.State.Error}}{{if .State.Health}} health={{.State.Health.Status}}{{end}}' "$cid"
else
    echo "brak kontenera app"
fi

echo "== log aplikacji (ostatnie linie, bez zapytań HTTP i CID)"
$DC logs --no-color --tail 400 app 2>&1 \
    | grep -v -e 'HTTP/[0-9.]*" ' -e 'CID ' \
    | sed -E 's/(input_value=)[^,}]*/\1***/g' \
    | tail -n 80

echo "== pamięć, procesor, dysk"
free -m
echo "cpu: $(nproc), load: $(cut -d' ' -f1-3 /proc/loadavg)"
df -h / /var/lib/docker 2>/dev/null

echo "== jądro: brak pamięci (jeśli dostępne)"
{ journalctl -k -q --since "-30 min" 2>/dev/null || dmesg 2>/dev/null; } \
    | grep -i -E 'out of memory|oom-kill|killed process' | tail -n 10
exit 0
