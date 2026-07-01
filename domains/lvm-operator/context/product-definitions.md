<!-- Supplemental context for LVM Operator dev environment. Repo's native CLAUDE.md (if any) takes priority. -->

# product-definitions — LVMS Context

**Category**: Deployment

**Purpose**: Product Security (ProdSec) repository that defines Red Hat product metadata — versions, update streams, and module definitions that gate official releases.

**LVMS Relevance**: LVMS must have entries in this repo before any version can be officially released. This is the "gatekeeper" for version approvals.

**Important**: This is a GitLab repo (`gitlab.cee.redhat.com`) — requires VPN access.

**Key concepts**:
- **ps_products**: Product definitions (e.g., "LVM Storage" product entry)
- **ps_update_streams**: Version streams that map to release branches (e.g., LVMS 4.16, 4.17)
- **ps_modules**: Module definitions that map products to specific build components

**Key LVMS paths**:
- `data/openshift/ps_products.json` — Top-level product definitions
  - `ps_products.lvms-operator` — JSON path to the operator product definition
- `data/openshift/ps_update_streams.json` — Version and CPE information for products
  - `ps_update_streams.lvms-operator-*` — JSON path (regex) to LVMS version definitions
- `data/openshift/ps_modules.json` — Module version definitions for OpenShift products
  - `ps_modules.lvms-operator-4` — JSON path to the LVMS v4 module versions

**Common tasks**:
- Adding a new LVMS version stream (required before each new OCP release)
- Verifying that LVMS product definitions match current component names
- Checking which OCP versions have approved LVMS releases
- Debugging release pipeline failures caused by missing product definitions

**Workflow**:
1. Before a new LVMS version ships, ProdSec must approve the product definition
2. An MR (merge request) is submitted to add/update entries in the relevant JSON files
3. ProdSec reviews and merges the MR
4. The release pipeline can then proceed with the approved version
