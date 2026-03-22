"""
app.py — kopf handlers for the App CRD (djify.io/v1alpha1).

Handler flow:
  on_create / on_update:
    1. Patch status → Building
    2. run_build() → image_ref
    3. Patch status → Deploying
    4. apply_workload() → Deployment + Service + Ingress
    5. Patch status → Ready

  on_delete:
    1. delete_workload() — removes Deployment, Service, Ingress
    2. cleanup_build_job() — removes any lingering build Job
"""

import datetime
import logging
import os

import kopf
from kubernetes import client as k8s_client, config as k8s_config

from handlers.build import run_build, cleanup_build_job
from handlers.deploy import apply_workload, delete_workload

log = logging.getLogger(__name__)

# ── kopf startup: load kubeconfig (local dev) or in-cluster config ────────────

@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_):
    """Load k8s credentials once at operator startup."""
    try:
        k8s_config.load_incluster_config()
        log.info("Loaded in-cluster kubeconfig")
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()
        log.info("Loaded local kubeconfig")

    # Give handlers more time — builds can take a few minutes
    settings.execution.max_workers = 5
    settings.persistence.finalizer = "djify.io/finalizer"


# ── helpers ───────────────────────────────────────────────────────────────────

def _patch_status(namespace: str, name: str, patch: dict) -> None:
    """Directly patch the App status subresource."""
    custom_api = k8s_client.CustomObjectsApi()
    custom_api.patch_namespaced_custom_object_status(
        group="djify.io",
        version="v1alpha1",
        namespace=namespace,
        plural="apps",
        name=name,
        body={"status": patch},
    )


def _ingress_host(app_name: str, spec: dict) -> str:
    """Return the ingress hostname — spec.ingressHost or <appname>.<DJIFY_DOMAIN>."""
    domain = os.environ.get("DJIFY_DOMAIN", "djify.local")
    return spec.get("ingressHost") or f"{app_name}.{domain}"


# ── create handler ─────────────────────────────────────────────────────────────

@kopf.on.create("djify.io", "v1alpha1", "apps")
async def on_create(spec, name, namespace, logger, **kwargs):
    """Handle a new App CR: build image then deploy workload."""
    await _reconcile(spec, name, namespace, logger)


# ── update handler ─────────────────────────────────────────────────────────────

@kopf.on.update("djify.io", "v1alpha1", "apps", field="spec")
async def on_update(spec, name, namespace, logger, **kwargs):
    """Handle updates to an App CR spec: rebuild and redeploy.

    The `field='spec'` filter ensures this only fires when the spec actually
    changes — status patches (phase, message, image) do NOT trigger this
    handler, preventing the infinite create→status-patch→update→build loop.
    """
    await _reconcile(spec, name, namespace, logger)


# ── ingress drift correction ──────────────────────────────────────────────────

@kopf.on.timer("djify.io", "v1alpha1", "apps", interval=30.0, idle=10.0)
async def reconcile_ingress(spec, name, namespace, logger, **kwargs):
    """Periodically ensure the Ingress hostname matches the current DJIFY_DOMAIN.

    This corrects drift when DJIFY_DOMAIN changes without touching app specs,
    without triggering a full rebuild.
    """
    net_api = k8s_client.NetworkingV1Api()
    expected_host = _ingress_host(name, spec)

    try:
        ingress = net_api.read_namespaced_ingress(name=name, namespace=namespace)
    except k8s_client.ApiException as exc:
        if exc.status == 404:
            return  # ingress not created yet — on_create will handle it
        raise

    rules = (ingress.spec.rules or [])
    current_host = rules[0].host if rules else None

    if current_host == expected_host:
        return  # nothing to do

    logger.info(
        "Ingress host drift detected for %s: %r → %r",
        name, current_host, expected_host,
    )

    from handlers.deploy import _ingress_manifest, FIELD_MANAGER
    body = _ingress_manifest(name, namespace, expected_host)
    net_api.patch_namespaced_ingress(
        name=name,
        namespace=namespace,
        body=body,
        field_manager=FIELD_MANAGER,
    )

    _patch_status(namespace, name, {
        "message": f"Available at http://{expected_host}",
    })
    logger.info("Ingress host updated to %r for %s/%s", expected_host, namespace, name)


# ── shared reconcile logic ────────────────────────────────────────────────────

async def _reconcile(spec: dict, name: str, namespace: str, logger: logging.Logger):
    repo_url = spec["repoUrl"]
    branch = spec.get("branch", "main")
    dockerfile_path = spec.get("dockerfilePath", "Dockerfile")
    context_path = spec.get("contextPath", None)  # None = unset (legacy), "" = repo root
    port = spec["port"]
    replicas = spec.get("replicas", 1)
    host = _ingress_host(name, spec)

    # ── Phase: Building ───────────────────────────────────────────────────────
    _patch_status(namespace, name, {
        "phase": "Building",
        "message": f"Building image from {repo_url}#{branch}",
    })
    logger.info("Building from %s#%s", repo_url, branch)

    try:
        image_ref = await run_build(
            app_name=name,
            namespace=namespace,
            repo_url=repo_url,
            branch=branch,
            dockerfile_path=dockerfile_path,
            logger=logger,
            context_path=context_path,
        )
    except kopf.PermanentError as exc:
        _patch_status(namespace, name, {
            "phase": "Failed",
            "message": str(exc)[:512],  # keep status tidy
        })
        raise  # re-raise so kopf records the failure

    # ── Phase: Deploying ──────────────────────────────────────────────────────
    _patch_status(namespace, name, {
        "phase": "Deploying",
        "image": image_ref,
        "message": "Deploying workload...",
    })

    apply_workload(
        app_name=name,
        namespace=namespace,
        image_ref=image_ref,
        port=port,
        replicas=replicas,
        ingress_host=host,
        logger=logger,
    )

    # ── Phase: Ready ──────────────────────────────────────────────────────────
    _patch_status(namespace, name, {
        "phase": "Ready",
        "image": image_ref,
        "lastBuildTime": datetime.datetime.utcnow().isoformat() + "Z",
        "message": f"Available at http://{host}",
    })
    logger.info("App %s/%s is Ready at http://%s", namespace, name, host)


# ── delete handler ─────────────────────────────────────────────────────────────

@kopf.on.delete("djify.io", "v1alpha1", "apps")
def on_delete(spec, name, namespace, logger, **kwargs):
    """Clean up all resources owned by this App CR."""
    logger.info("Deleting workload and build job for App %s/%s", namespace, name)
    delete_workload(app_name=name, namespace=namespace, logger=logger)
    cleanup_build_job(app_name=name, logger=logger)
    logger.info("App %s/%s fully cleaned up", namespace, name)
