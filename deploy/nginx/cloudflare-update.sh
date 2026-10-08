#!/bin/sh
# Generuje /etc/nginx/snippets/cloudflare.conf z aktualnych zakresów IP Cloudflare i przeładowuje nginx.
# sudo sh cloudflare-update.sh   (warto dać do crona raz w tygodniu)
set -eu

out=/etc/nginx/snippets/cloudflare.conf
tmp=$(mktemp)

ranges() {
    for v in 4 6; do
        { curl -fsS "https://www.cloudflare.com/ips-v$v"; echo; } | sed '/^$/d'
    done
}

list=$(ranges)
[ -n "$list" ] || { echo "nie udało się pobrać zakresów Cloudflare" >&2; exit 1; }

{
    echo "# generowane przez cloudflare-update.sh, $(date -u +%F)"
    echo "$list" | sed 's/.*/set_real_ip_from &;/'
    echo "real_ip_header CF-Connecting-IP;"
    echo "allow 127.0.0.1;"
    echo "allow ::1;"
    echo "$list" | sed 's/.*/allow &;/'
    echo "deny all;"
} > "$tmp"

mkdir -p "$(dirname "$out")"
install -m 644 "$tmp" "$out"
rm -f "$tmp"
nginx -t && systemctl reload nginx
