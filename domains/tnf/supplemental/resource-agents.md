# CLAUDE.md — resource-agents

## What This Repo Is

A collection of **OCF (Open Cluster Framework) resource agents** that Pacemaker uses to manage cluster resources. The TNF-relevant agent is `podman-etcd`, which manages etcd as a podman container under Pacemaker control.

**Upstream project**: ClusterLabs (same org as Pacemaker and fence-agents)
**Language**: Bash (OCF agents)
**License**: GPL-2.0+

## Key Paths for TNF

- `heartbeat/podman-etcd` — The OCF resource agent that manages etcd on TNF clusters
  - `start` — Starts etcd container via podman
  - `stop` — Stops etcd container, handles etcd member removal
  - `monitor` — Health checks (cert hash, `etcdctl endpoint health`)

## Coding Patterns

### File-based flags (`CONTAINER_HEARTBEAT_FILE` pattern)

The established pattern for file-based flags in podman-etcd (introduced by Carlo in commit `e8fb2ad9c`):
- Store flags in `$HA_RSCTMP` directory
- Clean the flag file at the **top of both start and stop** functions to avoid stale state across restarts
- Use the flag to communicate state between OCF actions (e.g., monitor detecting a condition that start/stop should act on)

### Testing changes on live clusters

```bash
# From two-node-toolbox deploy/ directory:
make patch-nodes    # Builds RPM from local source, deploys to all cluster nodes
```
