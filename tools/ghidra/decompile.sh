#!/bin/sh
# Headless Ghidra wrapper for the Denon x86 tools.
#   tools/ghidra/decompile.sh import <tool.exe>                one-time import + auto-analysis
#   tools/ghidra/decompile.sh dec <tool.exe> <out.c> <addr>..  decompile functions at addresses
#   tools/ghidra/decompile.sh xrefs <tool.exe> <out.txt> <addr>..  references to addresses
# Project lives in build/ghidra (git-ignored). Needs GHIDRA and JAVA_HOME (defaults below).
set -e
GHIDRA=${GHIDRA:-$HOME/.local/opt/ghidra_12.2_PUBLIC}
JAVA_HOME=${JAVA_HOME:-$HOME/.local/opt/jdk-25.0.5+8/Contents/Home}
export JAVA_HOME PATH="$JAVA_HOME/bin:$PATH"
HERE=$(cd "$(dirname "$0")" && pwd)
PROJ=$(cd "$HERE/../.." && pwd)/build/ghidra
mkdir -p "$PROJ"
cmd=$1; exe=$2; shift 2
name=$(basename "$exe")
case $cmd in
  import)
    "$GHIDRA/support/analyzeHeadless" "$PROJ" denon -import "$exe" -overwrite 2>&1 | grep -E 'INFO  (IMPORTING|ANALYZING|REPORT)|ERROR|WARN.*fail' || true ;;
  dec)
    out=$1; shift
    "$GHIDRA/support/analyzeHeadless" "$PROJ" denon -process "$name" -noanalysis -readOnly \
      -scriptPath "$HERE" -postScript DecompileAt.java "$out" "$@" 2>&1 | grep -E 'ERROR|Exception' || true
    echo "$out: $(grep -c '^// =====' "$out") function(s)" ;;
  xrefs)
    out=$1; shift
    "$GHIDRA/support/analyzeHeadless" "$PROJ" denon -process "$name" -noanalysis -readOnly \
      -scriptPath "$HERE" -postScript XrefsTo.java "$out" "$@" 2>&1 | grep -E 'ERROR|Exception' || true
    cat "$out" ;;
  *) sed -n '2,6p' "$0"; exit 2 ;;
esac
