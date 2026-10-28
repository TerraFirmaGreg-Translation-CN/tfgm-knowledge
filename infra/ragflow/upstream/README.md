# Upstream configuration provenance

Vendored from https://github.com/infiniflow/ragflow/tree/v1.0.0-rc2/docker:

- `service_conf.yaml.template`
- `init.sql`
- `kvrocks-entrypoint.sh`

These files retain upstream contents. The generated local service configuration appends bounded logging settings. `LICENSE` is the upstream Apache-2.0 license. The project manager adapts the upstream Compose dependencies to isolated, unexposed development services; it does not vendor the entire RAGFlow application.
