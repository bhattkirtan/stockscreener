#!/bin/bash
# Same as run_sweep.sh but never calls fetch_data (for instruments whose data is already fresh)
INST=$1; PAR=$2; OUT=$3; shift 3; shift
BT=/opt/stockscreener/trading-bot-skills/run_skills_backtest.py
cd /opt/stockscreener/trading-bot-skills
i=0
for spec in "$@"; do
  RID="${spec%%:*}"; ARGS="${spec#*:}"
  python3 $BT --instrument $INST --years 2 --results-dir $OUT --run-id $RID $ARGS > /tmp/sw_${INST}_${RID}.log 2>&1 &
  i=$((i+1)); [ $((i % PAR)) -eq 0 ] && wait
done
wait; echo "SWEEP_DONE $INST"
