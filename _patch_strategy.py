"""Inject rolling strategy into gen_service_manifests.py YAML template."""
p = '/home/iandre/projects/jtp-bio-v3/exoscale-deploy-kit/gen_service_manifests.py'
t = open(p).read()
old = '  replicas: 1\n  selector:'
new = (
    '  replicas: 1\n'
    '  strategy:\n'
    '    type: RollingUpdate\n'
    '    rollingUpdate:\n'
    '      maxUnavailable: 1\n'
    '      maxSurge: 0\n'
    '  selector:'
)
if old not in t:
    print('SKIP: strategy already injected or pattern not found')
else:
    t2 = t.replace(old, new, 1)
    open(p, 'w').write(t2)
    print('strategy_injected OK')
