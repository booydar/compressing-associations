
#!/bin/sh
# Usage: bgrun.sh [VAR=val ...] ./path/to/script.sh
 
SCRIPT="${@: -1}"
VARS="${@:1:$#-1}"
 
LOG_BASE="${SCRIPT%.*}"
LOG="${LOG_BASE}.log"
i=1; while [ -f "$LOG" ]; do LOG="${LOG_BASE}.${i}.log"; i=$((i+1)); done
 
env $VARS nohup "$SCRIPT" > "$LOG" 2>&1 &
echo "PID=$! LOG=$LOG"