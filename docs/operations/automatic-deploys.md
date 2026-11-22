# Automatic deploys of the public instance

Every push to `main` that changes code and passes CI reaches <https://app.whadio.com> on its own.
The `publish` job pushes the commit's images to GHCR. Then the `deploy-app` job connects to the VM
as the `deploy` user and runs [`infra/deploy/deploy.sh`](../../infra/deploy/deploy.sh) with the
commit's SHA. The job runs only while the repository variable `DEPLOY_HOST` is set. This guide sets that up once, end to end, on the instance that
[Public instance on Google Cloud](public-instance.md) builds, and then covers daily operation.

## How a deploy works

The deploy key's `authorized_keys` entry forces one command, so the key can run `deploy.sh` and
nothing else: no shell, no port forwarding. The script:

1. refuses anything but a full SHA of a commit on `main`, and a second deploy at the same time;
2. checks the commit out in `/opt/whadio` and writes `.env` from the `whadio-env` secret, with
   `IMAGE_TAG=<SHA>` added, so every `docker compose` command there uses the deployed images;
3. pulls the images and dumps the database. If any of this fails, it puts the checkout and `.env`
   back, and the running stack is untouched;
4. starts the stack and checks `https://app.whadio.com/health` through the VM's own nginx;
5. if the new commit does not come up healthy, returns to the running commit, first restoring the
   dump when a migration ran, and fails the CI job;
6. after a success, removes images unused for 7 days and dumps older than 7 days.

## One-time setup

You need the instance from [Public instance on Google Cloud](public-instance.md), admin rights on
the repository, and at least one commit of `main` whose CI run shows "Publish images: success".

### 1. A token that can pull the images

The packages on GHCR are private, so the VM signs in with a classic personal access token. On
GitHub, open **Settings → Developer settings → Personal access tokens → Tokens (classic)**, and
generate a token with only the `read:packages` scope and an expiry after the defence. Copy it; it
is needed in step 5.

### 2. The image names in the configuration secret

On your computer, outside the repository, add the two image repositories to the configuration.
Do not add `IMAGE_TAG`: the script writes it.

```bash
gcloud secrets versions access latest --secret=whadio-env > whadio-env
```

```bash
printf '\n%s\n%s\n' IMAGE_REPOSITORY=ghcr.io/ukma-fin-ssdm-2026/whadio NGINX_IMAGE_REPOSITORY=ghcr.io/ukma-fin-ssdm-2026/whadio-nginx >> whadio-env
```

```bash
gcloud secrets versions add whadio-env --data-file=whadio-env && shred -u whadio-env
```

### 3. The deploy user and its checkout

Connect to the VM with `gcloud compute ssh whadio-1` and run the rest of this step there.

The `docker` group can control every container, which is as much as root on this VM. The forced
command is what keeps the deploy key from using that.

```bash
sudo useradd --create-home --shell /bin/bash --groups docker deploy
```

Clone the repository into `/opt/whadio` for the `deploy` user, and copy over the certificate and
the current configuration from the first install:

```bash
sudo git clone https://github.com/ukma-fin-ssdm-2026/Whadio.git /opt/whadio
sudo chown -R deploy:deploy /opt/whadio
sudo cp -a ~/Whadio/certs /opt/whadio/
sudo install -m 600 -o deploy -g deploy ~/Whadio/.env /opt/whadio/.env
```

`cp -a` keeps uid 101 as the owner of the private key, which nginx needs. If you installed the
certificate renewal hooks, point them at the new checkout:

```bash
sudo sed -i 's|/home/hukyl/Whadio|/opt/whadio|' /etc/letsencrypt/renewal-hooks/*/whadio-*.sh
```

### 4. Check that the deploy user reads the secret

The VM's service account answers for every user on the VM:

```bash
sudo -iu deploy gcloud secrets versions access latest --secret=whadio-env > /dev/null && echo readable
```

### 5. Sign the deploy user in to GHCR

Use your GitHub user name, and paste the token from step 1 when asked for the password. Docker
keeps it in `/home/deploy/.docker/config.json`.

```bash
sudo -iu deploy docker login ghcr.io --username GITHUB_USER
```

### 6. The deploy key

On your computer, outside the repository:

```bash
ssh-keygen -t ed25519 -N "" -C github-actions-deploy -f whadio-deploy
```

On the VM, install its public key (the content of `whadio-deploy.pub`) with the forced command
and no other rights:

```bash
sudo install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
```

