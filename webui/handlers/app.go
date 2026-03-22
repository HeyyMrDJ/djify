package handlers

import (
	"context"
	"html/template"
	"net/http"

	"k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/dynamic"
)

// GetApp handles GET /apps/{name} — renders the detail page.
func GetApp(tmpl *template.Template, client dynamic.Interface, namespace string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		name := r.PathValue("name")
		if name == "" {
			http.Error(w, "missing app name", http.StatusBadRequest)
			return
		}

		item, err := client.Resource(appGVR).Namespace(namespace).Get(context.Background(), name, metav1.GetOptions{})
		if err != nil {
			if errors.IsNotFound(err) {
				http.Error(w, "app not found: "+name, http.StatusNotFound)
				return
			}
			http.Error(w, "failed to get app: "+err.Error(), http.StatusInternalServerError)
			return
		}

		obj := item.Object
		detail := AppDetail{
			Name:           strField(obj, "metadata", "name"),
			Namespace:      strField(obj, "metadata", "namespace"),
			Phase:          strField(obj, "status", "phase"),
			Image:          strField(obj, "status", "image"),
			Message:        strField(obj, "status", "message"),
			LastBuildTime:  strField(obj, "status", "lastBuildTime"),
			Age:            humanAge(item.GetCreationTimestamp()),
			RepoURL:        strField(obj, "spec", "repoUrl"),
			Branch:         strField(obj, "spec", "branch"),
			DockerfilePath: strField(obj, "spec", "dockerfilePath"),
			ContextPath:    strField(obj, "spec", "contextPath"),
			Port:           int64Field(obj, "spec", "port"),
			Replicas:       int64Field(obj, "spec", "replicas"),
			IngressHost:    strField(obj, "spec", "ingressHost"),
		}

		if err := tmpl.ExecuteTemplate(w, "detail.html", detail); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
		}
	}
}
