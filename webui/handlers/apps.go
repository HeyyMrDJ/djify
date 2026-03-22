package handlers

import (
	"context"
	"fmt"
	"html/template"
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

// ListApps handles GET / — renders the app list.
func ListApps(tmpl *template.Template, client dynamic.Interface, namespace string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		list, err := client.Resource(appGVR).Namespace(namespace).List(context.Background(), metav1.ListOptions{})
		if err != nil {
			http.Error(w, "failed to list apps: "+err.Error(), http.StatusInternalServerError)
			return
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

		if err := tmpl.ExecuteTemplate(w, "index.html", apps); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
		}
	}
}
