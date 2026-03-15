# djify

A self-hosted, Kubernetes-native PaaS. Point it at a Git repo with a Dockerfile and djify builds the image in-cluster, pushes it to an in-cluster registry, and deploys it with a Deployment, Service, and Ingress — all driven by a single Kubernetes CRD.

Think Coolify or Render, but running on your own k3s cluster.

---

## How it works

1. You create an `App` custom resource pointing at a Git repo
2. The djify controller clones the repo, builds the image using BuildKit, and pushes it to the in-cluster registry
3. A Deployment + Service + Ingress are created automatically
4. The app is available at `http://<appname>.djify.local` via Traefik

Updating `spec` on the `App` CR triggers a rebuild and redeploy automatically.

---

## Prerequisites

- [k3s](https://k3s.io) or [kind](https://kind.sigs.k8s.io) cluster
- `kubectl` configured to talk to your cluster
- Nix (see below) — manages Python, uv, kubectl, kind, and all dev tooling

---

## Development environment

The recommended way to work on djify is via the Nix dev shell. It gives every contributor an identical, fully reproducible environment with all tools pinned — no manual Python installs, no PATH fiddling.

### 1. Install Nix

Use the [Determinate Systems installer](https://determinate.systems/nix), which enables flakes out of the box:

```bash
curl --proto '=https' --tlsv1.2 -sSf -L https://install.determinate.systems/nix | sh -s -- install
```

Follow the prompts, then open a new terminal (or source your shell profile) to pick up the `nix` command.

### 2. Enter the dev shell

From the repo root:

```bash
nix develop
```

Or run:

```bash
direnv allow
```
In case direnv is installed in the system

This drops you into a shell with Python 3.12, uv, kubectl, and kind on `PATH`, plus all `djify-*` commands available directly. You'll see:

```
djify dev shell ready
  Python : Python 3.12.x
  uv     : uv x.x.x

Run 'djify-help' to see available commands.
```

### 3. Available commands

```
djify dev shell — available commands

  djify-kind-up          Create a kind cluster (djify)
  djify-kind-down        Delete the kind cluster
  djify-install-ingress  Install Ingress NGINX (for kind)
  djify-sync             Install/sync Python dependencies (uv sync)
  djify-install-crd      Apply the App CRD to the cluster
  djify-install-infra    Apply namespace, RBAC, registry, buildkitd
  djify-dev              Run the controller locally
  djify-sample           Apply examples/sample-app.yaml
  djify-delete-sample    Delete examples/sample-app.yaml
  djify-uninstall        Remove all djify resources from the cluster
  djify-docker-load      Build the Docker image and load it into the daemon
  djify-clean            Remove .venv and __pycache__

First-time setup (with kind):
  1. djify-kind-up && djify-install-ingress
  2. djify-sync
  3. djify-install-crd && djify-install-infra
  4. Update config/k3s-registries.yaml and point to registry IP
  5. djify-dev
```

### direnv (optional)

If you have [direnv](https://direnv.net) installed, a `.envrc` is already included in the repo. Just run:

```bash
direnv allow
```

The dev shell will activate automatically whenever you `cd` into the project — no need to run `nix develop` manually.

### Nix build targets

```bash
nix build              # build the Python virtualenv derivation
nix build .#dockerImage  # build the controller Docker image as a Nix derivation
djify-docker-load      # build .#dockerImage and load it into the local Docker daemon
```

---

## Setup

### Local development with kind (optional)

If you don't have k3s running, you can use `kind` to create a 3-node cluster:
```bash
make kind-up install-ingress
```

### 1. Configure the in-cluster registry

k3s's containerd runtime needs to know to pull from the in-cluster registry over plain HTTP.

Get the registry Service's ClusterIP (after step 3 below):
```bash
kubectl get svc registry -n djify-system -o jsonpath='{.spec.clusterIP}'
```

Edit `config/k3s-registries.yaml` and replace `<REGISTRY_CLUSTER_IP>` with that value, then copy it to your k3s node and restart k3s:
```bash
sudo cp config/k3s-registries.yaml /etc/rancher/k3s/registries.yaml
sudo systemctl restart k3s
```

> If your k3s node is remote, SSH in first before running the above commands.

### 2. Install Python dependencies

```bash
make venv install-deps
```

### 3. Install the CRD and in-cluster infrastructure

```bash
make install-crd install-infra
```

This applies:
- `djify-system` namespace
- RBAC (ClusterRole + binding for the controller)
- In-cluster `registry:2` Deployment + Service + PVC
- BuildKit (`moby/buildkit`) Deployment

After this completes, run the registry ClusterIP command from step 1 and update `config/k3s-registries.yaml` if you haven't already.

### 4. Start the controller

```bash
make dev
```

The controller runs locally using your kubeconfig and watches the `default` namespace for `App` CRs. Leave this running in a terminal.

---

## Deploy an example app

With the controller running, apply the sample App CR:

```bash
make sample
```

This deploys [dockersamples/node-bulletin-board](https://github.com/dockersamples/node-bulletin-board) — a Node.js app with a Dockerfile at `bulletin-board-app/Dockerfile` listening on port 8080.

Watch it progress through the build and deploy phases:
```bash
kubectl get apps -w
```

```
NAME         PHASE       IMAGE                                                          AGE
sample-app   Building                                                                   5s
sample-app   Deploying   registry.djify-system.svc.cluster.local:5000/sample-app:...   40s
sample-app   Ready       registry.djify-system.svc.cluster.local:5000/sample-app:...   45s
```

Once `Ready`, add the hostname to your local `/etc/hosts` pointing at your k3s node IP:
```
192.168.x.x   sample-app.djify.local
```

Then open `http://sample-app.djify.local` in your browser, or test with curl:
```bash
curl -H "Host: sample-app.djify.local" http://<k3s-node-ip>
```

To clean up:
```bash
make delete-sample
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
| `ingressHost` | no | `<name>.djify.local` | Override the default ingress hostname |

### `contextPath` and `dockerfilePath`

These two fields control how BuildKit clones and builds from your repo.

**Dockerfile at repo root** (most common — omit both):
```yaml
spec:
  repoUrl: https://github.com/you/repo
  port: 8080
  # dockerfilePath defaults to "Dockerfile" at repo root
```

**Dockerfile in a subdirectory, context = that subdirectory** (omit `contextPath`):
```yaml
spec:
  repoUrl: https://github.com/you/repo
  dockerfilePath: app/Dockerfile   # context root becomes app/, filename becomes Dockerfile
  port: 8080
```

**Dockerfile in a subdirectory, context = repo root** (set `contextPath: ""`):
```yaml
spec:
  repoUrl: https://github.com/you/repo
  dockerfilePath: docker/Dockerfile  # relative to repo root
  contextPath: ""                    # repo root is the build context
  port: 8080
```

**Dockerfile and context both in a subdirectory** (set `contextPath` to that subdir):
```yaml
spec:
  repoUrl: https://github.com/you/monorepo
  contextPath: services/api          # build context root
  dockerfilePath: Dockerfile         # relative to contextPath
  port: 3000
```

### Trigger a rebuild

Any change to `spec` triggers a rebuild and redeploy. To force a rebuild without changing app config, bump `replicas` and back:
```bash
kubectl patch app my-app --type=merge -p '{"spec":{"replicas":2}}'
kubectl patch app my-app --type=merge -p '{"spec":{"replicas":1}}'
```

### Check status

```bash
kubectl get apps
kubectl describe app my-app
```

The `status.message` field contains the error detail if the phase is `Failed`.

### Delete an app

```bash
kubectl delete app my-app
```

This removes the Deployment, Service, Ingress, and any lingering build Jobs.

---

## Project layout

```
├── config/
│   └── k3s-registries.yaml     # containerd registry mirror config for k3s node
├── controller/
│   ├── main.py                  # kopf entrypoint
│   ├── requirements.txt
│   └── handlers/
│       ├── app.py               # on_create / on_update / on_delete handlers
│       ├── build.py             # BuildKit job orchestration
│       └── deploy.py            # Deployment + Service + Ingress management
├── crds/
│   └── apps.djify.io.yaml       # App CRD definition
├── deploy/
│   ├── namespace.yaml
│   ├── rbac.yaml
│   ├── registry.yaml            # in-cluster registry:2
│   └── buildkitd.yaml           # moby/buildkit
├── examples/
│   └── sample-app.yaml
├── flake.nix                    # Nix flake: venv + Docker image outputs, imports dev shell
├── flake.lock                   # pinned Nix input revisions (committed)
├── shell.nix                    # Nix dev shell definition (imported by flake.nix)
├── devx.nix                     # all djify-* dev scripts (writeShellApplication)
├── default.nix                  # callPackage-compatible Docker image build
├── pyproject.toml               # uv workspace root + dependency declarations
├── uv.lock                      # pinned Python dependency tree (committed)
└── .envrc                       # direnv entry point — runs `use flake` to activate the dev shell
```

---

## Makefile targets

| Target | Description |
|---|---|
| `make kind-up` | Create a 3-node kind cluster (1 control, 2 workers) |
| `make kind-down` | Delete the kind cluster |
| `make install-ingress` | Install Ingress NGINX (for kind) |
| `make venv` | Create `.venv` with Python 3.12 |
| `make install-deps` | Install Python dependencies into `.venv` |
| `make install-crd` | Apply the App CRD to the cluster |
| `make install-infra` | Apply namespace, RBAC, registry, and buildkitd |
| `make dev` | Run the controller locally using kubeconfig |
| `make sample` | Apply `examples/sample-app.yaml` |
| `make delete-sample` | Delete the sample App CR |
| `make uninstall` | Remove all djify resources from the cluster |
| `make clean` | Remove `.venv` and `__pycache__` |
