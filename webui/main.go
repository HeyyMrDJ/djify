package main

import (
	"embed"
	"flag"
	"io/fs"
	"log"
	"net/http"

	"djify/webui/handlers"
	djk8s "djify/webui/k8s"
)

//go:embed templates/* static/*
var assets embed.FS

func main() {
	addr := flag.String("addr", ":8080", "HTTP listen address")
	ns := flag.String("namespace", "default", "Kubernetes namespace to watch")
	domain := flag.String("domain", "djify.local", "Base domain for app ingress hostnames")
	flag.Parse()

	// Build Kubernetes dynamic client
	client, err := djk8s.NewDynamicClient()
	if err != nil {
		log.Fatalf("failed to create Kubernetes client: %v", err)
	}

	// Serve static files
	staticFS, err := fs.Sub(assets, "static")
	if err != nil {
		log.Fatalf("failed to sub static fs: %v", err)
	}

	mux := http.NewServeMux()

	// Static assets
	mux.Handle("GET /static/", http.StripPrefix("/static/", http.FileServer(http.FS(staticFS))))

	// App list (home)
	mux.HandleFunc("GET /", handlers.ListApps(assets, client, *ns))

	// App table fragment for HTMX polling
	mux.HandleFunc("GET /apps/table", handlers.ListAppsTable(assets, client, *ns))

	// App detail
	mux.HandleFunc("GET /apps/{name}", handlers.GetApp(assets, client, *ns, *domain))

	// Create app — form page + submit
	mux.HandleFunc("GET /apps/new", handlers.CreateApp(assets, client, *ns))
	mux.HandleFunc("POST /apps", handlers.CreateApp(assets, client, *ns))

	// Delete app
	mux.HandleFunc("DELETE /apps/{name}", handlers.DeleteApp(client, *ns))

	log.Printf("djify webui listening on %s (namespace=%s)", *addr, *ns)
	if err := http.ListenAndServe(*addr, mux); err != nil {
		log.Fatalf("server error: %v", err)
	}
}
