#!/usr/bin/env python3
from __future__ import annotations
import platform, statistics, subprocess, sys, tempfile, time
from pathlib import Path
W=256; H=256; G=80; N=W*H; UPDATES=N*G; SAMPLES=5
HERE=Path(__file__).resolve().parent

def python_once():
    a=bytearray(N); b=bytearray(N)
    for r in range(H):
        row=r*W
        for c in range(W):
            i=row+c; a[i]=1 if (i*17+r*31+7)%11<5 else 0
    start=time.perf_counter_ns()
    for _ in range(G):
        for r in range(H):
            up=(H-1 if r==0 else r-1)*W; mid=r*W; down=(0 if r+1==H else r+1)*W
            for c in range(W):
                left=W-1 if c==0 else c-1; right=0 if c+1==W else c+1; i=mid+c
                n=(a[up+left]+a[up+c]+a[up+right]+a[mid+left]+a[mid+right]+a[down+left]+a[down+c]+a[down+right])
                alive=a[i]; b[i]=1 if n==3 or (alive and n==2) else 0
        a,b=b,a
    elapsed=time.perf_counter_ns()-start
    h=14695981039346656037
    for cell in a: h=((h^cell)*1099511628211)&0xffffffffffffffff
    return elapsed,f"{h:016x}"

def parse(out):
    p=out.strip().split()
    if len(p)!=3 or p[0]!="RESULT": raise RuntimeError(f"bad output: {out!r}")
    return int(p[1]),p[2]

def run(cmd):
    x=subprocess.run(cmd,check=True,text=True,capture_output=True)
    return parse(x.stdout)

def version(cmd):
    x=subprocess.run(cmd,check=True,text=True,capture_output=True)
    return (x.stdout or x.stderr).splitlines()[0]

def main():
    if sys.argv[1:]==["--python-once"]:
        ns,h=python_once(); print(f"RESULT {ns} {h}"); return
    print(f"Runner: {platform.platform()}")
    print(f"Python: {platform.python_version()} ({platform.python_implementation()})")
    print(f"C: {version(['cc','--version'])}")
    print(f"C++: {version(['c++','--version'])}")
    print(f"Rust: {version(['rustc','--version'])}")
    print(f"Workload: {W}x{H}, {G} generations, {UPDATES:,} cell updates; one warm-up + {SAMPLES} samples")
    with tempfile.TemporaryDirectory(prefix="capri-four-lang-") as tmp:
        d=Path(tmp); c=d/"life-c"; cpp=d/"life-cpp"; rust=d/"life-rust"
        builds=[
            ["cc","-O3","-march=native","-std=c17","-DNDEBUG",str(HERE/"life_c.c"),"-o",str(c)],
            ["c++","-O3","-march=native","-std=c++23","-DNDEBUG",str(HERE/"life_cpp.cpp"),"-o",str(cpp)],
            ["rustc","--edition=2024","-C","opt-level=3","-C","target-cpu=native",str(HERE/"life_rust.rs"),"-o",str(rust)]
        ]
        for cmd in builds: subprocess.run(cmd,check=True)
        runners={"C":[str(c)],"C++":[str(cpp)],"Rust":[str(rust)],"Python":[sys.executable,str(Path(__file__).resolve()),"--python-once"]}
        times={}; hashes={}
        for name,cmd in runners.items():
            run(cmd)
            values=[]; seen=set()
            for _ in range(SAMPLES):
                ns,h=parse(subprocess.run(cmd,check=True,text=True,capture_output=True).stdout)
                values.append(ns); seen.add(h)
            if len(seen)!=1: raise RuntimeError(f"{name} non-deterministic checksums: {seen}")
            times[name]=values; hashes[name]=seen.pop()
        if len(set(hashes.values()))!=1: raise RuntimeError(f"cross-language mismatch: {hashes}")
        med={k:statistics.median(v) for k,v in times.items()}; fastest=min(med.values())
        print(f"\nCorrectness: PASS, shared checksum {next(iter(hashes.values()))}")
        print("\nLanguage | Median ms | Cell updates/s | Relative to fastest")
        print("---|---:|---:|---:")
        for name in ("C","C++","Rust","Python"):
            ns=med[name]; print(f"{name} | {ns/1e6:.3f} | {UPDATES/(ns/1e9):,.0f} | {ns/fastest:.2f}x")
            print("  samples ms: "+", ".join(f"{v/1e6:.3f}" for v in times[name]))
        print("\nRelative runtime vs C:")
        for name in ("C++","Rust","Python"): print(f"{name}: {med[name]/med['C']:.2f}x")
        print("Benchmark completed successfully.")

if __name__=="__main__": main()
