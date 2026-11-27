#!/usr/bin/env bash
# Bootstrap .toolchain: CPython 3.15 + SQLite >= 3.41 + zlib + libffi.
#
# System Python (3.11) and system SQLite (3.40.1) are older than the
# repository support policy (requires-python >=3.15,<3.16; Capri stores
# require SQLite >= 3.41 for json CHECK constraints). The system image has
# no dev headers (zlib/libffi/sqlite3.h), so this script builds the missing
# pieces from GitHub sources only (sandbox allowlist: github.com).
#
# Output:
#   .toolchain/py315/bin/python3     CPython 3.15 with bundled-capable deps
#   .toolchain/sqlite2/{include,lib} SQLite amalgamation (static)
#   .toolchain/zlib/{include,lib}    zlib
#   .toolchain/libffi/{include,lib}  libffi (only if the system lacks ffi.h)
#
# Usage:  scripts/bootstrap_toolchain.sh
# Re-run safe: existing verified builds are skipped.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$REPO_ROOT/.toolchain"
SRC="$ROOT/src"
JOBS="$(nproc 2>/dev/null || echo 2)"
mkdir -p "$SRC"

log() { printf '[toolchain] %s\n' "$*"; }

# ---------------------------------------------------------------- SQLite
# Note: FTS5/RTREE are intentionally NOT enabled - they pull libm symbols
# (log/pow) that break CPython's sqlite link probe, and Capri's schema
# uses neither (FTS5 was evaluated and rejected; all-terms search is
# implemented in Python).
SQLITE_LIB="$ROOT/sqlite2/lib/libsqlite3.a"
SQLITE_HDR="$ROOT/sqlite2/include/sqlite3.h"
if [ -f "$SQLITE_LIB" ] && [ -f "$SQLITE_HDR" ]; then
  log "sqlite2 already built, skipping"
