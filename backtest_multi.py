import pandas as pd
import numpy as np
import itertools
import matplotlib.pyplot as plt
from datetime import time, timedelta

# =========================
# 1. CONFIGURACIÓN
# =========================
CSV_PATH = "data_spxusd_m1_clean_spx_2025.csv"
SYMBOL = "SPXUSD"

# Financiero
CAPITAL_INICIAL = 10000.0  
RIESGO_POR_TRADE = 0.01    

# Mercado
SPREAD = 0.20          
COMISION_R = 0.05      
SLIPPAGE_POINTS = 0.50 
SESSION_START = time(9, 30)
SESSION_END   = time(11, 0) # Ventana de ENTRADAS
SESSION_EXIT  = time(13, 0) # Ventana de CIERRE FORZOSO

# =========================
# 2. LÓGICA TÉCNICA
# =========================

def calculate_indicators(df, atr_period=14, ema_period=50):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    df['atr'] = true_range.ewm(alpha=1/atr_period, min_periods=atr_period).mean()
    df['ema'] = df['close'].ewm(span=ema_period, adjust=False).mean()
    return df

def simulate_trade_logic(df_day, entry_idx, direction, entry_price, stop_price, target_price, risk_distance):
    """
    Ahora devuelve una tupla: (Resultado_R, Indice_De_Salida)
    Si no hubo trade (cancelado), devuelve (None, Indice_De_Cancelacion)
    """
    is_open = False
    is_breakeven = False
    current_stop = stop_price
    
    breakeven_trigger = (entry_price + (risk_distance * 1.5)) if direction == "long" else (entry_price - (risk_distance * 1.5))

    for k in range(entry_idx, len(df_day)):
        fut = df_day.iloc[k]
        ts = df_day.index[k]
        
        # --- FASE 1: ORDEN PENDIENTE ---
        if not is_open:
            if ts.time() >= SESSION_EXIT: return (None, k) # Expiró
            
            # Cancelaciones
            if direction == "long":
                if fut['low'] <= stop_price: return (None, k) 
                if fut['high'] >= target_price: return (None, k)
                if fut['low'] <= entry_price: is_open = True 
            else:
                if fut['high'] >= stop_price: return (None, k)
                if fut['low'] <= target_price: return (None, k)
                if fut['high'] >= entry_price: is_open = True 
            
            if not is_open: continue

        # --- FASE 2: ORDEN ABIERTA ---
        if ts.time() >= SESSION_EXIT:
            exit_p = fut['close']
            pnl = (exit_p - entry_price) if direction == "long" else (entry_price - exit_p)
            return ((pnl / risk_distance) - COMISION_R, k)

        if direction == "long":
            if not is_breakeven and fut['high'] >= breakeven_trigger:
                current_stop = entry_price + SPREAD
                is_breakeven = True
            
            if fut['low'] <= current_stop:
                exit_slippage = current_stop - SLIPPAGE_POINTS if not is_breakeven else current_stop
                return (((exit_slippage - entry_price) / risk_distance) - COMISION_R, k)
            
            if fut['high'] >= target_price:
                return (((target_price - entry_price) / risk_distance) - COMISION_R, k)

        else: # Short
            if not is_breakeven and fut['low'] <= breakeven_trigger:
                current_stop = entry_price - SPREAD
                is_breakeven = True
            
            if fut['high'] >= current_stop:
                exit_slippage = current_stop + SLIPPAGE_POINTS if not is_breakeven else current_stop
                return (((entry_price - exit_slippage) / risk_distance) - COMISION_R, k)
            
            if fut['low'] <= target_price:
                return (((entry_price - target_price) / risk_distance) - COMISION_R, k)
                
    # Cierre fin de datos
    if is_open:
        last_p = df_day.iloc[-1]['close']
        pnl = (last_p - entry_price) if direction == "long" else (entry_price - last_p)
        return ((pnl / risk_distance) - COMISION_R, len(df_day)-1)
        
    return (None, len(df_day)-1)

