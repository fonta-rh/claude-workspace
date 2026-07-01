# TNF CI Infrastructure

## Build Farm Registry Auth

To pull images from CI build farm registries (`registry.build{NN}.ci.openshift.org`), three things are needed in `config_fencing.sh`:

1. `CI_SERVER` → `api.build{NN}.ci.devcluster.openshift.com`
2. `CI_TOKEN` → token from the build farm's own console
3. `pull-secret.json` → `user:<token>` base64-encoded entry for `registry.build{NN}.ci.openshift.org`

**Key facts:**
- The central CI token (`apps.ci.l2s4.p1.openshiftapps.com`) does NOT work for build farm registries
- Build farm console URL: `https://console-openshift-console.apps.build{NN}.ci.devcluster.openshift.com/`
- Build farm API hostname: `api.build{NN}.ci.devcluster.openshift.com` (NOT `api.build{NN}.ci.openshift.org`)
- Registry hostname: `registry.build{NN}.ci.openshift.org` (different domain from API)
- `CI_SERVER` is needed so `write_pull_secret()` in dev-scripts runs `oc registry login` against the right cluster to generate a proper registry bearer token
- Tokens are short-lived (~24-48h)

## GCS Artifact Access (Prow Logs)

gcsweb-ci (`gcsweb-ci.apps.ci.l2s4.p1.openshiftapps.com`) serves HTML wrappers for all files. To download raw content, use the GCS JSON API:

```bash
# Pattern: URL-encode the object path, use alt=media
curl -sL "https://storage.googleapis.com/storage/v1/b/test-platform-results/o/<URL_ENCODED_PATH>?alt=media" -o output.txt

# Example: build log
JOB="periodic-ci-openshift-release-main-nightly-4.22-e2e-metal-ovn-two-node-fencing-ipv6-recovery-techpreview"
curl -sL "https://storage.googleapis.com/storage/v1/b/test-platform-results/o/logs%2F${JOB}%2F${RUN_ID}%2Fbuild-log.txt?alt=media"

# Example: list objects under a prefix
curl -sL "https://storage.googleapis.com/storage/v1/b/test-platform-results/o?prefix=logs%2F${JOB}%2F${RUN_ID}%2F&delimiter=/&maxResults=50"
```

`gsutil` requires `storage.objects.list` permission on the `test-platform-results` bucket, which most Red Hat accounts don't have. Use the JSON API instead.
