# Public instance on Google Cloud

The public instance runs at <https://app.whadio.com>. It is the single-host production stack from
the README's [Deploying](../../README.md#deploying) section on one Google Cloud VM: CPU
transcription, notes written by Claude through the Anthropic API, and `invite-only`
registration. This guide records how the instance is built, so that it can be rebuilt from an
empty Google Cloud account, and how it is operated.

`whadio.com` itself is reserved for a separate site and is not part of this setup.

## What runs where

| Resource | Name and settings |
|---|---|
| Project | `whadio`, on a free-trial billing account |
| Region and zone | `europe-north1`, `europe-north1-c` |
| VM | `whadio-1`: `e2-standard-2` (2 vCPU, 8 GB), Ubuntu 24.04 LTS, 80 GB `pd-balanced` disk, network tag `whadio-web` |
| Static IP | `whadio-ip`, regional, attached to `whadio-1` |
| Firewall | `whadio-web` allows TCP 80 and 443 to the tag; the default `default-allow-ssh` allows SSH with a key only; the default RDP rule is deleted |
| Service account | `whadio-vm`, attached to the VM; its only permission is reading the `whadio-env` secret |
| Secret | `whadio-env` in Secret Manager: the whole `.env` file of the stack |
| Domain and DNS | `whadio.com`, registered with Cloud Domains with automatic renewal; Cloud DNS zone `whadio-com` with an `A` record for `app.whadio.com` |
| Backups | Snapshot schedule `whadio-daily`: the VM's disk at 03:00 UTC, kept for 7 days |
| TLS | Let's Encrypt certificate for `app.whadio.com` from `certbot` on the VM |
| Stack | The repository at `~/Whadio` on the VM, `COMPOSE_PROFILES=core,gpu,storage`, started with `sudo docker compose` |

## Building it from scratch

