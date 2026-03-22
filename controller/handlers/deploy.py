"""
deploy.py — Workload deployment logic for djify.

Responsibilities:
  - Create or update a Deployment, Service, and Ingress for each App CR
  - All child resources are created in the same namespace as the App CR
  - Resources are labelled with the App name so they can be cleaned up
  - The Ingress class defaults to "traefik" (k3s) but can be overridden via
    the DJIFY_INGRESS_CLASS environment variable (e.g. "nginx" for kind)
  - Host pattern: <appname>.djify.local (or spec.ingressHost if provided)
"""

import logging
import os

from kubernetes import client as k8s_client
from kubernetes.client.rest import ApiException

log = logging.getLogger(__name__)

# Field manager name used for patch calls
FIELD_MANAGER = "djify-controller"

# Ingress class — "traefik" for k3s, "nginx" for kind/ingress-nginx.
# Override via DJIFY_INGRESS_CLASS environment variable.
INGRESS_CLASS = os.environ.get("DJIFY_INGRESS_CLASS", "traefik")


def _labels(app_name: str) -> dict:
    return {
        "app.kubernetes.io/name": app_name,
        "app.kubernetes.io/managed-by": "djify",
        "djify.io/app": app_name,
    }


def _deployment_manifest(
    app_name: str,
    namespace: str,
    image_ref: str,
    port: int,
    replicas: int,
) -> dict:
    labels = _labels(app_name)
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": app_name,
            "namespace": namespace,
            "labels": labels,
        },
        "spec": {
            "replicas": replicas,
            "selector": {"matchLabels": {"djify.io/app": app_name}},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "containers": [
                        {
                            "name": app_name,
                            "image": image_ref,
                            "ports": [{"containerPort": port}],
                            "imagePullPolicy": "Always",
                        }
                    ]
                },
            },
        },
    }


def _service_manifest(app_name: str, namespace: str, port: int) -> dict:
    labels = _labels(app_name)
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": app_name,
            "namespace": namespace,
            "labels": labels,
        },
        "spec": {
            "selector": {"djify.io/app": app_name},
            "ports": [
                {
                    "name": "http",
                    "port": 80,
                    "targetPort": port,
                }
            ],
            "type": "ClusterIP",
        },
    }


def _ingress_manifest(app_name: str, namespace: str, host: str) -> dict:
    labels = _labels(app_name)
    annotations = (
        {"traefik.ingress.kubernetes.io/router.entrypoints": "web"}
        if INGRESS_CLASS == "traefik"
        else {}
    )
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {
            "name": app_name,
            "namespace": namespace,
            "labels": labels,
            "annotations": annotations,
        },
        "spec": {
            "ingressClassName": INGRESS_CLASS,
            "rules": [
                {
                    "host": host,
                    "http": {
                        "paths": [
                            {
                                "path": "/",
                                "pathType": "Prefix",
                                "backend": {
                                    "service": {
                                        "name": app_name,
                                        "port": {"number": 80},
                                    }
                                },
                            }
                        ]
                    },
                }
            ],
        },
    }


def _apply_resource(
    create_fn,
    patch_fn,
    namespace: str,
    name: str,
    body: dict,
    kind: str,
    logger: logging.Logger,
) -> None:
    """
    Apply a resource: strategic-merge-patch if it exists, create if it doesn't.

    This is a plain create-or-update that works with all versions of the
    kubernetes Python client — no _content_type or SSA quirks.
    """
    try:
        patch_fn(name=name, namespace=namespace, body=body, field_manager=FIELD_MANAGER)
        logger.info("%s %s/%s updated", kind, namespace, name)
    except ApiException as exc:
        if exc.status == 404:
            create_fn(namespace=namespace, body=body)
            logger.info("%s %s/%s created", kind, namespace, name)
        else:
            raise


def apply_workload(
    app_name: str,
    namespace: str,
    image_ref: str,
    port: int,
    replicas: int,
    ingress_host: str,
    logger: logging.Logger,
) -> None:
    """
    Create or update the Deployment, Service, and Ingress for an App.
    Safe to call on both create and update events.
    """
    apps_api = k8s_client.AppsV1Api()
    core_api = k8s_client.CoreV1Api()
    net_api = k8s_client.NetworkingV1Api()

    _apply_resource(
        apps_api.create_namespaced_deployment,
        apps_api.patch_namespaced_deployment,
        namespace, app_name,
        _deployment_manifest(app_name, namespace, image_ref, port, replicas),
        "Deployment", logger,
    )

    _apply_resource(
        core_api.create_namespaced_service,
        core_api.patch_namespaced_service,
        namespace, app_name,
        _service_manifest(app_name, namespace, port),
        "Service", logger,
    )

    _apply_resource(
        net_api.create_namespaced_ingress,
        net_api.patch_namespaced_ingress,
        namespace, app_name,
        _ingress_manifest(app_name, namespace, ingress_host),
        "Ingress", logger,
    )

    logger.info("Workload ready at http://%s", ingress_host)


def delete_workload(app_name: str, namespace: str, logger: logging.Logger) -> None:
    """
    Delete the Deployment, Service, and Ingress for an App.
    Errors for resources that do not exist (404) are silently ignored.
    """
    apps_api = k8s_client.AppsV1Api()
    core_api = k8s_client.CoreV1Api()
    net_api = k8s_client.NetworkingV1Api()
    delete_opts = k8s_client.V1DeleteOptions(propagation_policy="Foreground")

    for kind, fn in [
        ("Ingress", lambda: net_api.delete_namespaced_ingress(app_name, namespace, body=delete_opts)),
        ("Service", lambda: core_api.delete_namespaced_service(app_name, namespace, body=delete_opts)),
        ("Deployment", lambda: apps_api.delete_namespaced_deployment(app_name, namespace, body=delete_opts)),
    ]:
        try:
            fn()
            logger.info("Deleted %s %s/%s", kind, namespace, app_name)
        except ApiException as exc:
            if exc.status != 404:
                logger.warning("Could not delete %s %s/%s: %s", kind, namespace, app_name, exc)
