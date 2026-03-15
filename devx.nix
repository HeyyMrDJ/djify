{ pkgs, lib }:
let
  djify-kind-load-image = pkgs.writeShellApplication {
    name = "djify-kind-load-image";
    runtimeInputs = [ pkgs.kind ];
    text = ''
      kind load docker-image djify:latest --name djify
    '';
    meta.description = "Loads the docker image in kind cluster";
  };
  djify-kind-up = pkgs.writeShellApplication {
    name = "djify-kind-up";
    runtimeInputs = [ pkgs.kind ];
    text = ''
      kind create cluster --config kind-config.yaml --name djify
    '';
    meta.description = "Create a kind cluster named djify";
  };

  djify-kind-down = pkgs.writeShellApplication {
    name = "djify-kind-down";
    runtimeInputs = [ pkgs.kind ];
    text = ''
      kind delete cluster --name djify
    '';
    meta.description = "Delete the djify kind cluster";
  };

  djify-install-ingress = pkgs.writeShellApplication {
    name = "djify-install-ingress";
    runtimeInputs = [ pkgs.kubectl ];
    text = ''
      kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
      echo "Waiting for ingress-nginx to be ready..."
      kubectl wait --namespace ingress-nginx \
        --for=condition=ready pod \
        --selector=app.kubernetes.io/component=controller \
        --timeout=90s
    '';
    meta.description = "Install Ingress NGINX controller for kind";
  };

  djify-sync = pkgs.writeShellApplication {
    name = "djify-sync";
    runtimeInputs = [ pkgs.uv ];
    text = ''
      uv sync
    '';
    meta.description = "Install/sync Python dependencies via uv";
  };

  djify-install-crd = pkgs.writeShellApplication {
    name = "djify-install-crd";
    runtimeInputs = [ pkgs.kubectl ];
    text = ''
      kubectl apply -f crds/
    '';
    meta.description = "Apply the App CRD to the cluster";
  };

  djify-install-infra = pkgs.writeShellApplication {
    name = "djify-install-infra";
    runtimeInputs = [ pkgs.kubectl ];
    text = ''
      kubectl apply -f deploy/namespace.yaml
      kubectl apply -f deploy/rbac.yaml
      kubectl apply -f deploy/registry.yaml
      kubectl apply -f deploy/buildkitd.yaml
      echo ""
      echo "Waiting for registry to be ready..."
      kubectl rollout status deployment/registry -n djify-system --timeout=120s
      echo "Waiting for buildkitd to be ready..."
      kubectl rollout status deployment/buildkitd -n djify-system --timeout=120s
      echo ""
      cat <<EOF
      ---------------------------------------------------------------"
      IMPORTANT: k3s node trust for in-cluster registry

      Copy config/k3s-registries.yaml to your k3s node:
        sudo cp config/k3s-registries.yaml /etc/rancher/k3s/registries.yaml
        sudo systemctl restart k3s
      ---------------------------------------------------------------"
      EOF
    '';
    meta.description = "Apply namespace, RBAC, registry, and buildkitd to the cluster";
  };

  djify-dev = pkgs.writeShellApplication {
    name = "djify-dev";
    runtimeInputs = [ pkgs.uv ];
    text = ''
      echo "Starting controller locally (namespace=default)..."
      uv run kopf run controller/main.py \
        --namespace=default \
        --dev \
        --log-format=plain \
        --verbose
    '';
    meta.description = "Run the kopf controller locally against the cluster";
  };

  djify-sample = pkgs.writeShellApplication {
    name = "djify-sample";
    runtimeInputs = [ pkgs.kubectl ];
    text = ''
      kubectl apply -f examples/sample-app.yaml
      cat <<EOF
      App CR applied. Watch progress:
        kubectl get apps -n default -w
        kubectl describe app sample-app -n default
      EOF
    '';
    meta.description = "Apply the sample App CR to the cluster";
  };

  djify-delete-sample = pkgs.writeShellApplication {
    name = "djify-delete-sample";
    runtimeInputs = [ pkgs.kubectl ];
    text = ''
      kubectl delete -f examples/sample-app.yaml --ignore-not-found
    '';
    meta.description = "Delete the sample App CR from the cluster";
  };

  djify-uninstall = pkgs.writeShellApplication {
    name = "djify-uninstall";
    runtimeInputs = [ pkgs.kubectl ];
    text = ''
      kubectl delete -f examples/ --ignore-not-found || true
      kubectl delete -f deploy/ --ignore-not-found || true
      kubectl delete -f crds/ --ignore-not-found || true
      echo "djify resources removed."
    '';
    meta.description = "Remove all djify resources from the cluster";
  };

  djify-docker-load = pkgs.writeShellApplication {
    name = "djify-docker-load";
    runtimeInputs = [
      pkgs.nix
      pkgs.docker
    ];
    text = ''
      echo "Building docker image..."
      nix build .#dockerImage --out-link /tmp/djify-docker-image
      echo "Loading image into Docker daemon..."
      docker load < /tmp/djify-docker-image
    '';
    meta.description = "Build the djify Docker image via Nix and load it into the Docker daemon";
  };

  djify-clean = pkgs.writeShellApplication {
    name = "djify-clean";
    runtimeInputs = [
      pkgs.coreutils
      pkgs.findutils
    ];
    text = ''
      rm -rf .venv
      find . -type d -name __pycache__ -exec rm -rf {} + || true
      find . -name "*.pyc" -delete || true
      echo "Cleaned."
    '';
    meta.description = "Remove .venv and Python cache files";
  };

  # All scripts except djify-help so it can iterate over them to build its output
  scripts = [
    djify-kind-up
    djify-kind-down
    djify-install-ingress
    djify-sync
    djify-install-crd
    djify-install-infra
    djify-dev
    djify-sample
    djify-delete-sample
    djify-uninstall
    djify-docker-load
    djify-kind-load-image
    djify-clean
  ];

  djify-help = pkgs.writeShellApplication {
    name = "djify-help";
    text = ''
      printf '\ndjify dev shell — available commands\n\n'
      ${lib.concatMapStrings (s: "printf '  %-26s  %s\\n' '${s.name}' '${s.meta.description}'\n") scripts}
      printf '\nFirst-time setup (with kind):\n'
      printf '  1. djify-kind-up && djify-install-ingress\n'
      printf '  2. djify-sync\n'
      printf '  3. djify-install-crd && djify-install-infra\n'
      printf '  4. Update config/k3s-registries.yaml and point to registry IP\n'
      printf '  5. djify-dev\n\n'
    '';
    meta.description = "Print available djify dev shell commands";
  };
in
scripts ++ [ djify-help ]
