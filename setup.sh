#!/bin/bash
#
# Dev Environment Setup Script
# ============================
#
# Usage:
#   ./setup.sh              # Clone all repos (first time setup)
#   ./setup.sh clone        # Clone all repos
#   ./setup.sh update       # Update all repos (git pull)
#   ./setup.sh clone <dir>  # Clone specific repo by directory name
#   ./setup.sh update <dir> # Update specific repo by directory name
#   ./setup.sh status       # Show status of all repos
#   ./setup.sh list         # List configured repos
#   ./setup.sh init <name>            # Initialize from a bundled domain
#   ./setup.sh init <url>             # Initialize from an external domain git URL
#   ./setup.sh init <url#subdir>      # External pack repo containing multiple domains
#   ./setup.sh refresh-domain         # Re-fetch domain from its recorded source
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOS_DIR="$SCRIPT_DIR/repos"
DEV_ENV_YAML="$SCRIPT_DIR/dev-env.yaml"
DEV_ENV_TEMPLATE="$SCRIPT_DIR/dev-env.yaml.template"
DOMAINS_DIR="$SCRIPT_DIR/domains"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ─── YAML Parsing ─────────────────────────────────────────────────────────────
# Parse dev-env.yaml into pipe-separated lines: url|directory|branch|name|category|summary
# Uses yq if available, falls back to python3 with PyYAML.

parse_yaml_repos() {
    local yaml_file="$1"

    if command -v yq &>/dev/null; then
        yq -r '.repos[] | [.url, (.directory // .name), .branch, .name, .category, .summary] | join("|")' "$yaml_file" 2>/dev/null
        return $?
    fi

    if python3 -c "import yaml" 2>/dev/null; then
        python3 -c "
import yaml, sys
with open('$yaml_file') as f:
    data = yaml.safe_load(f)
for r in data.get('repos', []):
    print('|'.join([
        r.get('url',''), r.get('directory', r.get('name','')), r.get('branch','main'),
        r.get('name',''), r.get('category',''), r.get('summary','')
    ]))
" 2>/dev/null
        return $?
    fi

    log_error "Cannot parse dev-env.yaml: no YAML parser available."
    log_info "Install one of the following:"
    log_info "  yq          — https://github.com/mikefarah/yq"
    log_info "  python3-pyyaml — dnf install python3-pyyaml  (or pip install pyyaml)"
    return 1
}

# Read the domain: block from dev-env.yaml.
# Outputs: name|source|ref|subdir (empty string for missing fields)
parse_yaml_domain() {
    local yaml_file="${1:-$DEV_ENV_YAML}"

    if python3 -c "import yaml" 2>/dev/null; then
        python3 -c "
import yaml
with open('$yaml_file') as f:
    data = yaml.safe_load(f)
p = data.get('domain', {})
if isinstance(p, str):
    p = {'name': p, 'source': 'bundled'}
elif not isinstance(p, dict):
    p = {}
print('|'.join([
    p.get('name',''), p.get('source','bundled'), p.get('ref',''), p.get('subdir','')
]))
" 2>/dev/null
        return 0
    fi

    if command -v yq &>/dev/null; then
        local name source ref subdir
        name=$(yq -r '(.domain.name // .domain) // ""' "$yaml_file" 2>/dev/null)
        source=$(yq -r '.domain.source // "bundled"' "$yaml_file" 2>/dev/null)
        ref=$(yq -r '.domain.ref // ""' "$yaml_file" 2>/dev/null)
        subdir=$(yq -r '.domain.subdir // ""' "$yaml_file" 2>/dev/null)
        echo "${name}|${source}|${ref}|${subdir}"
        return 0
    fi

    echo "|||"
}

# ─── Repo Source Detection ────────────────────────────────────────────────────
# Verifies dev-env.yaml exists, sets REPO_SOURCE and ACTIVE_DOMAIN_NAME.