```bash
echo 'restrict,command="/opt/whadio/infra/deploy/deploy.sh" PUBLIC_KEY' | sudo -u deploy tee /home/deploy/.ssh/authorized_keys > /dev/null && sudo chmod 600 /home/deploy/.ssh/authorized_keys
```

On your computer, record the VM's host key, and check that its fingerprint matches the one the VM
itself prints with `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`:

```bash
ssh-keyscan -t ed25519 app.whadio.com > whadio-known-hosts && ssh-keygen -lf whadio-known-hosts
```

Check that the key can do nothing but deploy: this must print only the script's usage line.

```bash
ssh -i whadio-deploy -o UserKnownHostsFile=whadio-known-hosts deploy@app.whadio.com hello
```

### 7. The GitHub environment

In the repository's **Settings → Environments**, create the environment `production`. Under
**Deployment branches and tags**, choose **Selected branches and tags** and add `main`. Then, from
the folder with the key files, store the key and the host key as its secrets:

```bash
gh secret set DEPLOY_SSH_KEY --env production --repo ukma-fin-ssdm-2026/Whadio < whadio-deploy
```

```bash
gh secret set DEPLOY_KNOWN_HOSTS --env production --repo ukma-fin-ssdm-2026/Whadio < whadio-known-hosts
```

```bash
shred -u whadio-deploy && rm whadio-deploy.pub whadio-known-hosts
```

The private key now exists only in GitHub. To replace it, repeat steps 6 and 7.

### 8. The first deploy

Choose a commit `SHA` of `main` whose CI run shows "Publish images: success". Then, on the VM, as
the `deploy` user:

```bash
sudo -iu deploy
```

```bash
cd /opt/whadio && infra/deploy/deploy.sh SHA
```

It ends with "Deployed SHA". The Compose project keeps the name `whadio`, so this deploy takes over
the containers that the first install started from `~/Whadio`, with the same volumes and data.
`docker compose ps` in `/opt/whadio` now lists the `ghcr.io` images.

### 9. The rollback drill

Run both as `deploy` in `/opt/whadio`:

1. **A commit without images.** Deploy a commit of `main` whose CI run did not publish, such as a
   documentation-only one. The pull fails, the script prints "nothing was changed", and the site
   stays up.
2. **An unhealthy commit.** Add `HTTPS_PORT=8444` to the configuration secret as in step 2, and
   deploy the running SHA again. nginx then listens on port 8444, the health check on 443 fails,
   and the script returns to the running configuration within about two minutes. Then add a new
   secret version without that line.

### 10. Turn on automatic deploys

Set the repository variable that the deploy job waits for. It is a repository variable, not an
environment one, because the job's condition reads it:

```bash
gh variable set DEPLOY_HOST --repo ukma-fin-ssdm-2026/Whadio --body app.whadio.com
```

The next push to `main` that changes code is deployed. Its run's "Deploy the public instance" job
must succeed. Deleting the variable turns automatic deploys off again.

### 11. Clean up

After the first automatic deploy succeeds, remove the first install's checkout, which holds a copy
of the configuration:

```bash
rm -rf ~/Whadio
```

## Operating the deploys

- **Watching a deploy.** In the repository's **Actions**, the `main` run's "Deploy the public
  instance" job shows the script's output.
- **Rolling back.** Re-run the "Deploy the public instance" job of an earlier `main` run, or run
  `infra/deploy/deploy.sh SHA` as `deploy`. A commit older than the database's last migration does
  not start: its migrations fail, and the script returns to the running commit.
- **Changing the configuration.** Add a new version of the `whadio-env` secret, then deploy the
  running commit again as `deploy`:
  `cd /opt/whadio && infra/deploy/deploy.sh "$(git rev-parse HEAD)"`. Do not write `.env` by hand:
  without `IMAGE_TAG`, Compose falls back to images that do not exist on the VM.
- **Running Compose.** Run `docker compose` commands as `deploy` in `/opt/whadio`, where `.env`
  names the deployed images.
- **An expired token.** When the token from step 1 expires, every deploy stops at "Could not
  prepare" and the running commit stays. Create a new token and repeat step 5.
- **Database dumps.** `/home/deploy/backups` keeps a dump from before each deploy for 7 days, named
  after the commit that was running. The disk snapshots of the VM add a daily copy.

## AI Usage

This guide was drafted with Claude Code from the deploy script, the CI job and the instance's
settings; Andrii Shalaiev reviewed it.