def process_day(df_day, rr_target, stop_mult):
    if df_day.iloc[0]['atr'] == 0 or np.isnan(df_day.iloc[0]['atr']): return []

    end_first5 = (pd.Timestamp.combine(pd.Timestamp.today(), SESSION_START) + timedelta(minutes=4)).time()
    mask_range = (df_day.index.time >= SESSION_START) & (df_day.index.time <= end_first5)
    range_candles = df_day.loc[mask_range]
    if len(range_candles) == 0: return []

    range_high = range_candles['high'].max()
    range_low = range_candles['low'].min()
    atr_val = range_candles.iloc[-1]['atr']
    
    if (range_high - range_low) > (atr_val * 5): return [] 

    start_idx_arr = np.where(df_day.index.time > end_first5)[0]
    if len(start_idx_arr) == 0: return []
    
    # Usamos un while loop para poder saltar índices
    i = start_idx_arr[0]
    daily_trades = []
    
    while i < len(df_day):
        if i < 2: 
            i += 1
            continue
            
        if df_day.index[i].time() > SESSION_END: 
            break
            
        c0, c2 = df_day.iloc[i-2], df_day.iloc[i]
        curr_atr = c2['atr']
        min_gap = curr_atr * 0.1
        
        direction = None
        
        # Setup Logic
        if c2['close'] > c2['ema']: 
            if (c2['low'] > c0['high']) and (c2['low'] - c0['high'] >= min_gap):
                if (c2['close'] > range_high):
                    direction = "long"
                    entry = c0['high']
                    stop = c0['low'] - (curr_atr * stop_mult) 
                    target = entry + ((entry - stop) * rr_target)

        elif c2['close'] < c2['ema']: 
            if (c2['high'] < c0['low']) and (c0['low'] - c2['high'] >= min_gap):
                if (c2['close'] < range_low):
                    direction = "short"
                    entry = c0['low']
                    stop = c0['high'] + (curr_atr * stop_mult)
                    target = entry - ((stop - entry) * rr_target)

        trade_executed = False
        if direction:
            risk = abs(entry - stop)
            if risk >= (SPREAD * 2): 
                # Intentamos simular
                res_tuple = simulate_trade_logic(df_day, i+1, direction, entry, stop, target, risk)
                
                if res_tuple:
                    r_val, exit_idx = res_tuple
                    
                    if r_val is not None:
                        # Trade completado
                        daily_trades.append(r_val)
                        i = exit_idx # Saltamos al momento de salida
                        trade_executed = True
                    else:
                        # Orden cancelada o no llenada, saltamos hasta donde se canceló
                        if exit_idx > i:
                            i = exit_idx
                            trade_executed = True
        
        if not trade_executed:
            i += 1
            
    return daily_trades

# =========================
# 3. EJECUCIÓN
# =========================

def run_full_system():
    print("=== SISTEMA MULTI-TRADE (Re-entradas activadas) ===")
    print("1. Cargando datos...")
    try:
        df = pd.read_csv(CSV_PATH)
    except:
        print("Error CSV")
        return
        
    if "timestamp" not in df.columns:
        df.columns = ["timestamp", "open", "high", "low", "close", "vol", "sp", "rv"][:len(df.columns)]
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df = calculate_indicators(df)
    
    days = [g for _, g in df.groupby(df.index.date) if len(g) > 30]
    print(f"   -> Días: {len(days)}")

    print("\n2. Optimizando (Buscando mejor config para Multi-Trade)...")
    # Probamos las configs que ya sabemos que funcionan bien + variantes
    rr_params = [2.0, 2.5, 3.0] 
    stop_mult_params = [0.5, 0.75, 1.0]
    
    results = []
    print(f"   {'RR':<5} | {'StopMult':<10} | {'Total R':<10} | {'# Trades':<8}")
    print("   " + "-"*45)

    for rr, sm in itertools.product(rr_params, stop_mult_params):
        all_outcomes = []
        for d in days:
            day_res = process_day(d, rr_target=rr, stop_mult=sm)
            all_outcomes.extend(day_res) # Aplanamos la lista
        
        total_r = sum(all_outcomes)
        results.append({'RR': rr, 'StopMult': sm, 'Total_R': total_r, 'Trades': all_outcomes})
        print(f"   {rr:<5.1f} | {sm:<10.2f} | {total_r:<10.2f} | {len(all_outcomes):<8}")

    best = sorted(results, key=lambda x: x['Total_R'], reverse=True)[0]
    print(f"\n✅ GANADOR: RR={best['RR']} | Stop={best['StopMult']}x | Total={best['Total_R']:.2f} R")

    # Simulacion Dinero
    print("\n3. Simulación Financiera...")
    balance = CAPITAL_INICIAL
    equity = [balance]
    trades = best['Trades']
    
    wins = sum(1 for x in trades if x > 0)
    
    for r in trades:
        risk = balance * RIESGO_POR_TRADE
        balance += risk * r
        equity.append(balance)

    net = balance - CAPITAL_INICIAL
    print(f"💰 Final: ${balance:,.2f} (+{(net/CAPITAL_INICIAL)*100:.2f}%)")
    print(f"📊 Win Rate: {(wins/len(trades))*100:.2f}% ({len(trades)} trades)")
    
    plt.plot(equity)
    plt.title(f"Multi-Trade Equity: {best['RR']}R / {best['StopMult']} Stop")
    plt.show()

if __name__ == "__main__":
    run_full_system()