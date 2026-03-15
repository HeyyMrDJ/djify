"""
build.py — Image build logic for djify.

Responsibilities:
  - Resolve the current git SHA for a branch via `git ls-remote`
  - Create a Kubernetes batch Job that runs buildctl inside the cluster
  - Poll the Job until it succeeds or fails
  - Return the fully-qualified image reference on success
  - Tail the failed pod's log on failure and raise a kopf.PermanentError
"""

import asyncio
import datetime
import logging
import os
import subprocess
import time
from typing import Optional

import kopf
from kubernetes import client as k8s_client

log = logging.getLogger(__name__)

# Where buildkitd listens inside djify-system
BUILDKITD_ADDR = "tcp://buildkitd.djify-system.svc.cluster.local:1234"

# In-cluster registry address (used for both push destination and image pull)
REGISTRY_HOST = "registry.djify-system.svc.cluster.local:5000"

# Namespace for build Jobs
SYSTEM_NAMESPACE = "djify-system"

# How long to wait for a build Job to finish (seconds)
BUILD_TIMEOUT_SECONDS = 600

# Interval between Job status polls (seconds)
POLL_INTERVAL_SECONDS = 5


def resolve_git_sha(repo_url: str, branch: str) -> str:
    """
    Run `git ls-remote <repo_url> refs/heads/<branch>` locally and return
    the short (7-char) SHA.  Falls back to a UTC timestamp string if git
    is unavailable or the branch cannot be resolved (e.g. private repo
    without credentials configured locally).
    """
    try:
        result = subprocess.run(
            ["git", "ls-remote", repo_url, f"refs/heads/{branch}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            full_sha = result.stdout.strip().split()[0]
            return full_sha[:7]
    except Exception as exc:
        log.warning("git ls-remote failed (%s); falling back to timestamp tag", exc)

    # Fallback: UTC timestamp tag — still unique, just not linked to a commit
    return datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")


def build_job_manifest(
    app_name: str,
    namespace: str,
    repo_url: str,
    branch: str,
    dockerfile_path: str,
    image_ref: str,
    context_path: Optional[str] = None,
) -> dict:
    """
    Return a Kubernetes Job manifest dict that runs buildctl to build and
    push the image to the in-cluster registry.

    Context vs. Dockerfile path handling:
      - context_path=None (unset): legacy — derive context dir from dockerfile_path.
          dockerfilePath=app/Dockerfile → context=repo#branch:app, filename=Dockerfile
      - context_path="" (explicit empty): repo root as context.
          dockerfilePath=sample/Dockerfile → context=repo#branch, filename=sample/Dockerfile
      - context_path="subdir": explicit subdir as context.
          dockerfilePath=Dockerfile → context=repo#branch:subdir, filename=Dockerfile

    Examples:
      # Dockerfile at repo root (legacy or explicit)
      dockerfilePath=Dockerfile, contextPath=None or ""
        context  → repo.git#main
        filename → Dockerfile

      # Dockerfile in subdir, context = that subdir (legacy — contextPath omitted)
      dockerfilePath=app/Dockerfile, contextPath=None
        context  → repo.git#main:app
        filename → Dockerfile

      # Dockerfile in subdir, context = repo root (explicit contextPath="")
      dockerfilePath=sample/Dockerfile, contextPath=""
        context  → repo.git#main
        filename → sample/Dockerfile
    """
    job_name = f"djify-build-{app_name}"

    def _normalise(p: str) -> str:
        """Strip leading / and ./ from a path."""
        p = p.lstrip("/")
        if p.startswith("./"):
            p = p[2:]
        return p

    base_url = repo_url if repo_url.endswith(".git") else repo_url + ".git"
    normalised_dockerfile = _normalise(dockerfile_path)

    if context_path is None:
        # Legacy: derive context from the dockerfile directory
        dockerfile_dir = os.path.dirname(normalised_dockerfile)   # e.g. "app" or ""
        dockerfile_file = os.path.basename(normalised_dockerfile)  # e.g. "Dockerfile"
        git_context = f"{base_url}#{branch}:{dockerfile_dir}" if dockerfile_dir else f"{base_url}#{branch}"
    else:
        # Explicit context_path (including "" for repo root)
        ctx_dir = _normalise(context_path)
        dockerfile_file = normalised_dockerfile  # relative to context root
        git_context = f"{base_url}#{branch}:{ctx_dir}" if ctx_dir else f"{base_url}#{branch}"

    opts = [
        "--opt", f"context={git_context}",
        "--opt", f"filename={dockerfile_file}",
    ]

    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": job_name,
            "namespace": SYSTEM_NAMESPACE,
            "labels": {
                "app.kubernetes.io/managed-by": "djify",
                "djify.io/app-name": app_name,
                "djify.io/app-namespace": namespace,
            },
        },
        "spec": {
            # Keep finished Jobs around briefly so we can read logs on failure
            "ttlSecondsAfterFinished": 300,
            "backoffLimit": 0,
            "template": {
                "metadata": {
                    "labels": {
                        "app.kubernetes.io/managed-by": "djify",
                        "djify.io/app-name": app_name,
                        "djify.io/job-type": "build",
                    }
                },
                "spec": {
                    "restartPolicy": "Never",
                    "containers": [
                        {
                            "name": "buildctl",
                            "image": "moby/buildkit:latest",
                            "command": [
                                "buildctl",
                                "--addr", BUILDKITD_ADDR,
                                "build",
                                "--frontend", "dockerfile.v0",
                                *opts,
                                "--output",
                                (
                                    f"type=image,"
                                    f"name={image_ref},"
                                    f"push=true,"
                                    f"registry.insecure=true"
                                ),
                            ],
                        }
                    ],
                },
            },
        },
    }


