package handlers

import (
	"context"
	"fmt"
	"io/fs"
	"net/http"
	"strconv"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/client-go/dynamic"
)

// CreateApp handles GET /apps/new (form) and POST /apps (submit).
func CreateApp(assets fs.FS, client dynamic.Interface, namespace string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet {
			tmpl := mustParse(assets, "create.html")
			if err := tmpl.ExecuteTemplate(w, "base", nil); err != nil {
				http.Error(w, err.Error(), http.StatusInternalServerError)
			}
			return
		}

		// POST — parse form and create App CR
		if err := r.ParseForm(); err != nil {
			http.Error(w, "invalid form: "+err.Error(), http.StatusBadRequest)
			return
		}

		name := r.FormValue("name")
		repoURL := r.FormValue("repoUrl")
		portStr := r.FormValue("port")

		if name == "" || repoURL == "" || portStr == "" {
			http.Error(w, "name, repoUrl, and port are required", http.StatusBadRequest)
			return
		}

		port, err := strconv.ParseInt(portStr, 10, 64)
		if err != nil || port < 1 || port > 65535 {
			http.Error(w, fmt.Sprintf("invalid port %q", portStr), http.StatusBadRequest)
			return
		}

		spec := map[string]interface{}{
			"repoUrl":  repoURL,
			"port":     port,
			"replicas": int64(1),
		}

		if v := r.FormValue("branch"); v != "" {
			spec["branch"] = v
		}
		if v := r.FormValue("dockerfilePath"); v != "" {
			spec["dockerfilePath"] = v
		}
		if v := r.FormValue("contextPath"); v != "" {
			spec["contextPath"] = v
		}

		obj := &unstructured.Unstructured{
			Object: map[string]interface{}{
				"apiVersion": "djify.io/v1alpha1",
				"kind":       "App",
				"metadata": map[string]interface{}{
					"name":      name,
					"namespace": namespace,
				},
				"spec": spec,
			},
		}

		_, err = client.Resource(appGVR).Namespace(namespace).Create(
			context.Background(), obj, metav1.CreateOptions{},
		)
		if err != nil {
			http.Error(w, "failed to create app: "+err.Error(), http.StatusInternalServerError)
			return
		}

		http.Redirect(w, r, "/", http.StatusSeeOther)
	}
}
