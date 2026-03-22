# djify

A self-hosted, Kubernetes-native PaaS. Point it at a Git repo with a Dockerfile and djify builds the image in-cluster, pushes it to an in-cluster registry, and deploys it with a Deployment, Service, and Ingress — all driven by a single Kubernetes CRD.

Think Vercel, Netlify, coolify, but running on your own kubernetes cluster. 

Kubernetes is the state, there is no database outside of the kubernetes etcd (or whatever your cluster is using). And because this is just kubernetes, you can deploy via kubectl, API (curl, or kubernetes language specific SDKs), GitOps (eg. Argo CD), or the included webui. 

---

## How it works

1. You create an `App` custom resource pointing at a Git repo
2. The djify controller clones the repo, builds the image using BuildKit, and pushes it to the in-cluster registry
3. A Deployment + Service + Ingress are created automatically
4. The app is available at `http://<appname>.<DJIFY_DOMAIN>` (default: `<appname>.djify.local`)

Updating `spec` on the `App` CR triggers a rebuild and redeploy automatically. The ingress hostname is kept in sync with the current `DJIFY_DOMAIN` — if the domain changes, all ingresses are updated within 30 seconds without a rebuild.

---
## Screenshots
<img width="1872" height="507" alt="image" src="https://github.com/user-attachments/assets/afebaaa5-1f0b-4912-95a9-6da803e153e3" />
<img width="1301" height="730" alt="image" src="https://github.com/user-attachments/assets/b42be7d9-8261-4675-8e57-973680187de4" />


---
## Prerequisites

