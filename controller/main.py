"""
main.py — djify controller entrypoint.

Run locally with:
  kopf run controller/main.py --namespace=default --dev

Run in-cluster (see deploy/controller.yaml):
  kopf run /app/main.py --namespace=default
"""

# Import handlers — kopf discovers decorators on import
import handlers.app  # noqa: F401