You need a Google account with a payment card, the [Google Cloud
CLI](https://cloud.google.com/sdk/docs/install) on your computer, an Anthropic API key, and a
Hugging Face read token whose account has accepted the terms of
`pyannote/speaker-diarization-community-1`.

### 1. Project and billing

In the Google Cloud console:

1. Start the free trial. It gives a credit for 90 days. Do not activate the full account during
   the trial: until then, Google stops the resources when the credit ends instead of charging the
   card.
2. Create the project `whadio` and link it to the trial billing account.
3. Under **Billing → Budgets & alerts**, create a budget for the project with email alerts at 50%,
   75% and 90%.

In the Anthropic Console, give the instance its own workspace with a monthly spend limit, and
create the API key in that workspace.

### 2. The command-line tool

```bash
gcloud init
```

```bash
gcloud config set compute/region europe-north1
```

```bash
gcloud config set compute/zone europe-north1-c
```

```bash
gcloud services enable compute.googleapis.com secretmanager.googleapis.com dns.googleapis.com domains.googleapis.com
```

### 3. Network, service account and VM

```bash
gcloud compute addresses create whadio-ip --region=europe-north1
```

```bash
gcloud compute firewall-rules create whadio-web --network=default --allow=tcp:80,tcp:443 --target-tags=whadio-web
```

```bash
gcloud compute firewall-rules delete default-allow-rdp
```

The default Compute Engine service account can hold the Editor role on the whole project, so the
VM gets its own account without any role:

```bash
gcloud iam service-accounts create whadio-vm --display-name="Whadio VM"
```

```bash
gcloud compute instances create whadio-1 \
  --machine-type=e2-standard-2 \
  --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
  --boot-disk-size=80GB --boot-disk-type=pd-balanced \
  --address=whadio-ip \
  --tags=whadio-web \
  --service-account=whadio-vm@whadio.iam.gserviceaccount.com \
  --scopes=cloud-platform
```

```bash
gcloud compute resource-policies create snapshot-schedule whadio-daily --region=europe-north1 --daily-schedule --start-time=03:00 --max-retention-days=7
```

```bash
gcloud compute disks add-resource-policies whadio-1 --resource-policies=whadio-daily
```

### 4. Domain and DNS

1. In the console, open **Network services → Cloud Domains**, register `whadio.com` and choose
   Cloud DNS for it. The registration creates the zone `whadio-com`, but no address record.
2. Point `app.whadio.com` at the static IP:

   ```bash
   gcloud dns record-sets create app.whadio.com. --zone=whadio-com --type=A --ttl=300 --rrdatas="$(gcloud compute addresses describe whadio-ip --region=europe-north1 --format='value(address)')"
   ```

3. Wait until a public resolver returns the address. Let's Encrypt refuses the certificate
   ("no valid A records") until it does.

   ```bash
   dig +short app.whadio.com A @8.8.8.8
   ```

### 5. Configuration secret

Fill a copy of `.env.production.example` on your computer, as the README's Deploying section
describes, with `WHADIO_PUBLIC_URL=https://app.whadio.com/` and
`WHADIO_REGISTRATION_MODE=invite-only`. Keep the copy outside the repository: git ignores `.env`
only. Then store it and let the VM read it:

```bash
gcloud secrets create whadio-env --data-file=PATH_TO_YOUR_COPY
```

```bash
gcloud secrets add-iam-policy-binding whadio-env --member=serviceAccount:whadio-vm@whadio.iam.gserviceaccount.com --role=roles/secretmanager.secretAccessor
```

Delete the local copy afterwards; the secret is the copy that counts.

### 6. The VM

Connect to it:

```bash
gcloud compute ssh whadio-1
```

On the VM:

1. Install Docker Engine and the Compose plugin from Docker's apt repository, as [Docker's guide
   for Ubuntu](https://docs.docker.com/engine/install/ubuntu/) describes, and install `certbot`
   with `sudo apt install certbot`.
2. Clone the repository and fetch the configuration. The VM's Ubuntu image includes the Google
   Cloud CLI, which authenticates as `whadio-vm`:

   ```bash
   git clone https://github.com/ukma-fin-ssdm-2026/Whadio.git ~/Whadio
   cd ~/Whadio
   gcloud secrets versions access latest --secret=whadio-env > .env
   chmod 600 .env
   ```

### 7. TLS certificate

`certbot --standalone` answers Let's Encrypt on port 80, so nothing else may hold that port. If the
stack is already running, stop its nginx first (`sudo docker compose stop nginx`). Then, in
`~/Whadio`:

```bash
sudo certbot certonly --standalone -d app.whadio.com
mkdir -p certs
sudo install -m 644 /etc/letsencrypt/live/app.whadio.com/fullchain.pem certs/fullchain.pem
sudo install -m 600 -o 101 -g 101 /etc/letsencrypt/live/app.whadio.com/privkey.pem certs/privkey.pem
```

The nginx image runs as uid 101, which must own the private key.

Install the renewal hooks now; [Renewing the certificate](#renewing-the-certificate) explains
them.

### 8. Start the stack and create the first administrator

```bash
cd ~/Whadio
sudo docker compose config --quiet
sudo docker compose up --detach --build --wait
sudo docker compose ps
```

The first build downloads the Python dependencies, and the first transcription downloads the
models. Open <https://app.whadio.com/health>, then create the first account and make it an
administrator:

```bash
sudo docker compose exec web whadio links registration --email ADDRESS
```

```bash
sudo docker compose exec web whadio admin grant --email ADDRESS
```

Hand the registration link to its owner privately, and run the second command after they complete
it.

## Operating the instance

### Updating to the latest `main`

```bash
cd ~/Whadio
git pull
sudo docker compose up --detach --build --wait
```

The one-shot `migrate` service applies new migrations before `web` and `scheduler` start. A new
required variable makes `docker compose config` fail with its name: add it to the configuration
first.

### Changing the configuration

Add a new version of the secret from your computer, then fetch it on the VM and restart the
stack:

```bash
gcloud secrets versions add whadio-env --data-file=PATH_TO_YOUR_COPY
```

```bash
cd ~/Whadio && gcloud secrets versions access latest --secret=whadio-env > .env && sudo docker compose up --detach --wait
```

Secret Manager bills active versions beyond six, so disable old versions
(`gcloud secrets versions disable VERSION --secret=whadio-env`).

### Renewing the certificate

The `certbot.timer` unit tries to renew twice a day once fewer than 30 days remain. A standalone
renewal needs port 80, and nginx reads the certificate from `certs/`, so three hooks stop nginx,
copy the renewed files and start nginx again, about 10 seconds without the site:

```bash
sudo tee /etc/letsencrypt/renewal-hooks/pre/whadio-stop-nginx.sh > /dev/null <<'EOF'
#!/bin/sh
cd /home/hukyl/Whadio && docker compose stop nginx
EOF
sudo tee /etc/letsencrypt/renewal-hooks/deploy/whadio-copy-certificate.sh > /dev/null <<'EOF'
#!/bin/sh
set -eu
case "$RENEWED_LINEAGE" in */app.whadio.com) ;; *) exit 0 ;; esac
cd /home/hukyl/Whadio
install -m 644 "$RENEWED_LINEAGE/fullchain.pem" certs/fullchain.pem
install -m 600 -o 101 -g 101 "$RENEWED_LINEAGE/privkey.pem" certs/privkey.pem
EOF
sudo tee /etc/letsencrypt/renewal-hooks/post/whadio-start-nginx.sh > /dev/null <<'EOF'
#!/bin/sh
cd /home/hukyl/Whadio && docker compose start nginx
EOF
sudo chmod 755 /etc/letsencrypt/renewal-hooks/*/whadio-*.sh
```

The hooks run as root, so they name the checkout by its full path; change `/home/hukyl` if another
user cloned it. The deploy hook copies only the `app.whadio.com` certificate, because the hooks
run for every certificate on the VM. A dry run checks the stop and start hooks, which stops and
starts nginx once; it does not run the deploy hook:

```bash
sudo certbot renew --dry-run
```

### Resizing the VM

The VM must be stopped to change its machine type, for example when transcription is too slow:

```bash
gcloud compute instances stop whadio-1
```

```bash
gcloud compute instances set-machine-type whadio-1 --machine-type=e2-standard-4
```

```bash
gcloud compute instances start whadio-1
```

The static IP stays attached. After the start, run `sudo docker compose up --detach --wait` in
`~/Whadio` so that every service runs again.

### Restoring from a snapshot

List the snapshots, create a disk from one, and create a VM from that disk with the same settings
as in step 3, using `--disk=name=DISK,boot=yes` instead of the image and disk options:

```bash
gcloud compute snapshots list --filter="sourceDisk~whadio-1"
```

```bash
gcloud compute disks create whadio-restored --source-snapshot=SNAPSHOT --type=pd-balanced
```

The static IP can be attached to one VM only: delete or stop the old VM first.

### Costs

**Billing → Reports** in the console shows the spending, and the budget alerts mail the project's
owner. The disk, the static IP and the snapshots are billed even while the VM is stopped. The
domain renews automatically every year. Notes cost Anthropic API usage, up
to the workspace's spend limit.

## Pitfalls met while building it

- Registering a domain with Cloud DNS creates no address record, and certbot fails until a public
  resolver returns one.
- The running stack's nginx holds port 80, so `certbot --standalone` fails until nginx stops.
- Google Cloud blocks outbound port 25 on every VM, so an SMTP relay must use port 587 or 465.
- Git ignores `.env` but no other name, so a filled copy such as `.env.prod` inside the
  repository can be committed by mistake.

## AI Usage

This guide was drafted with Claude Code from the commands used to build the instance and from the
instance's settings read with `gcloud`; Andrii Shalaiev reviewed it.
