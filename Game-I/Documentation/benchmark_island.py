"""Windowed performance sample for Sentry's island and full power runtime."""

from __future__ import annotations
import argparse
import ctypes
import os
import statistics
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from main import build_game

def _memory_counters():
    class Counters(ctypes.Structure):
        _fields_=[("cb",ctypes.c_ulong),("PageFaultCount",ctypes.c_ulong),
          ("PeakWorkingSetSize",ctypes.c_size_t),("WorkingSetSize",ctypes.c_size_t),
          ("QuotaPeakPagedPoolUsage",ctypes.c_size_t),("QuotaPagedPoolUsage",ctypes.c_size_t),
          ("QuotaPeakNonPagedPoolUsage",ctypes.c_size_t),("QuotaNonPagedPoolUsage",ctypes.c_size_t),
          ("PagefileUsage",ctypes.c_size_t),("PeakPagefileUsage",ctypes.c_size_t)]
    counters=Counters(); counters.cb=ctypes.sizeof(counters)
    try:
        from ctypes import wintypes
        psapi=ctypes.WinDLL("psapi"); kernel=ctypes.WinDLL("kernel32")
        get_handle=kernel.GetCurrentProcess; get_handle.restype=wintypes.HANDLE
        get_info=psapi.GetProcessMemoryInfo
        get_info.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
        get_info.restype=wintypes.BOOL
        return int(counters.PeakWorkingSetSize) if get_info(get_handle(),ctypes.byref(counters),counters.cb) else 0
    except (AttributeError,OSError): return 0

def _cpu_time():
    class FileTime(ctypes.Structure):
        _fields_=[("low",ctypes.c_ulong),("high",ctypes.c_ulong)]
    try:
        from ctypes import wintypes
        kernel=ctypes.WinDLL("kernel32"); handle=kernel.GetCurrentProcess
        handle.restype=wintypes.HANDLE
        get_times=kernel.GetProcessTimes
        get_times.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(FileTime)]*4)]
        get_times.restype=wintypes.BOOL
        create,exit,kernel_time,user_time=(FileTime() for _ in range(4))
        if not get_times(handle(),ctypes.byref(create),ctypes.byref(exit),ctypes.byref(kernel_time),ctypes.byref(user_time)):
            return 0.0
        ticks=lambda value:(value.high<<32)|value.low
        return (ticks(kernel_time)+ticks(user_time))/10_000_000.0
    except (AttributeError,OSError): return 0.0

def _project_size():
    root=Path(__file__).resolve().parents[1]
    total=0
    for current,dirs,files in os.walk(root):
        dirs[:]=[name for name in dirs if name not in {".venv","__pycache__",".restore_original"}]
        for name in files:
            path=Path(current)/name
            if path.suffix.lower()==".zip" or path.suffix==".pyc": continue
            try: total+=path.stat().st_size
            except OSError: pass
    return total

def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--seconds",type=float,default=8.0)
    args=parser.parse_args()
    startup=time.perf_counter()
    app,game=build_game("onscreen")
    startup_seconds=time.perf_counter()-startup
    frames=[]; started=time.perf_counter(); cpu_start=_cpu_time()
    sample_start=started+1.0; end=started+max(3.0,args.seconds); last=started
    def sample(task):
        nonlocal last
        now=time.perf_counter()
        if now>=sample_start: frames.append((now-last)*1000.0)
        last=now
        if now>=end:
            duration=max(.001,now-sample_start)
            avg_fps=len(frames)/duration
            min_fps=(1000.0/max(frames)) if frames else 0.0
            mean_ms=statistics.mean(frames) if frames else 0.0
            cpu=max(0.0,_cpu_time()-cpu_start)
            cpu_pct=cpu/duration*100.0
            rss=_memory_counters()
            disk=_project_size()
            print(f"startup_s={startup_seconds:.2f} sample_s={duration:.2f} frames={len(frames)} "
                  f"avg_fps={avg_fps:.2f} min_fps={min_fps:.2f} mean_frame_ms={mean_ms:.2f} "
                  f"process_cpu_pct_one_core={cpu_pct:.1f} peak_working_set_mib={rss/1048576:.1f} "
                  f"project_source_mib={disk/1048576:.1f}",flush=True)
            app.userExit(); return task.done
        return task.cont
    app.taskMgr.add(sample,"sentry-island-benchmark")
    app.run()
    return 0

if __name__=="__main__": raise SystemExit(main())
