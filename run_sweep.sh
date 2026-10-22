#!/bin/bash
# Usage: run_sweep.sh <instrument> <parallel> <outroot> -- "runid:--set a=b --set c=d" ...
INST=$1; PAR=$2; OUT=$3; shift 3; shift  # drop --
cd /opt/stockscreener/trading-bot-skills
BT=/opt/stockscreener/trading-bot-skills/run_skills_backtest.py
i=0
for spec in "$@"; do
  RID="${spec%%:*}"; ARGS="${spec#*:}"
  # refresh data sequentially before each batch to avoid concurrent /session 400s
  if [ $((i % PAR)) -eq 0 ]; then
    python3 /opt/stockscreener/trading-bot-skills/fetch_data.py --epic $INST --timeframe M5 --bars 300 >/dev/null 2>&1
    wait
  fi
  python3 $BT --instrument $INST --years 2 --results-dir $OUT --run-id $RID $ARGS > /tmp/sw_${INST}_${RID}.log 2>&1 &
  i=$((i+1))
  if [ $((i % PAR)) -eq 0 ]; then wait; fi
done
wait
echo "SWEEP_DONE $INST"
