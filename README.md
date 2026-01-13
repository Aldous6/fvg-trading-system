FVG TRADING SYSTEM
=================

End-to-end algorithmic trading system based on Fair Value Gaps (FVG) and
New York session breakouts, including:

- Historical data cleaning
- Realistic backtesting with costs
- Parameter optimization
- Multi-trade and single-trade variants
- Live execution bot for MetaTrader 5

WARNING:
Educational and research purposes only. Not financial advice.

--------------------------------------------------
STRATEGY OVERVIEW
--------------------------------------------------

The system trades Fair Value Gaps (FVG) in the direction of the trend,
confirmed by:

- EMA trend filter
- Breakout of the NY session opening range (first 5 minutes)
- ATR-based volatility filters
- Risk-reward based exits (RR configurable)

Key features:
- Session-based trading (New York)
- Break-even logic after 1.5R
- Realistic modeling: spread, commission, slippage
- Strict risk management (fixed % per trade)

--------------------------------------------------
EVOLUTION & TECHNICAL CHALLENGES
--------------------------------------------------

This project evolved through rigorous testing to eliminate statistical
biases and ensure realistic performance in live market conditions.

1) The "Phantom Entry" Bug (FIXED)
---------------------------------
Initial backtests produced unrealistic results (>300 R/year).

Problem:
The system assumed limit orders were filled immediately at the signal
close price, without price retracing to the entry level.

Solution:
The trade execution logic was rewritten using a state machine:

Pending -> Open -> Closed

- Entry only triggers if price actually trades through the limit level
- If Take Profit is hit before entry, the order is cancelled

Result:
- Win rate dropped from ~60% to ~42%
- Reliability increased to realistic, live-trading conditions

2) Asset Specificity (SPX500 vs Gold)
------------------------------------
The strategy is highly asset-dependent.

Gold (XAUUSD):
- High volatility and wick noise
- Excessive stop-outs with tight ATR stops (0.5–0.75 ATR)
- Poor signal-to-noise ratio for M1 breakouts

S&P 500 (SPXUSD):
- Cleaner momentum during NY Open
- Better institutional flow alignment

Decision:
The final system focuses exclusively on SPXUSD.

3) Single-Shot vs Multi-Trade Execution
---------------------------------------
Two execution modes were tested:

Multi-Trade ("Machine Gun"):
- Trades every valid signal from 9:30–11:00
- Result: Negative expectancy (-54 R)
- Overtrading and commission decay

Single-Shot ("Sniper"):
- Only first valid signal of the session
- Result: Strong performance (+65.89 R)
- Captures true institutional breakout

Final Decision:
System is hardcoded to execute a maximum of 1 trade per day.

--------------------------------------------------
CONFIGURATION & OPTIMIZATION
--------------------------------------------------

A grid search was run on 2025 SPXUSD data to find the optimal parameter
set.

OPTIMAL PARAMETERS (SPXUSD):

Asset:            SPXUSD (S&P 500 Index)
Timeframe:        M1 (1-minute candles)
Session:          09:30 – 11:00 NY time (strict)
Stop Loss:        0.75 x ATR
Take Profit:      3.0 R
Breakeven:        At 1.5 R (SL moved to entry + spread)
Risk per Trade:   1.0% (compounded)

These values are hardcoded in bot_fvg_live.py but can be adjusted in
the configuration section.

--------------------------------------------------
PERFORMANCE METRICS (2025 BACKTEST)
--------------------------------------------------

- Total Return:     +65.89 R (net of commissions)
- Win Rate:         ~42.5%
- Profit Factor:    > 1.5
- Max Drawdown:     ~6% (at 0.5% risk)

--------------------------------------------------
INSTALLATION & USAGE
--------------------------------------------------

1) Prerequisites
----------------
- Python 3.10+
- MetaTrader 5 Terminal
- MetaTrader5 Python library

2) Setup
--------
Clone the repository and install dependencies:

git clone https://github.com/Aldous6/fvg-trading-system.git
cd fvg-trading-system
pip install -r requirements.txt

3) Running Backtests
--------------------
Run the strict single-shot backtest:

python backtest_fvg.py

4) Live Execution
-----------------
Ensure MetaTrader 5 is running and Algo Trading is enabled.

python bot_fvg_live.py

--------------------------------------------------
RISK WARNING
--------------------------------------------------

This is a trend-following breakout system.

- Requires volatility to perform
- Do NOT trade on US bank holidays
- Expect losing streaks (42% win rate)
- Edge comes from 3:1 Reward-to-Risk ratio
- Psychological discipline is required to hold winners

--------------------------------------------------
PROJECT STRUCTURE
--------------------------------------------------

.
├── backtest_fvg.py        Single-trade per day backtest
├── backtest_multi.py      Multi-trade backtest (experimental)
├── bot_fvg_live.py        Live trading bot for MetaTrader 5
├── convert_xau.py         Data cleaning & timezone conversion
├── data/                  Cleaned OHLC CSV files (not included)
└── README.txt

--------------------------------------------------
END OF DOCUMENT
--------------------------------------------------
