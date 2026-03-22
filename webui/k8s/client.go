// Package k8s provides a Kubernetes dynamic client configured from the local
// kubeconfig (~/.kube/config or $KUBECONFIG) with an automatic fallback to
// in-cluster service-account credentials when running inside a Pod.
package k8s

import (
	"fmt"
	"os"
	"path/filepath"

	"k8s.io/client-go/dynamic"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"
)

// NewDynamicClient returns a dynamic client using the best available config:
//  1. $KUBECONFIG env var
//  2. ~/.kube/config
//  3. In-cluster service account (when running as a Pod)
func NewDynamicClient() (dynamic.Interface, error) {
	cfg, err := loadConfig()
	if err != nil {
		return nil, fmt.Errorf("build kubeconfig: %w", err)
	}
	client, err := dynamic.NewForConfig(cfg)
	if err != nil {
		return nil, fmt.Errorf("create dynamic client: %w", err)
	}
	return client, nil
}

func loadConfig() (*rest.Config, error) {
	// Explicit kubeconfig path via env var
	if kc := os.Getenv("KUBECONFIG"); kc != "" {
		return clientcmd.BuildConfigFromFlags("", kc)
	}

	// Default ~/.kube/config
	if home, err := os.UserHomeDir(); err == nil {
		p := filepath.Join(home, ".kube", "config")
		if _, err := os.Stat(p); err == nil {
			return clientcmd.BuildConfigFromFlags("", p)
		}
	}

	// In-cluster fallback
	return rest.InClusterConfig()
}