async def _get_job_pod_log(batch_api, core_api, job_name: str) -> str:
    """Return the last 50 lines of the failed build pod's log, or empty string."""
    try:
        pods = core_api.list_namespaced_pod(
            namespace=SYSTEM_NAMESPACE,
            label_selector=f"job-name={job_name}",
        )
        if not pods.items:
            return ""
        pod_name = pods.items[0].metadata.name
        log_text = core_api.read_namespaced_pod_log(
            name=pod_name,
            namespace=SYSTEM_NAMESPACE,
            tail_lines=50,
        )
        return log_text
    except Exception as exc:
        log.warning("Could not fetch build pod log: %s", exc)
        return ""


async def run_build(
    app_name: str,
    namespace: str,
    repo_url: str,
    branch: str,
    dockerfile_path: str,
    logger: logging.Logger,
    context_path: Optional[str] = None,
) -> str:
    """
    Orchestrate a full image build:
      1. Resolve git SHA → image tag
      2. Delete any pre-existing Job with the same name (previous failed build)
      3. Create the build Job
      4. Poll until completion
      5. Return the image reference

    Raises kopf.PermanentError on build failure so kopf marks the handler
    as permanently failed (no automatic retry for a broken build).
    """
    batch_api = k8s_client.BatchV1Api()
    core_api = k8s_client.CoreV1Api()

    job_name = f"djify-build-{app_name}"
    sha = resolve_git_sha(repo_url, branch)
    image_ref = f"{REGISTRY_HOST}/{app_name}:{sha}"

    logger.info("Resolved image ref: %s", image_ref)

    # Clean up any pre-existing Job (e.g. from a previous failed build)
    _delete_job_if_exists(batch_api, job_name)

    # Create the Job
    manifest = build_job_manifest(
        app_name=app_name,
        namespace=namespace,
        repo_url=repo_url,
        branch=branch,
        dockerfile_path=dockerfile_path,
        image_ref=image_ref,
        context_path=context_path,
    )
    batch_api.create_namespaced_job(namespace=SYSTEM_NAMESPACE, body=manifest)
    logger.info("Build Job %s created in %s", job_name, SYSTEM_NAMESPACE)

    # Poll until the Job finishes or we time out
    elapsed = 0
    while elapsed < BUILD_TIMEOUT_SECONDS:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS

        try:
            job = batch_api.read_namespaced_job(
                name=job_name, namespace=SYSTEM_NAMESPACE
            )
        except k8s_client.exceptions.ApiException as exc:
            raise kopf.TemporaryError(f"Could not read Job {job_name}: {exc}", delay=10)

        conditions = job.status.conditions or []
        succeeded = job.status.succeeded or 0
        failed = job.status.failed or 0

        if succeeded >= 1:
            logger.info("Build Job %s succeeded", job_name)
            return image_ref

        if failed >= 1 or any(c.type == "Failed" for c in conditions):
            build_log = await _get_job_pod_log(batch_api, core_api, job_name)
            raise kopf.PermanentError(
                f"Build Job {job_name} failed.\n--- build log (last 50 lines) ---\n{build_log}"
            )

        logger.debug(
            "Build Job %s still running (elapsed %ds)...", job_name, elapsed
        )

    # Timed out
    raise kopf.PermanentError(
        f"Build Job {job_name} timed out after {BUILD_TIMEOUT_SECONDS}s."
    )


def _delete_job_if_exists(
    batch_api: k8s_client.BatchV1Api,
    job_name: str,
    wait_timeout: int = 60,
) -> None:
    """
    Delete a Job (and its pods) if it exists, then block until the Job is
    fully gone from the API.  Using Background propagation so the API
    server removes the Job object immediately and we can recreate it right
    away (pods are garbage-collected asynchronously).
    """
    try:
        batch_api.delete_namespaced_job(
            name=job_name,
            namespace=SYSTEM_NAMESPACE,
            body=k8s_client.V1DeleteOptions(propagation_policy="Background"),
        )
        log.info("Deleted pre-existing build Job %s; waiting for it to disappear", job_name)
    except k8s_client.exceptions.ApiException as exc:
        if exc.status == 404:
            return  # already gone — nothing to wait for
        log.warning("Could not delete Job %s: %s", job_name, exc)
        return

    # Poll until the Job object is gone (or we hit wait_timeout)
    deadline = time.monotonic() + wait_timeout
    while time.monotonic() < deadline:
        time.sleep(1)
        try:
            batch_api.read_namespaced_job(name=job_name, namespace=SYSTEM_NAMESPACE)
            # Still exists — keep waiting
        except k8s_client.exceptions.ApiException as exc:
            if exc.status == 404:
                log.info("Build Job %s fully deleted", job_name)
                return
            log.warning("Unexpected error while waiting for Job deletion: %s", exc)
            return

    log.warning("Timed out waiting for Job %s to be deleted; proceeding anyway", job_name)


def cleanup_build_job(app_name: str, logger: logging.Logger) -> None:
    """
    Synchronous cleanup of the build Job for app_name.
    Called from the delete handler.
    """
    batch_api = k8s_client.BatchV1Api()
    job_name = f"djify-build-{app_name}"
    _delete_job_if_exists(batch_api, job_name)
    logger.info("Cleaned up build Job for %s", app_name)
