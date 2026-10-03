from pathlib import Path
import json, subprocess, sys
root=Path(__file__).resolve().parent
required=['server.py','app.js','index.html','styles.css','render.yaml','Dockerfile','DEPLOY_COM.md','privacy.html','terms.html']
missing=[x for x in required if not (root/x).exists()]
if missing:
    print('MISSING:', ', '.join(missing)); sys.exit(1)
subprocess.run([sys.executable,'-m','py_compile','server.py'],check=True)
subprocess.run(['node','--check','app.js'],check=True)
print('SkillForge v8 preflight: PASS')
print('Files:', len(list(root.iterdir())))
