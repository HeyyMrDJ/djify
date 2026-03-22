package handlers

import (
	"context"
	"fmt"
	"html/template"
	"io/fs"
	"net/http"
	"time"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/client-go/dynamic"
)

var appGVR = schema.GroupVersionResource{
	Group:    "djify.io",
	Version:  "v1alpha1",
	Resource: "apps",
}

// AppSummary holds the fields shown in the app list.
type AppSummary struct {
	Name      string
	Namespace string
	Phase     string
	Image     string
	Age       string
}

// AppDetail holds all fields shown on the detail page.
type AppDetail struct {
	Name           string
	Namespace      string
	Phase          string
	Image          string
	Message        string
	LastBuildTime  string
	Age            string
	RepoURL        string
	Branch         string
	DockerfilePath string
	ContextPath    string
	Port           int64
	Replicas       int64
	IngressHost    string
	Domain         string
}

func strField(obj map[string]interface{}, keys ...string) string {
	cur := obj
	for i, k := range keys {
		v, ok := cur[k]
		if !ok {
			return ""
		}
		if i == len(keys)-1 {
			s, _ := v.(string)
			return s
		}
		cur, ok = v.(map[string]interface{})
		if !ok {
			return ""
		}
	}
	return ""
}

func int64Field(obj map[string]interface{}, keys ...string) int64 {
	cur := obj
	for i, k := range keys {
		v, ok := cur[k]
		if !ok {
			return 0
		}
		if i == len(keys)-1 {
			switch n := v.(type) {
			case int64:
				return n
			case float64:
				return int64(n)
			}
			return 0
		}
		cur, ok = v.(map[string]interface{})
		if !ok {
			return 0
		}
	}
	return 0
}

func humanAge(creationTime metav1.Time) string {
	d := time.Since(creationTime.Time).Round(time.Second)
	if d < time.Minute {
		return d.String()
	}
	if d < time.Hour {
		m := int(d.Minutes())
		return formatPlural(m, "minute")
	}
	if d < 24*time.Hour {
		h := int(d.Hours())
		return formatPlural(h, "hour")
	}
	days := int(d.Hours() / 24)
	return formatPlural(days, "day")
}

func formatPlural(n int, unit string) string {
	if n == 1 {
		return fmt.Sprintf("1 %s", unit)
	}
	return fmt.Sprintf("%d %ss", n, unit)
}

// mustParse parses base.html + the named page file from the embedded FS.
// Each call produces an isolated template set with no shared {{define}} blocks.
func mustParse(assets fs.FS, page string) *template.Template {
	tmpl, err := template.ParseFS(assets, "templates/base.html", "templates/"+page)
	if err != nil {
		panic("failed to parse templates: " + err.Error())
	}
	return tmpl
}

// listApps fetches the current app list from the cluster.
func listApps(client dynamic.Interface, namespace string) ([]AppSummary, error) {
	list, err := client.Resource(appGVR).Namespace(namespace).List(context.Background(), metav1.ListOptions{})
	if err != nil {
		return nil, err
	}
	var apps []AppSummary
	for _, item := range list.Items {
		obj := item.Object
		apps = append(apps, AppSummary{
			Name:      strField(obj, "metadata", "name"),
			Namespace: strField(obj, "metadata", "namespace"),
			Phase:     strField(obj, "status", "phase"),
			Image:     strField(obj, "status", "image"),
			Age:       humanAge(item.GetCreationTimestamp()),
		})
	}
	return apps, nil
}

// ListApps handles GET / — renders the full page app list.
func ListApps(assets fs.FS, client dynamic.Interface, namespace string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		apps, err := listApps(client, namespace)
		if err != nil {
			http.Error(w, "failed to list apps: "+err.Error(), http.StatusInternalServerError)
			return
		}
		tmpl := mustParse(assets, "index.html")
		if err := tmpl.ExecuteTemplate(w, "base", apps); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
		}
	}
}

// ListAppsTable handles GET /apps/table — renders only the table fragment for HTMX polling.
func ListAppsTable(assets fs.FS, client dynamic.Interface, namespace string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		apps, err := listApps(client, namespace)
		if err != nil {
			http.Error(w, "failed to list apps: "+err.Error(), http.StatusInternalServerError)
			return
		}
		tmpl := mustParse(assets, "index.html")
		if err := tmpl.ExecuteTemplate(w, "app-table", apps); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
		}
	}
}
