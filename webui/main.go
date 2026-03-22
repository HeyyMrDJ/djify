package main

import (
	"embed"
	"flag"
	"html/template"
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
	flag.Parse()

	// Build Kubernetes dynamic client
	client, err := djk8s.NewDynamicClient()
	if err != nil {
		log.Fatalf("failed to create Kubernetes client: %v", err)
	}

	// Parse all templates
	tmpl, err := template.ParseFS(assets, "templates/*.html")
	if err != nil {
		log.Fatalf("failed to parse templates: %v", err)
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
	mux.HandleFunc("GET /", handlers.ListApps(tmpl, client, *ns))

	// App detail
	mux.HandleFunc("GET /apps/{name}", handlers.GetApp(tmpl, client, *ns))

	// Create app — form page + submit
	mux.HandleFunc("GET /apps/new", handlers.CreateApp(tmpl, client, *ns))
	mux.HandleFunc("POST /apps", handlers.CreateApp(tmpl, client, *ns))

	// Delete app
	mux.HandleFunc("DELETE /apps/{name}", handlers.DeleteApp(tmpl, client, *ns))

	log.Printf("djify webui listening on %s (namespace=%s)", *addr, *ns)
	if err := http.ListenAndServe(*addr, mux); err != nil {
		log.Fatalf("server error: %v", err)
	}
}
