# NeuroCI — OPA Rego Policy
#
# Declarative policy rules that control when NeuroCI is allowed
# to create automated pull requests. Version-controlled in Git.
#
# Usage: OPA evaluates this policy before any PR is created.
# Result: { "result": true/false }

package neuroci

import rego.v1

default allow := false

# ═══════════════════════════════════════════════════════════
# Main allow rule — all conditions must pass
# ═══════════════════════════════════════════════════════════
allow if {
    not restricted_path
    not excessive_patch
    branch_confidence_ok
    category_allowed
}

# ═══════════════════════════════════════════════════════════
# Rule: Restricted file paths — never auto-patch
# ═══════════════════════════════════════════════════════════
restricted_path if {
    some path in input.restricted_paths
    startswith(input.target_file, path)
}

restricted_path if {
    some path in input.restricted_paths
    endswith(input.target_file, path)
}

# ═══════════════════════════════════════════════════════════
# Rule: Patch size limit
# ═══════════════════════════════════════════════════════════
excessive_patch if {
    input.lines_changed > 20
}

# ═══════════════════════════════════════════════════════════
# Rule: Branch-specific confidence thresholds
# ═══════════════════════════════════════════════════════════
branch_confidence_ok if {
    input.branch == "main"
    input.confidence >= 0.92
}

branch_confidence_ok if {
    input.branch != "main"
    input.confidence >= 0.5
}

# ═══════════════════════════════════════════════════════════
# Rule: Category restrictions
# ═══════════════════════════════════════════════════════════
category_allowed if {
    not input.category in blocked_categories
}

blocked_categories := {
    "AuthError",
    "NetworkTimeout",
    "FlakyTest",
    "Unknown"
}
