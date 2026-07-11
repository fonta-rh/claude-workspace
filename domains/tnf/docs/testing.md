# Running openshift-tests on TNF

Running `openshift-tests run openshift/two-node` on a live TNF cluster requires:

1. **Build from source**: `make openshift-tests` in the origin repo
2. **Source proxy**: `source repos/two-node-toolbox/deploy/openshift-clusters/proxy.env`
3. **Stub extensions**: Baremetal payloads lack vsphere/ccm — compile ELF stub binaries (not shell scripts) into `~/.cache/openshift-tests/<release_hash>/`
4. **Hypervisor config**: `--with-hypervisor-json='{"hypervisorIP":"<EC2_PUBLIC_IP>","sshUser":"ec2-user","privateKeyPath":"~/.ssh/id_ed25519"}'`

## Critical Pitfall: --dry-run

`--dry-run` returns "no tests to run" because it skips cluster discovery. `DecodeProvider` returns a bare skeleton config with no feature gates, so `ClusterStateFilter` drops all `[OCPFeatureGate:DualReplica]` tests. Never use `--dry-run` with feature-gated suites.

## Patching resource-agents on Live Clusters

From the two-node-toolbox `deploy/` directory:

```bash
make patch-nodes    # Builds RPM from local source, deploys to all cluster nodes
```