- [k3s](https://k3s.io) or [kind](https://kind.sigs.k8s.io) cluster
- `kubectl` configured to talk to your cluster
- Nix (see below) — manages Python, uv, kubectl, kind, Go, and all dev tooling

---

## Development environment

The recommended way to work on djify is via the Nix dev shell. It gives every contributor an identical, fully reproducible environment with all tools pinned — no manual installs, no PATH fiddling.

### 1. Install Nix

Use the [Determinate Systems installer](https://determinate.systems/nix), which enables flakes out of the box:

```bash
curl --proto '=https' --tlsv1.2 -sSf -L https://install.determinate.systems/nix | sh -s -- install
```

Follow the prompts, then open a new terminal to pick up the `nix` command.

### 2. Enter the dev shell

```bash
nix develop
```

Or, if you have [direnv](https://direnv.net) installed:

```bash
direnv allow
```

The dev shell activates automatically whenever you `cd` into the project.

### 3. Available commands

Run `djify-help` to see all commands:

```
djify dev shell — available commands

  djify-kind-up              Create a kind cluster named djify
  djify-kind-down            Delete the djify kind cluster
  djify-install-ingress      Install Ingress NGINX controller for kind
  djify-sync                 Install/sync Python dependencies via uv
  djify-install-crd          Apply the App CRD to the cluster
  djify-install-infra        Apply namespace, RBAC, registry, and buildkitd
  djify-dev                  Run the kopf controller locally against the cluster
  djify-webui                Run the djify web UI locally on :8080
  djify-sample               Apply the sample App CR
  djify-delete-sample        Delete the sample App CR
  djify-uninstall            Remove all djify resources from the cluster
  djify-docker-load          Build the djify Docker image via Nix and load it
  djify-kind-load-image      Load the docker image into the kind cluster
  djify-clean                Remove .venv and Python cache files

First-time setup (with kind):
  1. djify-kind-up && djify-install-ingress
  2. djify-sync
  3. djify-install-crd && djify-install-infra
  4. djify-dev
```

---

## Setup

### Local development with kind

Create a 3-node cluster (1 control-plane, 2 workers) with the in-cluster registry mirror pre-configured:

```bash
djify-kind-up
djify-install-ingress
```

> **Note:** `djify-kind-up` pre-creates the Podman `kind` network with the correct settings. If you already have a `kind` network from a previous install, it will be recreated automatically.

### 1. Install Python dependencies

```bash
djify-sync
```

### 2. Install the CRD and in-cluster infrastructure

```bash
djify-install-crd
djify-install-infra
```

This applies:
- `djify-system` namespace
- RBAC (ClusterRole + binding for the controller)
- In-cluster `registry:2` Deployment + Service (ClusterIP pinned to `10.96.112.244`)
- BuildKit (`moby/buildkit`) Deployment

> **k3s users:** after this step, copy the registry mirror config to your node and restart k3s:
> ```bash
> sudo cp config/k3s-registries.yaml /etc/rancher/k3s/registries.yaml
> sudo systemctl restart k3s
> ```

### 3. Configure your domain

djify generates ingress hostnames as `<appname>.<DJIFY_DOMAIN>`. The default domain is `djify.local`.

Set `DJIFY_DOMAIN` to your preferred domain before starting the controller:

```bash
export DJIFY_DOMAIN=djify.example.com
```

**DNS setup options:**

- **Wildcard DNS (recommended):** Add a `*.djify.example.com` `A` record pointing to your node IP (or `127.0.0.1` for local kind). Any DNS provider that supports wildcards works — Cloudflare, Route53, etc.
- **dnsmasq (macOS local dev):** `echo 'address=/djify.local/127.0.0.1' >> $(brew --prefix)/etc/dnsmasq.conf` and add `/etc/resolver/djify.local` pointing to `127.0.0.1`.
- **`/etc/hosts` (per-app fallback):** Add `127.0.0.1 <appname>.djify.local` for each app.

### 4. Start the controller

```bash
djify-dev
```

The controller runs locally using your kubeconfig and watches the `default` namespace for `App` CRs. Leave this running in a terminal.

### 5. Start the web UI (optional)

```bash
djify-webui
```

Opens a dark-themed dashboard at `http://localhost:8080` where you can view all deployed apps, check build status, create new apps, and delete existing ones.

The web UI picks up `DJIFY_DOMAIN` automatically. You can also pass it explicitly:

```bash
go run ./webui/ -domain djify.example.com
```

---

## Deploy an example app

With the controller running, apply the sample App CR:

```bash
djify-sample
```

This deploys [dockersamples/node-bulletin-board](https://github.com/dockersamples/node-bulletin-board) — a Node.js app listening on port 8080.

Watch it build and deploy:

```bash
kubectl get apps -w
```

```
NAME         PHASE       IMAGE                                                          AGE
sample-app   Building                                                                   5s
sample-app   Deploying   registry.djify-system.svc.cluster.local:5000/sample-app:...   40s
sample-app   Ready       registry.djify-system.svc.cluster.local:5000/sample-app:...   45s
```

Once `Ready`, open `http://sample-app.<DJIFY_DOMAIN>` in your browser.

To clean up:

```bash
djify-delete-sample
```

---

## Deploy your own app

Create an `App` CR. The only required fields are `repoUrl` and `port`:

```yaml
apiVersion: djify.io/v1alpha1
kind: App
metadata:
  name: my-app
  namespace: default
spec:
  repoUrl: https://github.com/you/your-repo
  port: 8080
```

Apply it:

```bash
kubectl apply -f my-app.yaml
```

### Full spec reference

| Field | Required | Default | Description |
|---|---|---|---|
| `repoUrl` | yes | — | HTTPS Git URL of the repository |
| `port` | yes | — | Port the container listens on |
| `branch` | no | `main` | Branch to build from |
| `dockerfilePath` | no | `Dockerfile` | Path to the Dockerfile, relative to the build context root |
| `contextPath` | no | — | Subdirectory to use as the build context root (see below) |
| `replicas` | no | `1` | Number of pod replicas |
| `ingressHost` | no | `<name>.<DJIFY_DOMAIN>` | Override the computed ingress hostname |

### `contextPath` and `dockerfilePath`

**Dockerfile at repo root** (most common — omit both):
```yaml
spec:
  repoUrl: https://github.com/you/repo
  port: 8080
```

**Dockerfile in a subdirectory** (context = that subdirectory):
```yaml
spec:
  repoUrl: https://github.com/you/repo
  dockerfilePath: app/Dockerfile
  port: 8080
```

**Dockerfile and context both in a subdirectory:**
```yaml
spec:
  repoUrl: https://github.com/you/monorepo
  contextPath: services/api
  dockerfilePath: Dockerfile
  port: 3000
```

### Trigger a rebuild

Any change to `spec` triggers a rebuild and redeploy. To force a rebuild without changing app config:

```bash
kubectl patch app my-app --type=merge -p '{"spec":{"replicas":2}}'
kubectl patch app my-app --type=merge -p '{"spec":{"replicas":1}}'
```

### Check status

```bash
kubectl get apps
kubectl describe app my-app
```

The `status.message` field contains error detail if the phase is `Failed`.

### Delete an app

```bash
kubectl delete app my-app
```

This removes the Deployment, Service, Ingress, and any lingering build Jobs.

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DJIFY_DOMAIN` | `djify.local` | Base domain for generated ingress hostnames (`<appname>.<DJIFY_DOMAIN>`) |
| `DJIFY_INGRESS_CLASS` | `traefik` | Ingress class to use — `traefik` for k3s, `nginx` for kind |

Both are exported automatically by `djify-dev` and `djify-webui` when running inside the Nix dev shell.

---

## Project layout

```
├── config/
│   └── k3s-registries.yaml      # containerd registry mirror config for k3s
├── controller/
│   ├── main.py                   # kopf entrypoint
│   └── handlers/
│       ├── app.py                # on_create / on_update / on_delete / timer handlers
│       ├── build.py              # BuildKit job orchestration
│       └── deploy.py             # Deployment + Service + Ingress management
├── crds/
│   └── apps.djify.io.yaml        # App CRD definition
├── deploy/
│   ├── namespace.yaml
│   ├── rbac.yaml
│   ├── registry.yaml             # in-cluster registry:2 (ClusterIP pinned)
│   ├── buildkitd.yaml            # moby/buildkit
│   └── webui.yaml                # web UI ServiceAccount + RBAC + Deployment + Ingress
├── webui/
│   ├── go.mod                    # Go module (djify/webui)
│   ├── main.go                   # HTTP server, embedded assets, routes
│   ├── handlers/                 # list, detail, create, delete handlers
│   ├── k8s/                      # kubeconfig loader
│   ├── templates/                # HTMX + server-side Go templates
│   └── static/                   # CSS (dark theme)
├── examples/
│   └── sample-app.yaml
├── kind-config.yaml              # kind cluster config (port mappings, registry mirror)
├── registry-configs/             # containerd mirror config for kind worker nodes
├── flake.nix                     # Nix flake outputs
├── devx.nix                      # all djify-* dev scripts
├── pyproject.toml                # uv Python dependencies
├── uv.lock                       # pinned Python dependency tree
└── .envrc                        # direnv entry point
```
