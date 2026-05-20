#!/bin/bash
# Launch M staggered copies of a target script and wait for all to finish.
# Use as cloudru --script (with TARGET env) or as a CLI command.
#
# Env:
#   M       number of copies         (default 4)
#   N       seconds between launches (default 60)
#   NP      passed to target as NP   (default 1)
#   TARGET  path to target script    (or pass as $1)
#
# Examples:
#   M=4 N=60 NP=1 ./bgrun_multi.sh ./run_X.sh
#   TARGET=./run_X.sh M=4 N=60 NP=1 cloudru jobs submit -f job.yaml --script ./bgrun_multi.sh
set -u

M=${M:-4}
N=${N:-60}
NP=${NP:-1}
TARGET="${TARGET:-${1:-}}"
if [ -z "$TARGET" ]; then
  echo "usage: M=.. N=.. NP=.. $0 ./target.sh   (or set TARGET env)" >&2
  exit 1
fi

LOG_BASE="${TARGET%.*}"
next_log() {
  local base="$1" log="${1}.log" i=1
  while [ -f "$log" ]; do log="${base}.${i}.log"; i=$((i+1)); done
  echo "$log"
}

pids=()
for i in $(seq 1 "$M"); do
  LOG=$(next_log "$LOG_BASE")
  NP="$NP" nohup "$TARGET" > "$LOG" 2>&1 &
  pid=$!
  pids+=("$pid")
  echo "[bgrun_multi $i/$M] PID=$pid LOG=$LOG"
  if [ "$i" -lt "$M" ]; then
    sleep "$N"
  fi
done

echo "[bgrun_multi] waiting on PIDs: ${pids[*]}"
wait "${pids[@]}"
echo "[bgrun_multi] all $M done"