REPO_SOURCE=""
ACTIVE_DOMAIN_NAME=""

detect_repo_source() {
    if [[ -f "$DEV_ENV_YAML" ]]; then
        REPO_SOURCE="$DEV_ENV_YAML"
        local domain_info
        domain_info=$(parse_yaml_domain "$DEV_ENV_YAML")
        ACTIVE_DOMAIN_NAME="${domain_info%%|*}"
    else
        log_error "No repo configuration found!"
        log_info "Options:"
        log_info "  ./setup.sh init <domain>  — Initialize from a bundled domain"
        log_info "  ./setup.sh init <url>     — Initialize from an external domain git URL"
        log_info "  cp dev-env.yaml.template dev-env.yaml  — Start from template"
        exit 1
    fi
}

# ─── Line Iteration ──────────────────────────────────────────────────────────
# Iterates over repos from dev-env.yaml, calling a callback with:
#   url, dir, branch (set as globals for backward compat)

iterate_repos() {
    local callback="$1"

    while IFS='|' read -r url dir branch _name _cat _summary; do
        if [[ -z "$url" || -z "$dir" ]]; then
            [[ -n "$_name" || -n "$url" ]] && log_warn "Skipping entry with missing url or name: ${_name:-${url:-unknown}}"
            continue
        fi
        "$callback"
    done < <(parse_yaml_repos "$REPO_SOURCE")
}

# ─── Clone / Update ──────────────────────────────────────────────────────────

# Clone a single repository (blobless clone for faster downloads)
clone_repo() {
    local url="$1"
    local dir="$2"
    local branch="$3"

    local target="$REPOS_DIR/$dir"

    if [[ -d "$target/.git" ]]; then
        log_warn "$dir already exists, skipping (use 'update' to pull)"
        return 0
    fi

    mkdir -p "$REPOS_DIR"

    log_info "Cloning $dir (blobless)..."
    git clone --filter=blob:none --branch "$branch" "$url" "$target"
    log_success "Cloned $dir (branch: $branch)"

    # Distribute context/supplemental files from the active domain only.
    # Scoping to the active domain prevents collisions when multiple installed
    # domains contain files for a same-named repository.
    if [[ -n "$ACTIVE_DOMAIN_NAME" && -d "$DOMAINS_DIR/$ACTIVE_DOMAIN_NAME" ]]; then
        local domain_base="$DOMAINS_DIR/$ACTIVE_DOMAIN_NAME"

        if [[ -f "$domain_base/context/$dir.md" ]]; then
            cp "$domain_base/context/$dir.md" "$target/DOMAIN-CONTEXT.md"
            log_info "  Added DOMAIN-CONTEXT.md"
        fi

        if [[ ! -f "$target/CLAUDE.md" && -f "$domain_base/supplemental/$dir.md" ]]; then
            cp "$domain_base/supplemental/$dir.md" "$target/CLAUDE.md"
            log_info "  Added supplemental CLAUDE.md"
        fi
    else
        # Fallback for dev-env.yaml files that predate source tracking
        for ctx in "$DOMAINS_DIR"/*/context/"$dir".md; do
            if [[ -f "$ctx" ]]; then
                cp "$ctx" "$target/DOMAIN-CONTEXT.md"
                log_info "  Added DOMAIN-CONTEXT.md"
                break
            fi
        done

        if [[ ! -f "$target/CLAUDE.md" ]]; then
            for sup in "$DOMAINS_DIR"/*/supplemental/"$dir".md; do
                if [[ -f "$sup" ]]; then
                    cp "$sup" "$target/CLAUDE.md"
                    log_info "  Added supplemental CLAUDE.md"
                    break
                fi
            done
        fi
    fi
}

