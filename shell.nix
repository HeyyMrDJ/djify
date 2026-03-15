{ pkgs, lib }:
let
  scripts = pkgs.callPackage ./devx.nix { };
in
pkgs.mkShell {
  packages =
    with pkgs;
    [
      python312
      uv
      kubectl
      kind
    ]
    ++ scripts;

  shellHook = ''
    export UV_PROJECT_ENVIRONMENT=$(pwd)/.venv
    cat <<EOF

    djify dev shell ready
      Python : $(python3 --version)
      uv     : $(uv --version)

    Run 'djify-help' to see available commands.
    EOF
  '';
}
