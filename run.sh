#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PORT="$(python3 - <<'PY'
import socket
for p in range(3010, 3100):
    s=socket.socket()
    try:
        s.bind(('127.0.0.1', p))
        print(p)
        break
    except OSError:
        pass
    finally:
        s.close()
else:
    raise SystemExit('No free port between 3010 and 3099')
PY
)"
exec python3 server.py --host 127.0.0.1 --port "$PORT"