# Update a single repository
update_repo() {
    local dir="$1"
    local target="$REPOS_DIR/$dir"

    if [[ ! -d "$target/.git" ]]; then
        log_warn "$dir not cloned yet, skipping"
        return 0
    fi

    log_info "Updating $dir..."

    cd "$target"

    if ! git diff --quiet HEAD 2>/dev/null; then
        log_warn "  $dir has local changes, stashing..."
        git stash
    fi

    git pull --rebase
    cd "$SCRIPT_DIR"

    log_success "Updated $dir"
}

# Clone all repositories
clone_all() {
    log_info "Cloning all repositories..."
    echo

    _clone_callback() {
        clone_repo "$url" "$dir" "$branch"
    }
    iterate_repos _clone_callback

    echo
    log_success "All repositories cloned!"
}

# Update all repositories
update_all() {
    log_info "Updating all repositories..."
    echo

    _update_callback() {
        if [[ -d "$REPOS_DIR/$dir/.git" ]]; then
            update_repo "$dir"
        fi
    }
    iterate_repos _update_callback

    echo
    log_success "All repositories updated!"
}

# Clone or update a specific repo
handle_specific_repo() {
    local action="$1"
    local target_dir="$2"
    local found=false

    _find_callback() {
        if [[ "$dir" == "$target_dir" ]]; then
            found=true
            if [[ "$action" == "clone" ]]; then
                clone_repo "$url" "$dir" "$branch"
            else
                update_repo "$dir"
            fi
        fi
    }
    iterate_repos _find_callback

    if [[ "$found" == "false" ]]; then
        log_error "Repository '$target_dir' not found in $REPO_SOURCE"
        echo "Available repositories:"
        list_repos
        exit 1
    fi
}

# ─── Status / List ───────────────────────────────────────────────────────────

# Show status of all repos
show_status() {
    log_info "Repository status:"
    echo
    printf "%-30s %-12s %-20s %s\n" "DIRECTORY" "STATUS" "BRANCH" "LAST COMMIT"
    printf "%-30s %-12s %-20s %s\n" "---------" "------" "------" "-----------"

    _status_callback() {
        local target="$REPOS_DIR/$dir"
        local status branch_info last_commit

        if [[ -d "$target/.git" ]]; then
            cd "$target"
            status="${GREEN}cloned${NC}"
            branch_info="$(git branch --show-current 2>/dev/null || echo 'detached')"
            last_commit="$(git log -1 --format='%h %s' 2>/dev/null | cut -c1-40)"
            cd "$REPOS_DIR"
        else
            status="${YELLOW}not cloned${NC}"
            branch_info="-"
            last_commit="-"
        fi

        printf "%-30s $(echo -e $status)%-1s %-20s %s\n" "$dir" "" "$branch_info" "$last_commit"
    }
    iterate_repos _status_callback
}

# List configured repos
list_repos() {
    echo
    printf "%-30s %-10s %-50s %-12s\n" "DIRECTORY" "CATEGORY" "URL" "BRANCH"
    printf "%-30s %-10s %-50s %-12s\n" "---------" "--------" "---" "------"

    while IFS='|' read -r url dir branch name cat summary; do
        [[ -z "$url" ]] && continue
        local short_url="${url#https://github.com/}"
        printf "%-30s %-10s %-50s %-12s\n" "$dir" "$cat" "$short_url" "$branch"
    done < <(parse_yaml_repos "$REPO_SOURCE")
}

# ─── Domain Validation ────────────────────────────────────────────────────────

# Validate that a directory has the required domain layout.
# Returns non-zero and prints errors if validation fails.
validate_domain() {
    local domain_dir="$1"
    local source="${2:-$domain_dir}"
    local errors=0

    if [[ ! -f "$domain_dir/domain.yaml" ]]; then
        log_error "Missing domain.yaml in: $source"
        errors=$((errors + 1))
    fi

    if [[ ! -f "$domain_dir/dev-env.yaml" ]]; then
        log_error "Missing dev-env.yaml in: $source"
        log_info "  A valid domain must contain:"
        log_info "    domain.yaml              — name, description, metadata"
        log_info "    dev-env.yaml             — list of repos to clone"
        log_info "    context/<repo>.md        — (optional) per-repo context files"
        log_info "    supplemental/<repo>.md   — (optional) fallback CLAUDE.md for repos"
        log_info "    docs/                    — (optional) architecture / debugging docs"
        log_info "    settings.local.json.tpl  — (optional) Claude Code settings template"
        errors=$((errors + 1))
    fi

    if [[ $errors -gt 0 ]]; then
        return 1
    fi
    return 0
}

