"""Short, local-only polling benchmark. Reports no friend data or credentials."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import statistics
import subprocess
import time
import app


def client_cpu():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    total = 0
    for pid in CLIENT_PIDS:
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            continue
        times = [wintypes.FILETIME() for _ in range(4)]
        if kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            total += sum((t.dwHighDateTime << 32) + t.dwLowDateTime for t in times[2:]) / 10_000_000
        kernel.CloseHandle(handle)
    return total


if __name__ == '__main__':
    output = subprocess.check_output(['powershell', '-NoProfile', '-Command',
        "@(Get-Process RiotClientServices,RiotClientUx,RiotClientUxRender -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id) | ConvertTo-Json -Compress"],
        creationflags=subprocess.CREATE_NO_WINDOW, text=True)
    ids = json.loads(output or '[]')
    CLIENT_PIDS = ids if isinstance(ids, list) else [ids]
    port, password = app.get_lcu_connection()
    if port is None:
        raise SystemExit('Client unavailable')
    session = app.requests.Session()
    session.trust_env = False
    app.fetch_presences(port, password, session=session)
    results = []
    for name, interval, reuse in [('idle', None, True), ('old_0.10', .10, False),
                                  ('pooled_0.25', .25, True), ('pooled_0.10', .10, True),
                                  ('pooled_0.05', .05, True), ('pooled_0.01', .01, True)]:
        client_before, own_before = client_cpu(), time.process_time()
        start = time.perf_counter()
        durations, errors = [], 0
        while time.perf_counter() - start < 4:
            if interval is None:
                time.sleep(4)
                break
            began = time.perf_counter()
            try:
                app.fetch_presences(port, password, session=session if reuse else None)
            except Exception:
                errors += 1
            durations.append((time.perf_counter() - began) * 1000)
            time.sleep(max(0, interval - (time.perf_counter() - began)))
        wall = time.perf_counter() - start
        result = {'mode': name, 'seconds': round(wall, 3), 'requests': len(durations),
                  'requests_per_second': round(len(durations)/wall, 2), 'errors': errors,
                  'median_ms': round(statistics.median(durations), 2) if durations else None,
                  'own_cpu_one_core_percent': round((time.process_time()-own_before)/wall*100, 2),
                  'riot_cpu_one_core_percent': round((client_cpu()-client_before)/wall*100, 2)}
        results.append(result)
        print(json.dumps(result), flush=True)
    Path('benchmark-results.json').write_text(json.dumps({'logical_cpus': os.cpu_count(), 'results': results}, indent=2))
    session.close()
