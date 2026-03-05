"""Fix run_deploy.sh: replace bad sed-injected ResourceQuota block with correct version."""
p = '/home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit/run_deploy.sh'
t = open(p).read()

# Remove the broken block injected by sed (the 5 bad lines)
bad_block = (
    '        # u2500u2500 Step 2.5b: Remove ResourceQuota (Lesson 34b u2014 CRITICAL) u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500u2500\n'
)

# Find and remove ALL bad injected lines (from "# u2500" to the blank echo before # Generate)
import re

# Replace the corrupted block with the correct one
old = r'        # u2500u2500 Step 2.5b.*?        echo ""\n        # Generate'
new = (
    '        # -- Step 2.5b: Remove ResourceQuota (Lesson 34b -- CRITICAL) --\n'
    "        echo \"[$(date '+%H:%M:%S')] Step 2.5b: Removing ResourceQuota (Lesson 34b)\"\n"
    "        kubectl delete resourcequota --all -n \"${K8S_NS}\" \\\n"
    "            --kubeconfig=\"${KUBECONFIG_PATH}\" --ignore-not-found=true 2>&1 || true\n"
    "        echo \"[$(date '+%H:%M:%S')] OK  Step 2.5b: ResourceQuota cleared\"\n"
    '        echo ""\n'
    '        # Generate'
)

t2 = re.sub(old, new, t, flags=re.DOTALL)
if t2 == t:
    print('WARN: bad block pattern not found — checking for partial match')
    # Try simpler approach: find the bad timestamp lines
    lines = t.split('\n')
    new_lines = []
    skip = False
    inserted = False
    for i, line in enumerate(lines):
        if 'u2500u2500 Step 2.5b' in line or ('Step 2.5b' in line and '14:51' in line):
            if not inserted:
                # Insert correct block
                new_lines.append("        # -- Step 2.5b: Remove ResourceQuota (Lesson 34b -- CRITICAL) --")
                new_lines.append("        echo \"[$(date '+%H:%M:%S')] Step 2.5b: Removing ResourceQuota (Lesson 34b)\"")
                new_lines.append("        kubectl delete resourcequota --all -n \"${K8S_NS}\" \\")
                new_lines.append("            --kubeconfig=\"${KUBECONFIG_PATH}\" --ignore-not-found=true 2>&1 || true")
                new_lines.append("        echo \"[$(date '+%H:%M:%S')] OK  Step 2.5b: ResourceQuota cleared\"")
                new_lines.append('        echo ""')
                inserted = True
            skip = True
            continue
        # Stop skipping after the second blank echo following the bad block
        if skip and line.strip() == '# Generate per-service manifests':
            skip = False
        if not skip:
            new_lines.append(line)
    t2 = '\n'.join(new_lines)
    if t2 != t:
        print('Fixed via line-by-line method')
    else:
        print('ERROR: could not fix file')

open(p, 'w').write(t2)
# Verify
if 'u2500' in open(p).read():
    print('ERROR: u2500 still present')
elif 'Step 2.5b' in open(p).read():
    print('OK: ResourceQuota step present and clean')
else:
    print('WARN: Step 2.5b not found in output')