# Read the name field from a domain directory's domain.yaml
get_domain_name_from_dir() {
    local domain_dir="$1"

    if python3 -c "import yaml" 2>/dev/null; then
        python3 -c "
import yaml
with open('$domain_dir/domain.yaml') as f:
    data = yaml.safe_load(f)
print(data.get('name', ''))
" 2>/dev/null
        return 0
    fi

    if command -v yq &>/dev/null; then
        yq -r '.name // ""' "$domain_dir/domain.yaml" 2>/dev/null
        return 0
    fi

    grep '^name:' "$domain_dir/domain.yaml" | sed 's/^name: *//;s/"//g' | head -1
}

# ─── URL Detection ────────────────────────────────────────────────────────────

# Returns 0 if the argument looks like a git URL (before any #fragment)
is_git_url() {
    local url="${1%%#*}"
    [[ "$url" == https://* || "$url" == git@* || "$url" == ssh://* || \
       "$url" == git://* || "$url" == file://* || "$url" == *.git ]]
}

# ─── External Domain Fetching ─────────────────────────────────────────────────

# Clone an external domain pack into domains/<name>/.
# Sets FETCHED_DOMAIN_NAME to the installed domain name.
FETCHED_DOMAIN_NAME=""

fetch_external_domain() {
    local raw_url="$1"
    local url="${raw_url%%#*}"
    local subdir=""
    [[ "$raw_url" == *"#"* ]] && subdir="${raw_url##*#}"

    local tmp_dir
    tmp_dir=$(mktemp -d)

    log_info "Fetching domain from $url ..."
    if ! git clone --depth 1 "$url" "$tmp_dir/pack"; then
        rm -rf "$tmp_dir"
        log_error "Failed to clone $url"
        exit 1
    fi

    local pack_dir="$tmp_dir/pack"
    if [[ -n "$subdir" ]]; then
        pack_dir="$tmp_dir/pack/$subdir"
        if [[ ! -d "$pack_dir" ]]; then
            rm -rf "$tmp_dir"
            log_error "Subdirectory '$subdir' not found in $url"
            log_info "Directories available in the pack repo:"
            ls "$tmp_dir/pack/" 2>/dev/null | grep -v '^\.' | sed 's/^/  /' || true
            exit 1
        fi
    fi

    if ! validate_domain "$pack_dir" "$raw_url"; then
        rm -rf "$tmp_dir"
        exit 1
    fi

    local domain_name
    domain_name=$(get_domain_name_from_dir "$pack_dir")
    if [[ -z "$domain_name" ]]; then
        domain_name="${subdir:-$(basename "${url%.git}")}"
    fi

    local dest="$DOMAINS_DIR/$domain_name"
    if [[ -d "$dest" ]]; then
        log_warn "Domain '$domain_name' already installed at domains/$domain_name/"
        read -rp "Overwrite? [y/N] " answer
        if [[ "$answer" != "y" && "$answer" != "Y" ]]; then
            rm -rf "$tmp_dir"
            log_info "Aborted."
            exit 0
        fi
        rm -rf "$dest"
    fi

    mkdir -p "$dest"
    cp -r "$pack_dir/." "$dest/"
    rm -rf "$dest/.git"

    # Record in local git exclude so the external domain is not tracked by this repo
    local exclude_file="$SCRIPT_DIR/.git/info/exclude"
    if [[ -f "$exclude_file" ]]; then
        local ignore_pattern="domains/$domain_name/"
        if ! grep -qF "$ignore_pattern" "$exclude_file" 2>/dev/null; then
            echo "$ignore_pattern" >> "$exclude_file"
        fi
    fi

    rm -rf "$tmp_dir"
    log_success "Installed domain '$domain_name' from $url"
    FETCHED_DOMAIN_NAME="$domain_name"
}

# ─── Domain Source Recording ─────────────────────────────────────────────────

# Inject or replace the domain: block in a dev-env.yaml file.
# Uses a regex replace so comments in the rest of the file are preserved.
record_domain_source() {
    local yaml_file="$1"
    local name="$2"
    local source="$3"   # 'bundled' or the git URL
    local ref="${4:-}"
    local subdir="${5:-}"

    if ! python3 -c "import sys" 2>/dev/null; then
        log_warn "python3 not available — domain source not recorded in dev-env.yaml"
        return 0
    fi

    python3 - "$yaml_file" "$name" "$source" "$ref" "$subdir" << 'PYEOF'
import re, sys
yaml_file, name, source, ref, subdir = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]

with open(yaml_file) as f:
    text = f.read()

lines = ['domain:', f'  name: {name}', f'  source: {source}']
if ref:
    lines.append(f'  ref: {ref}')
if subdir:
    lines.append(f'  subdir: {subdir}')
block = '\n'.join(lines)

# Replace an existing domain key — handles both scalar (domain: <name>) and
# mapping (domain:\n  name: <name>\n  ...) forms.
new_text = re.sub(
    r'^domain:[^\n]*(?:\n[ \t]+[^\n]*)*',
    block,
    text,
    count=1,
    flags=re.MULTILINE
)

# If no domain: key existed, prepend the block
if not re.search(r'^domain:', new_text, re.MULTILINE):
    new_text = block + '\n\n' + text

with open(yaml_file, 'w') as f:
    f.write(new_text)
PYEOF
}

# ─── Settings Merge ──────────────────────────────────────────────────────────
# Merge a settings template into an existing settings.local.json.
# Adds missing top-level keys (e.g. hooks) and appends new permissions.allow
# entries without overwriting existing values.

merge_settings_template() {
    local target="$1"
    local template="$2"

    if ! python3 -c "import json" 2>/dev/null; then
        log_warn "python3 not available — cannot merge settings template"
        return 0
    fi

    local result
    result=$(python3 - "$target" "$template" << 'PYEOF'
import json, sys

target_path, template_path = sys.argv[1], sys.argv[2]

with open(target_path) as f:
    target = json.load(f)
with open(template_path) as f:
    template = json.load(f)

changed = []

# Merge permissions.allow: append entries not already present
if "permissions" in template and "allow" in template["permissions"]:
    target.setdefault("permissions", {}).setdefault("allow", [])
    existing = set(target["permissions"]["allow"])
    for entry in template["permissions"]["allow"]:
        if entry not in existing:
            target["permissions"]["allow"].append(entry)
            changed.append(f"  + permission: {entry}")

# Merge top-level keys that don't exist in target (hooks, env, etc.)
for key in template:
    if key == "permissions":
        continue
    if key not in target:
        target[key] = template[key]
        changed.append(f"  + {key}")

if changed:
    with open(target_path, "w") as f:
        json.dump(target, f, indent=2)
        f.write("\n")
    print("\n".join(changed))
else:
    print("__NO_CHANGES__")
PYEOF
    )

    if [[ "$result" == "__NO_CHANGES__" ]]; then
        log_success ".claude/settings.local.json already up to date"
    else
        log_success "Merged template into .claude/settings.local.json:"
        echo "$result"
    fi
}

# ─── Init from Domain ────────────────────────────────────────────────────────

init_domain() {
    local domain_name_or_url="$1"

    if [[ -z "$domain_name_or_url" ]]; then
        log_info "Available domains:"
        echo
        for domain_dir in "$DOMAINS_DIR"/*/; do
            [[ ! -d "$domain_dir" ]] && continue
            local name
            name="$(basename "$domain_dir")"
            local desc=""
            if [[ -f "$domain_dir/domain.yaml" ]]; then
                desc=$(grep '^description:' "$domain_dir/domain.yaml" | sed 's/^description: *"*//;s/"*$//')
            fi
            printf "  %-15s %s\n" "$name" "$desc"
        done
        echo
        log_info "Usage:"
        log_info "  ./setup.sh init <domain-name>         Bundled domain"
        log_info "  ./setup.sh init <url>                 External domain git URL"
        log_info "  ./setup.sh init <url#subdir>          Domain pack with multiple domains"
        exit 0
    fi

    local domain_name
    local source_type="bundled"
    local source_subdir=""

    if is_git_url "$domain_name_or_url"; then
        # External domain: fetch from git, then continue with the installed copy
        [[ "$domain_name_or_url" == *"#"* ]] && source_subdir="${domain_name_or_url##*#}"
        fetch_external_domain "$domain_name_or_url"
        domain_name="$FETCHED_DOMAIN_NAME"
        source_type="${domain_name_or_url%%#*}"   # store URL without fragment
    else
        domain_name="$domain_name_or_url"
    fi

    local domain_dir="$DOMAINS_DIR/$domain_name"
    if [[ ! -d "$domain_dir" ]]; then
        log_error "Domain '$domain_name' not found in $DOMAINS_DIR/"
        log_info "Available domains:"
        for d in "$DOMAINS_DIR"/*/; do
            [[ -d "$d" ]] && echo "  $(basename "$d")"
        done
        exit 1
    fi

    if ! validate_domain "$domain_dir"; then
        exit 1
    fi

    if [[ -f "$DEV_ENV_YAML" ]]; then
        log_warn "dev-env.yaml already exists"
        read -rp "Overwrite? [y/N] " answer
        [[ "$answer" != "y" && "$answer" != "Y" ]] && { log_info "Aborted."; exit 0; }
    fi

    cp "$domain_dir/dev-env.yaml" "$DEV_ENV_YAML"
    log_success "Initialized dev-env.yaml from domain '$domain_name'"

    # Record where this domain came from so refresh-domain can re-fetch it
    record_domain_source "$DEV_ENV_YAML" "$domain_name" "$source_type" "" "$source_subdir"

    local settings_dir="$SCRIPT_DIR/.claude"
    local settings_file="$settings_dir/settings.local.json"
    local settings_tpl=""
    if [[ -f "$domain_dir/settings.local.json.tpl" ]]; then
        settings_tpl="$domain_dir/settings.local.json.tpl"
    elif [[ -f "$SCRIPT_DIR/settings.local.json.tpl" ]]; then
        settings_tpl="$SCRIPT_DIR/settings.local.json.tpl"
    fi

    if [[ -z "$settings_tpl" ]]; then
        : # no template available
    elif [[ ! -f "$settings_file" ]]; then
        mkdir -p "$settings_dir"
        cp "$settings_tpl" "$settings_file"
        log_success "Created .claude/settings.local.json from template"
    else
        merge_settings_template "$settings_file" "$settings_tpl"
    fi

    echo
    log_info "Next steps:"
    log_info "  ./setup.sh clone    — Clone all repositories"
    log_info "  ./setup.sh status   — Check repo status"
}

# ─── Refresh Domain ──────────────────────────────────────────────────────────

refresh_domain() {
    if [[ ! -f "$DEV_ENV_YAML" ]]; then
        log_error "No dev-env.yaml found. Run './setup.sh init' first."
        exit 1
    fi

    local domain_info
    domain_info=$(parse_yaml_domain "$DEV_ENV_YAML")
    local domain_name source ref subdir
    IFS='|' read -r domain_name source ref subdir <<< "$domain_info"

    if [[ -z "$domain_name" ]]; then
        log_error "No domain recorded in dev-env.yaml."
        log_info "Re-run './setup.sh init <domain>' to initialize with source tracking."
        exit 1
    fi

    log_info "Refreshing domain '$domain_name' (source: $source)"

    if [[ "$source" == "bundled" ]]; then
        local domain_dir="$DOMAINS_DIR/$domain_name"
        if [[ ! -d "$domain_dir" ]]; then
            log_error "Bundled domain '$domain_name' not found at domains/$domain_name/"
            exit 1
        fi
        if ! validate_domain "$domain_dir"; then
            exit 1
        fi
    else
        # Re-fetch from git URL (source holds the URL, subdir holds the fragment path)
        local raw_url="$source"
        [[ -n "$subdir" ]] && raw_url="${source}#${subdir}"
        fetch_external_domain "$raw_url"
        domain_name="$FETCHED_DOMAIN_NAME"
    fi

    local domain_dir="$DOMAINS_DIR/$domain_name"

    log_warn "This will overwrite dev-env.yaml with the refreshed domain."
    read -rp "Continue? [y/N] " answer
    [[ "$answer" != "y" && "$answer" != "Y" ]] && { log_info "Aborted."; exit 0; }

    cp "$domain_dir/dev-env.yaml" "$DEV_ENV_YAML"
    record_domain_source "$DEV_ENV_YAML" "$domain_name" "$source" "$ref" "$subdir"

    log_success "Domain '$domain_name' refreshed."
    log_info "Run './setup.sh clone' to clone any newly added repositories."
}

# ─── Usage ────────────────────────────────────────────────────────────────────

usage() {
    echo "Dev Environment Setup Script"
    echo
    echo "Usage:"
    echo "  ./setup.sh              Clone all repos (first time setup)"
    echo "  ./setup.sh clone        Clone all repos"
    echo "  ./setup.sh update       Update all repos (git pull)"
    echo "  ./setup.sh clone <dir>  Clone specific repo by directory name"
    echo "  ./setup.sh update <dir> Update specific repo by directory name"
    echo "  ./setup.sh status       Show status of all repos"
    echo "  ./setup.sh list         List configured repos"
    echo "  ./setup.sh init <name>  Initialize from a bundled domain"
    echo "  ./setup.sh init <url>   Initialize from an external domain git URL"
    echo "  ./setup.sh init <url#subdir>  External pack containing multiple domains"
    echo "  ./setup.sh refresh-domain     Re-fetch domain from its recorded source"
    echo "  ./setup.sh help         Show this help"
    echo
    echo "Configuration:"
    echo "  dev-env.yaml — repo manifest (gitignored, generated by 'init')"
    echo
    echo "Domains:"
    echo "  Run './setup.sh init' (no args) to list available bundled domains."
    echo "  External domains are fetched from git and installed into domains/<name>/."
    echo
    echo "Notes:"
    echo "  All repos are cloned with --filter=blob:none (blobless)."
    echo "  Full structure is visible, blobs fetched on-demand."
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
    local action="${1:-clone}"
    local target="${2:-}"

    case "$action" in
        init)
            init_domain "$target"
            ;;
        refresh-domain)
            refresh_domain
            ;;
        clone)
            detect_repo_source
            if [[ -n "$target" ]]; then
                handle_specific_repo "clone" "$target"
            else
                clone_all
            fi
            ;;
        update)
            detect_repo_source
            if [[ -n "$target" ]]; then
                handle_specific_repo "update" "$target"
            else
                update_all
            fi
            ;;
        status)
            detect_repo_source
            show_status
            ;;
        list)
            detect_repo_source
            list_repos
            ;;
        help|--help|-h)
            usage
            ;;
        *)
            log_error "Unknown action: $action"
            usage
            exit 1
            ;;
    esac
}

main "$@"
