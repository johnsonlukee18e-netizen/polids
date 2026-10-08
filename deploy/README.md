# Deploy na VPS

Caddy przyjmuje 80/443 i sam ogarnia certyfikat Let's Encrypt, aplikacja słucha na 1337 tylko lokalnie.
Obraz buduje GitHub Actions (GHCR), po pushu do `main` workflow loguje się po SSH i robi `pull` + `up -d`.

## 1. Serwer

Wystarczy 2 vCPU / 2 GB RAM, Ubuntu 24.04 albo Debian 12.

```bash
curl -fsSL https://get.docker.com | sh
adduser --disabled-password --gecos "" deploy
usermod -aG docker deploy
mkdir -p /opt/polids/deploy && chown -R deploy:deploy /opt/polids
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443 && ufw enable
```

Porty publikowane przez Dockera omijają ufw, dlatego aplikacja jest wystawiona tylko na `127.0.0.1:1337`,
na zewnątrz jest tylko Caddy.

## 2. DNS

Rekord A (i AAAA, jeśli jest IPv6) na adres VPS, np. `polids.example.pl`. Caddy pobierze certyfikat dopiero, jak
domena wskazuje na serwer i 80/443 są otwarte.

## 3. VATSIM Connect

Organizację zakłada się na https://auth.vatsim.net/manage/new (akceptuje VATSIM, najprościej przez PL vACC).
W niej klient OAuth z redirect URI `https://<DOMAIN>/auth/callback`.

Do testów: sandbox https://auth-dev.vatsim.net, konto testowe (10000000-10000010, hasło = CID), klient w
"Manage OAuth organizations" i `POLIDS_VATSIM_AUTH_URL=https://auth-dev.vatsim.net`.

## 4. `/opt/polids/.env`

```bash
DOMAIN=polids.example.pl
ACME_EMAIL=admin@example.pl
POLIDS_IMAGE=ghcr.io/<org>/polids:latest

# openssl rand -hex 32 (zmiana wyloguje wszystkich)
POLIDS_SECRET_KEY=...
POLIDS_VATSIM_CLIENT_ID=...
POLIDS_VATSIM_CLIENT_SECRET=...
# Twój CID - reszcie dajesz dostęp w zakładce ADMIN
POLIDS_AUTH_ADMIN_CIDS=1234567

# klucz CARTO ograniczyć w panelu CARTO do domeny
POLIDS_CARTO_API_KEY=
POLIDS_OPENAIP_API_KEY=
```

`POLIDS_AUTH_MODE=vatsim` i `POLIDS_PUBLIC_URL=https://$DOMAIN` ustawia `docker-compose.prod.yml`.
Plik tylko na serwerze: `chmod 600 /opt/polids/.env`.

## 5. GHCR

Przy prywatnym repo serwer musi się raz zalogować tokenem z `read:packages`:

```bash
docker login ghcr.io -u <login>
```

Przy publicznym obrazie niepotrzebne.

## 6. GitHub Actions

`.github/workflows/ci-cd.yml`: testy na każdy push/PR, obraz `ghcr.io/<owner>/<repo>` (`latest` + `sha-xxxxxxx`)
z `main`, deploy tylko gdy ustawione `DEPLOY_HOST`.

Settings -> Secrets and variables -> Actions:

| | nazwa | wartość |
|---|---|---|
| variable | `DEPLOY_HOST` | IP albo nazwa serwera |
| variable | `DEPLOY_USER` | domyślnie `deploy` |
| variable | `DEPLOY_PATH` | domyślnie `/opt/polids` |
| variable | `DEPLOY_URL` | np. `https://polids.example.pl`, do sprawdzenia `/healthz` po deployu |
| secret | `DEPLOY_SSH_KEY` | klucz prywatny, publiczny w `~deploy/.ssh/authorized_keys` |
| secret | `DEPLOY_KNOWN_HOSTS` | `ssh-keyscan <serwer>` (sprawdzić odcisk) |

Klucz: `ssh-keygen -t ed25519 -f deploy_key -N ""`. Job `deploy` używa environment `production`, można tam włączyć
ręczne zatwierdzanie.

## 7. Pierwsze uruchomienie

Normalnie robi to workflow. Ręcznie (z `docker-compose.yml`, `docker-compose.prod.yml` i `deploy/Caddyfile` w `/opt/polids`):

```bash
cd /opt/polids
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f
```

Bez danych klienta VATSIM albo z za krótkim `POLIDS_SECRET_KEY` aplikacja nie wstanie (powód w logach).

## Utrzymanie

