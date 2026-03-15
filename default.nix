{
  pkgs,
  lib,
  venv,
}:
let
  controller = pkgs.runCommand "djify-controller-src" { } ''
    mkdir -p $out/app
    cp -r ${./controller}/. $out/app/
  '';
in
pkgs.dockerTools.buildLayeredImage {
  name = "djify";
  tag = "latest";
  contents = [
    venv
    controller
    pkgs.cacert
  ];
  config = {
    Entrypoint = [
      "${venv}/bin/kopf"
      "run"
      "/app/main.py"
    ];
    Cmd = [
      "--namespace=default"
      "--log-format=plain"
    ];
    WorkingDir = "/app";
    Env = [ "PYTHONUNBUFFERED=1" ];
  };
}
