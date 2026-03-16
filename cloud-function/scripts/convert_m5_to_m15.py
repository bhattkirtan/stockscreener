#!/usr/bin/env python3
"""Convert M5 bot to M15 bot - change only timeframe and strategy parameters"""
import re

# Read M5 bot
with open('trading_bot_m5.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace class name
content = content.replace('class TradingBot:', 'class TradingBotM15:')

# Replace strategy parameters  
content = re.sub(r'sma_fast=10,\s+# Faster SMA for M5', 'sma_fast=21,   # Optimized for M15', content)
content = re.sub(r'sma_slow=21,\s+# Faster slow SMA for M5', 'sma_slow=50,   # Optimized for M15', content)

# Replace M5 -> M15 in variables and comments
content = content.replace('m5_history', 'm15_history')
content = content.replace('M5', 'M15')
content = content.replace('MINUTE_5', 'MINUTE_15')

# Replace timeframe multipliers (5 min -> 15 min)
content = content.replace('count * 5', 'count * 15')

# Replace log file name
content = content.replace("'trading_bot.log'", "'trading_bot_m15.log'")

# Update main() to use M15 bot class
content = content.replace('bot = TradingBot(config', 'bot = TradingBotM15(config')

# Write M15 bot
with open('trading_bot_m15.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('✅ M15 bot created successfully')
print('📋 Changes made:')
print('   - Class: TradingBot -> TradingBotM15')
print('   - SMA fast: 10 -> 21')
print('   - SMA slow: 21 -> 50')
print('   - Timeframe: M5 -> M15')
print('   - Resolution: MINUTE_5 -> MINUTE_15')
print('   - Log file: trading_bot.log -> trading_bot_m15.log')