- logi: `docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f app` (albo `caddy`)
- rollback: ponowny run workflow dla starszego commita albo
  `POLIDS_IMAGE=ghcr.io/<org>/polids:sha-<stary> docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`
- nowy AIRAC: pliki w `data/import/` + linki `POLIDS_AIP_*_URL` w `.env`
- backup: `.env` i wolumeny `polids_state` (lista dostępu!), `polids_photos`, `polids_caddy_data`
  (główna baza jest budowana z repo)

## Wariant: własny nginx + Cloudflare, build na serwerze (polids.pl)

Bez Caddy, GHCR i CI - kod z gita, obraz budowany na VPS, TLS kończy Cloudflare, nginx przekazuje na `127.0.0.1:1337`.
Pliki: `docker-compose.nginx.yml`, `deploy/nginx/`, `deploy/update.sh`.

### 0. Łączność VPS

Build potrzebuje github.com (kod), Docker Hub (`python:3.12-slim`) i PyPI. GitHub nie ma IPv6, Docker Hub tylko częściowo:

```bash
curl -4 -sS -o /dev/null -w '%{http_code}\n' https://github.com
curl -6 -sS -o /dev/null -w '%{http_code}\n' https://github.com
```

Jeśli działa tylko `-6`, potrzebny jest NAT64/DNS64 albo WARP (albo kopiowanie kodu na serwer przez scp/rsync).

### 1. Cloudflare

- DNS: `AAAA polids.pl -> <IPv6 VPS>` z proxy (pomarańczowa chmurka), `CNAME www -> polids.pl` też z proxy
- SSL/TLS -> Overview: **Full (strict)**
- SSL/TLS -> Origin Server -> Create Certificate (`polids.pl`, `*.polids.pl`), na VPS:

```bash
sudo mkdir -p /etc/ssl/cloudflare
sudo nano /etc/ssl/cloudflare/polids.pl.pem   # Origin Certificate
sudo nano /etc/ssl/cloudflare/polids.pl.key   # Private Key
sudo chmod 600 /etc/ssl/cloudflare/polids.pl.key
```

### 2. Kod i aplikacja

Repo jest prywatne - klon przez deploy key (GitHub -> repo -> Settings -> Deploy keys, tylko odczyt):

```bash
ssh-keygen -t ed25519 -f ~/.ssh/polids_deploy -N ""
cat ~/.ssh/polids_deploy.pub          # wkleić jako deploy key
printf 'Host github.com\n  IdentityFile ~/.ssh/polids_deploy\n' >> ~/.ssh/config
sudo mkdir -p /opt/polids && sudo chown $USER /opt/polids
git clone git@github.com:johnsonlukee18e-netizen/polids.git /opt/polids
cd /opt/polids
```

`/opt/polids/.env` (`cp .env.example .env` i podmienić):

```bash
DOMAIN=polids.pl
POLIDS_SECRET_KEY=<openssl rand -hex 32>
POLIDS_VATSIM_CLIENT_ID=<z auth.vatsim.net>
POLIDS_VATSIM_CLIENT_SECRET=<z auth.vatsim.net>
POLIDS_AUTH_ADMIN_CIDS=1424541
```

`POLIDS_AUTH_MODE` i `POLIDS_PUBLIC_URL` ustawia `docker-compose.nginx.yml`, więc te linie w `.env` mogą zostać jak są.

```bash
chmod 600 .env
sh deploy/update.sh       # git pull, build, up -d, sprawdzenie /healthz
```

Pierwszy build trwa kilka minut. W kliencie VATSIM Connect redirect URI: `https://polids.pl/auth/callback`.

### 3. nginx

```bash
sudo cp deploy/nginx/polids.pl.conf /etc/nginx/sites-available/polids.pl
sudo ln -s /etc/nginx/sites-available/polids.pl /etc/nginx/sites-enabled/
sudo sh deploy/nginx/cloudflare-update.sh     # snippets/cloudflare.conf + nginx -t + reload
echo '0 4 * * 1 root sh /opt/polids/deploy/nginx/cloudflare-update.sh' | sudo tee /etc/cron.d/cloudflare-ips
```

Snippet wpuszcza tylko adresy Cloudflare, wejście bezpośrednio na IP serwera dostaje 403.
Test z zewnątrz: `curl -s https://polids.pl/healthz`.

### 4. Aktualizacja

```bash
cd /opt/polids && sh deploy/update.sh
```

Lista dostępu (wolumen `polids_state`) i zdjęcia zostają między buildami. Rollback: `git checkout <commit>` i
`docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d --build`.