else
  SQL_SRC="$SRC/sqlite"
  if [ ! -d "$SQL_SRC" ]; then
    log "cloning github.com/sqlite/sqlite"
    git clone --depth 1 https://github.com/sqlite/sqlite "$SQL_SRC"
  fi
  cd "$SQL_SRC"
  if [ -f configure ]; then
    log "configuring sqlite"
    ./configure >/dev/null 2>&1 || log "sqlite configure returned non-zero (continuing)"
  fi
  if ! make sqlite3.c >/dev/null 2>&1; then
    log "make sqlite3.c needs tclsh - building Tcl 9.1.0 first"
    TCL_SRC="$SRC/tcl"
    if [ ! -d "$TCL_SRC" ]; then
      git clone --depth 1 --branch core-9-1-0 https://github.com/tcltk/tcl "$TCL_SRC"
    fi
    cd "$TCL_SRC/unix"
    ./configure --prefix="$ROOT/tcl" >/dev/null
    make -j"$JOBS" >/dev/null
    make install >/dev/null
    export PATH="$ROOT/tcl/bin:$PATH"
    cd "$SQL_SRC"
    ./configure >/dev/null
    make sqlite3.c
  fi
  log "compiling sqlite amalgamation (no FTS5/RTREE: they need libm)"
  gcc -O2 -fPIC -DSQLITE_THREADSAFE=1 -c sqlite3.c -o sqlite3.o
  mkdir -p "$ROOT/sqlite2/include" "$ROOT/sqlite2/lib"
  ar rcs "$SQLITE_LIB" sqlite3.o
  cp sqlite3.h sqlite3ext.h "$ROOT/sqlite2/include/"
  log "sqlite2 ready: $(grep -o '#define SQLITE_VERSION[[:space:]]*"[^"]*"' "$ROOT/sqlite2/include/sqlite3.h" | grep -o '[0-9][0-9.]*')"
fi

# ----------------------------------------------------------------- zlib
if [ -f "$ROOT/zlib/include/zlib.h" ]; then
  log "zlib already built, skipping"
else
  Z_SRC="$SRC/zlib"
  if [ ! -d "$Z_SRC" ]; then
    log "cloning github.com/madler/zlib"
    git clone --depth 1 https://github.com/madler/zlib "$Z_SRC"
  fi
  cd "$Z_SRC"
  ./configure --prefix="$ROOT/zlib" >/dev/null
  make -j"$JOBS" >/dev/null
  make install >/dev/null
  log "zlib ready"
fi

# --------------------------------------------------------------- libffi
if [ -f /usr/include/ffi.h ] || [ -f /usr/include/x86_64-linux-gnu/ffi.h ]; then
  log "system ffi.h present, skipping libffi build"
  FFI_CPP=""
  FFI_LD=""
else
  if [ -f "$ROOT/libffi/include/ffi.h" ]; then
    log "libffi already built, skipping"
  else
    # Source with a pre-generated configure, from npm (registry.npmjs.org
    # is allowlisted; GitHub release assets redirect to a host that is
    # not). ffi-napi vendors deps/libffi including configure; the system
    # has no autotools to regenerate one from the upstream git tree.
    FFI_DIR="$SRC/ffi-napi-libffi"
    if [ ! -d "$FFI_DIR/src" ]; then
      log "packing ffi-napi from npm for vendored libffi"
      mkdir -p "$FFI_DIR"
      (cd "$SRC" && npm pack ffi-napi@4.0.3 --silent)
      tar xzf "$SRC"/ffi-napi-*.tgz -C "$FFI_DIR" package/deps/libffi
      mv "$FFI_DIR/package/deps/libffi" "$FFI_DIR/src"
      rm -rf "$FFI_DIR/package"
    fi
    cd "$FFI_DIR/src"
    ./configure --prefix="$ROOT/libffi" --disable-docs >/dev/null
    make -j"$JOBS" >/dev/null
    make install >/dev/null
    log "libffi ready"
  fi
  FFI_CPP="-I$ROOT/libffi/include"
  FFI_LD="-L$ROOT/libffi/lib"
fi

# ------------------------------------------------------------- CPython
PY="$ROOT/py315/bin/python3"
if [ -x "$PY" ] && "$PY" -c "import sqlite3, zlib, ctypes, zipfile" >/dev/null 2>&1; then
  log "py315 already built and verified, skipping"
else
  CPY_SRC="$SRC/cpython"
  if [ ! -d "$CPY_SRC" ]; then
    log "cloning github.com/python/cpython branch 3.15"
    git clone --depth 1 --branch 3.15 https://github.com/python/cpython "$CPY_SRC"
  fi
  cd "$CPY_SRC"
  export CPPFLAGS="-I$ROOT/sqlite2/include -I$ROOT/zlib/include ${FFI_CPP}"
  export LDFLAGS="-L$ROOT/sqlite2/lib -L$ROOT/zlib/lib ${FFI_LD}"
  export LD_LIBRARY_PATH="$ROOT/sqlite2/lib:$ROOT/zlib/lib${FFI_LD:+:$ROOT/libffi/lib}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  log "configuring cpython (official CPPFLAGS/LDFLAGS, ensurepip on)"
  ./configure --prefix="$ROOT/py315" --disable-test-modules >/dev/null
  log "building cpython with $JOBS jobs (several minutes)"
  make -j"$JOBS"
  make install >/dev/null
  log "cpython installed"
fi

# ------------------------------------------------------------- Verify
"$PY" - <<'EOF'
import ctypes
import sqlite3
import sys
import zipfile
import zlib

assert sys.version_info[:2] == (3, 15), sys.version
assert sqlite3.sqlite_version_info >= (3, 41), sqlite3.sqlite_version
print(
    f"[toolchain] OK python={sys.version.split()[0]} "
    f"sqlite={sqlite3.sqlite_version} zlib={zlib.ZLIB_VERSION}"
)
EOF
log "done: $PY"
