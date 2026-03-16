#!/bin/bash

LOG_FILE="/tmp/phase2_real.log"
CHECK_INTERVAL=60  # seconds

echo "🔍 Phase 2 Optimization Monitor"
echo "================================"
echo "Log: $LOG_FILE"
echo "Update interval: ${CHECK_INTERVAL}s"
echo "Press Ctrl+C to stop monitoring"
echo ""

while true; do
    clear
    echo "🔍 Phase 2 Optimization Monitor - $(date '+%Y-%m-%d %H:%M:%S')"
    echo "=================================================================="
    echo ""
    
    # Check if process is running
    PROCESS_COUNT=$(ps aux | grep -i "run-local-optimization" | grep -v grep | wc -l | tr -d ' ')
    if [ "$PROCESS_COUNT" -eq "0" ]; then
        echo "⚠️  No optimization process running!"
        echo ""
        echo "Checking for results..."
        LATEST_CSV=$(find /Users/kirtanbhatt/code/stockScreener/cloud-function/data/optimization -name "*_all_strategies_*.csv" -type f -mmin -10 | head -1)
        if [ -n "$LATEST_CSV" ]; then
            echo "✅ OPTIMIZATION COMPLETE!"
            echo "Results: $LATEST_CSV"
            exit 0
        else
            echo "❌ No recent results found"
            exit 1
        fi
    fi
    
    echo "✅ Optimization Running"
    echo ""
    
    # Show worker processes
    WORKER_COUNT=$(pgrep -P $(pgrep -f "run-local-optimization" | head -1) 2>/dev/null | wc -l | tr -d ' ')
    echo "👷 Workers: $WORKER_COUNT"
    echo ""
    
    # Show last few log lines with progress
    if [ -f "$LOG_FILE" ]; then
        echo "📊 Latest Progress:"
        echo "-------------------"
        tail -5 "$LOG_FILE" | grep -E "Progress|Testing|combinations|%" || tail -2 "$LOG_FILE"
        echo ""
        
        # Extract progress percentage
        PROGRESS=$(tail -10 "$LOG_FILE" | grep -oE "[0-9]+\.[0-9]+%" | tail -1)
        if [ -n "$PROGRESS" ]; then
            echo "Current: $PROGRESS"
            
            # Estimate time remaining based on progress
            COMPLETED=$(tail -10 "$LOG_FILE" | grep -oE "Progress: [0-9]+/" | tail -1 | grep -oE "[0-9]+")
            if [ -n "$COMPLETED" ]; then
                TOTAL=2304
                PERCENT_NUM=$(echo $PROGRESS | sed 's/%//')
                if [ $(echo "$PERCENT_NUM > 0" | bc -l) -eq 1 ]; then
                    # Calculate elapsed time
                    START_TIME=$(stat -f %B "$LOG_FILE" 2>/dev/null || echo 0)
                    CURRENT_TIME=$(date +%s)
                    ELAPSED=$((CURRENT_TIME - START_TIME))
                    
                    if [ $ELAPSED -gt 0 ]; then
                        TOTAL_EST=$(echo "scale=0; $ELAPSED / ($PERCENT_NUM / 100)" | bc -l)
                        REMAINING=$((TOTAL_EST - ELAPSED))
                        
                        HOURS=$((REMAINING / 3600))
                        MINS=$(((REMAINING % 3600) / 60))
                        
                        echo "⏱️  Elapsed: $((ELAPSED / 60))m"
                        echo "⏳ ETA: ${HOURS}h ${MINS}m remaining"
                    fi
                fi
            fi
        fi
    else
        echo "⚠️  Log file not found yet"
    fi
    
    echo ""
    echo "=================================================================="
    echo "Next update in ${CHECK_INTERVAL}s... (Ctrl+C to stop)"
    
    sleep $CHECK_INTERVAL
done
