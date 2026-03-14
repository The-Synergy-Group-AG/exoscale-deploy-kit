#!/usr/bin/env python3
import json

d = json.load(open('/home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit/outputs/test_results_rerun_20260306.json'))
s = d['summary']
print("=== Summary ===")
print(json.dumps(s, indent=2))

print("\n=== First 3 services detail ===")
results = d['results'][:3]
for r in results:
    print(f"\nService: {r.get('service')}")
    print(f"Status: {r.get('overall_status')}")
    for suite in r.get('suites', []):
        status = suite.get('status')
        passed = suite.get('passed')
        failed = suite.get('failed')
        output = suite.get('output', '')[:120]
        print(f"  Suite {suite.get('suite'):20} status={status:15} passed={passed} failed={failed}")
        if output:
            print(f"    output: {output}")

print("\n=== Status breakdown across all suites ===")
from collections import Counter
suite_statuses = Counter()
for r in d['results']:
    for suite in r.get('suites', []):
        suite_statuses[suite.get('status')] += 1
print(suite_statuses)
