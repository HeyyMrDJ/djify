package handlers

import (
	"context"
	"net/http"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/dynamic"
)

// DeleteApp handles DELETE /apps/{name} — deletes the App CR and returns an
// empty 200 so HTMX removes the row from the DOM.
func DeleteApp(client dynamic.Interface, namespace string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		name := r.PathValue("name")
		if name == "" {
			http.Error(w, "missing app name", http.StatusBadRequest)
			return
		}

		err := client.Resource(appGVR).Namespace(namespace).Delete(
			context.Background(), name, metav1.DeleteOptions{},
		)
		if err != nil {
			http.Error(w, "failed to delete app: "+err.Error(), http.StatusInternalServerError)
			return
		}

		// HTMX swap: return empty body so the row is removed via hx-swap="outerHTML"
		w.WriteHeader(http.StatusOK)
	}
}
