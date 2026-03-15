# djify — Makefile
# Requires: kubectl (pointing at k3s), python3.12, pip

CONTROLLER_DIR := controller
VENV           := .venv
PYTHON         := $(VENV)/bin/python
PIP            := $(VENV)/bin/pip
KOPF           := $(VENV)/bin/kopf

# Namespace where user App CRs live (controller watches this)
APP_NAMESPACE  := default

.PHONY: help venv install-deps install-crd install-infra dev \
        sample delete-sample uninstall clean

help:
	@echo ""
	@echo "djify — available targets"
	@echo ""
	@echo "  make venv            Create .venv with Python 3.12"
	@echo "  make install-deps    Install Python dependencies into .venv"
	@echo "  make install-crd     Apply the App CRD to k3s"
	@echo "  make install-infra   Apply namespace, RBAC, registry, buildkitd"
	@echo "  make dev             Run the controller locally (uses kubeconfig)"
	@echo "  make sample          Apply examples/sample-app.yaml"
	@echo "  make delete-sample   Delete examples/sample-app.yaml"
	@echo "  make uninstall       Remove all djify resources from k3s"
	@echo "  make clean           Remove .venv and __pycache__"
	@echo ""
	@echo "First-time setup:"
	@echo "  1. make venv install-deps"
	@echo "  2. make install-crd install-infra"
	@echo "  3. Apply k3s registries config (see config/k3s-registries.yaml)"
	@echo "  4. make dev"
	@echo ""

venv:
	python3.12 -m venv $(VENV)
	@echo "Venv created at $(VENV)"

install-deps: venv
	$(PIP) install --upgrade pip
	$(PIP) install -r $(CONTROLLER_DIR)/requirements.txt

install-crd:
	kubectl apply -f crds/

install-infra:
	kubectl apply -f deploy/namespace.yaml
	kubectl apply -f deploy/rbac.yaml
	kubectl apply -f deploy/registry.yaml
	kubectl apply -f deploy/buildkitd.yaml
	@echo ""
	@echo "Waiting for registry to be ready..."
	kubectl rollout status deployment/registry -n djify-system --timeout=120s
	@echo "Waiting for buildkitd to be ready..."
	kubectl rollout status deployment/buildkitd -n djify-system --timeout=120s
	@echo ""
	@echo "---------------------------------------------------------------"
	@echo "IMPORTANT: k3s node trust for in-cluster registry"
	@echo ""
	@echo "Copy config/k3s-registries.yaml to your k3s node:"
	@echo "  sudo cp config/k3s-registries.yaml /etc/rancher/k3s/registries.yaml"
	@echo "  sudo systemctl restart k3s"
	@echo ""
	@echo "Then run: make dev"
	@echo "---------------------------------------------------------------"

dev:
	@echo "Starting controller locally (namespace=$(APP_NAMESPACE))..."
	$(KOPF) run $(CONTROLLER_DIR)/main.py \
		--namespace=$(APP_NAMESPACE) \
		--dev \
		--log-format=plain \
		--verbose

sample:
	kubectl apply -f examples/sample-app.yaml
	@echo "App CR applied. Watch progress:"
	@echo "  kubectl get apps -n default -w"
	@echo "  kubectl describe app sample-app -n default"

delete-sample:
	kubectl delete -f examples/sample-app.yaml --ignore-not-found

uninstall:
	kubectl delete -f examples/ --ignore-not-found || true
	kubectl delete -f deploy/ --ignore-not-found || true
	kubectl delete -f crds/ --ignore-not-found || true
	@echo "djify resources removed."

clean:
	rm -rf $(VENV)
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	@echo "Cleaned."
