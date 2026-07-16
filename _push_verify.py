#!/usr/bin/env python3
"""Push and verify all experiment work."""
import subprocess, json, pathlib

root = pathlib.Path(r'C:\Users\casey\.openclaw\workspace\tzpro-agent')
results = {}

# 1. Git status
r = subprocess.run(['git', 'status', '--short'], capture_output=True, text=True, cwd=root)
results['status'] = r.stdout.strip()

# 2. Git add + commit + push
r = subprocess.run(['git', 'add', 'experiment_*.md', 'run_experiments.py', '_experiment_logs/'], capture_output=True, text=True, cwd=root)
r = subprocess.run(['git', 'commit', '-m', 'Experiment designs: Florence-2 VL, forward-look sonar, multi-model comparison'], capture_output=True, text=True, cwd=root)
results['commit'] = r.stdout.strip()[:200]
r = subprocess.run(['git', 'push'], capture_output=True, text=True, cwd=root)
results['push'] = r.stdout.strip()[:200] if r.stdout else r.stderr.strip()[:200]

# 3. List experiment files
results['experiments'] = [str(f.relative_to(root)) for f in sorted(root.glob('experiment_*.md'))]

# 4. List experiment logs
log_dir = root / '_experiment_logs'
if log_dir.exists():
    results['logs'] = [str(f.relative_to(root)) for f in sorted(log_dir.glob('*.json'))]

# 5. List recent experiment runner files  
results['runners'] = [str(f.relative_to(root)) for f in sorted(root.glob('run_experiments*.py'))]

pathlib.Path(r'C:\Users\casey\.openclaw\workspace\tzpro-agent\_push_verify.json').write_text(json.dumps(results, indent=2))
print(json.dumps(results, indent=2))
