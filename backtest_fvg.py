import pandas as pd
import numpy as np
import itertools
import matplotlib.pyplot as plt
from datetime import time, timedelta

# =========================
# 1. CONFIGURACIÓN
# =========================
CSV_PATH = "data_xauusd_m1_clean_2025.csv"
SYMBOL = "SPXUSD"

# --- Parámetros Financieros (TU CUENTA) ---
CAPITAL_INICIAL = 10000.0  # Pesos (MXN)
RIESGO_POR_TRADE = 0.01   # 1% de la cuenta (Interés Compuesto)

# --- Parámetros del Mercado (REALISMO) ---
SPREAD = 0.20          
COMISION_R = 0.05      
SLIPPAGE_POINTS = 0.50 # Deslizamiento asumido
SESSION_START = time(9, 30)
SESSION_END   = time(11, 0)
SESSION_EXIT  = time(13, 0)

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
    Simula la vida de un trade: Pendiente -> Abierto -> Cerrado
    """
    is_open = False
    is_breakeven = False
    current_stop = stop_price
    
    # Breakeven se activa al 1.5R de beneficio
    breakeven_trigger = (entry_price + (risk_distance * 1.5)) if direction == "long" else (entry_price - (risk_distance * 1.5))

    for k in range(entry_idx, len(df_day)):
        fut = df_day.iloc[k]
        ts = df_day.index[k]
        
        # --- FASE 1: ORDEN PENDIENTE ---
        if not is_open:
            if ts.time() >= SESSION_EXIT: return None # Expiró la orden
            
            # Cancelaciones si el precio invalida el setup antes de entrar
            if direction == "long":
                if fut['low'] <= stop_price: return None 
                if fut['high'] >= target_price: return None 
                if fut['low'] <= entry_price: is_open = True # FILL (Entrada)
            else:
                if fut['high'] >= stop_price: return None
                if fut['low'] <= target_price: return None
                if fut['high'] >= entry_price: is_open = True # FILL (Entrada)
            
            if not is_open: continue

        # --- FASE 2: ORDEN ABIERTA ---
        # Cierre forzoso por hora
        if ts.time() >= SESSION_EXIT:
            exit_p = fut['close']
            pnl = (exit_p - entry_price) if direction == "long" else (entry_price - exit_p)
            return (pnl / risk_distance) - COMISION_R

        if direction == "long":
            # Gestión Breakeven
            if not is_breakeven and fut['high'] >= breakeven_trigger:
                current_stop = entry_price + SPREAD
                is_breakeven = True
            
            # Stop Loss Check
            if fut['low'] <= current_stop:
                # Aplicamos Slippage al salir por Stop
                exit_slippage = current_stop - SLIPPAGE_POINTS if not is_breakeven else current_stop
                return ((exit_slippage - entry_price) / risk_distance) - COMISION_R
            
            # Take Profit Check
            if fut['high'] >= target_price:
                return ((target_price - entry_price) / risk_distance) - COMISION_R

        else: # Short
            # Gestión Breakeven
            if not is_breakeven and fut['low'] <= breakeven_trigger:
                current_stop = entry_price - SPREAD
                is_breakeven = True
            
            # Stop Loss Check
            if fut['high'] >= current_stop:
                # Aplicamos Slippage
                exit_slippage = current_stop + SLIPPAGE_POINTS if not is_breakeven else current_stop
                return ((entry_price - exit_slippage) / risk_distance) - COMISION_R
            
            # Take Profit Check
            if fut['low'] <= target_price:
                return ((entry_price - target_price) / risk_distance) - COMISION_R
                
    # Cierre al final de los datos del día
    if is_open:
        last_p = df_day.iloc[-1]['close']
        pnl = (last_p - entry_price) if direction == "long" else (entry_price - last_p)
        return (pnl / risk_distance) - COMISION_R
        
    return None

def process_day(df_day, rr_target, stop_mult):
    if df_day.iloc[0]['atr'] == 0 or np.isnan(df_day.iloc[0]['atr']): return None

    # Definir rango de apertura (primeros 5 min)
    end_first5 = (pd.Timestamp.combine(pd.Timestamp.today(), SESSION_START) + timedelta(minutes=4)).time()
    mask_range = (df_day.index.time >= SESSION_START) & (df_day.index.time <= end_first5)
    range_candles = df_day.loc[mask_range]
    if len(range_candles) == 0: return None

    range_high = range_candles['high'].max()
    range_low = range_candles['low'].min()
    atr_val = range_candles.iloc[-1]['atr']
    
    # Filtro: Evitar días de volatilidad extrema en apertura
    if (range_high - range_low) > (atr_val * 5): return None 

    start_idx = np.where(df_day.index.time > end_first5)[0]
    if len(start_idx) == 0: return None
    start_idx = start_idx[0]

    for i in range(start_idx, len(df_day)):
        if i < 2: continue
        if df_day.index[i].time() > SESSION_END: break
            
        c0, c2 = df_day.iloc[i-2], df_day.iloc[i]
        curr_atr = c2['atr']
        min_gap = curr_atr * 0.1
        
        direction = None
        
        # --- Lógica de Setup (FVG + Breakout) ---
        if c2['close'] > c2['ema']: # Tendencia Alcista
            if (c2['low'] > c0['high']) and (c2['low'] - c0['high'] >= min_gap):
                if (c2['close'] > range_high):
                    direction = "long"
                    entry = c0['high']
                    stop = c0['low'] - (curr_atr * stop_mult) 
                    target = entry + ((entry - stop) * rr_target)

        elif c2['close'] < c2['ema']: # Tendencia Bajista
            if (c2['high'] < c0['low']) and (c0['low'] - c2['high'] >= min_gap):
                if (c2['close'] < range_low):
                    direction = "short"
                    entry = c0['low']
                    stop = c0['high'] + (curr_atr * stop_mult)
                    target = entry - ((stop - entry) * rr_target)

        if direction:
            risk = abs(entry - stop)
            if risk < (SPREAD * 2): continue # Filtro Spread
            
            res_r = simulate_trade_logic(df_day, i+1, direction, entry, stop, target, risk)
            if res_r is not None:
                return res_r # Tomamos solo el primer trade válido del día
    return None

# =========================
# 3. EJECUCIÓN Y SIMULACIÓN
# =========================

def run_full_system():
    print("=== INICIANDO SISTEMA DE TRADING ALGORÍTMICO ===")
    print("1. Cargando y procesando datos...")
    try:
        df = pd.read_csv(CSV_PATH)
    except FileNotFoundError:
        print(f"Error: No se encuentra '{CSV_PATH}'")
        return
        
    if "timestamp" not in df.columns:
        df.columns = ["timestamp", "open", "high", "low", "close", "vol", "sp", "rv"][:len(df.columns)]
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df = calculate_indicators(df)
    
    days = [g for _, g in df.groupby(df.index.date) if len(g) > 30]
    print(f"   -> Días operativos encontrados: {len(days)}")

    # --- PASO 1: OPTIMIZACIÓN (Encontrar los mejores parámetros) ---
    print("\n2. Ejecutando Optimización de Parámetros...")
    rr_params = [2.0, 2.5, 3.0] 
    stop_mult_params = [0.5, 0.75, 1.0]
    
    results = []

    print(f"   {'RR':<5} | {'StopMult':<10} | {'Total R':<10}")
    print("   " + "-"*30)

    for rr, sm in itertools.product(rr_params, stop_mult_params):
        outcomes = []
        for d in days:
            r = process_day(d, rr_target=rr, stop_mult=sm)
            if r is not None: outcomes.append(r)
        
        total_r = sum(outcomes)
        results.append({'RR': rr, 'StopMult': sm, 'Total_R': total_r, 'Trades': outcomes})
        print(f"   {rr:<5.1f} | {sm:<10.2f} | {total_r:<10.2f}")

    # Seleccionar el mejor
    best_config = sorted(results, key=lambda x: x['Total_R'], reverse=True)[0]
    print(f"\n✅ MEJOR CONFIGURACIÓN: RR={best_config['RR']} | Stop={best_config['StopMult']}xATR | R Total={best_config['Total_R']:.2f}")

    # --- PASO 2: SIMULACIÓN DE DINERO (INTERÉS COMPUESTO) ---
    print("\n3. Simulando Crecimiento de Cuenta (Interés Compuesto)...")
    
    balance = CAPITAL_INICIAL
    equity_curve = [balance]
    trade_outcomes = best_config['Trades']
    
    wins = 0
    losses = 0
    
    for r in trade_outcomes:
        # Gestión de Riesgo: Arriesgamos el 1% del saldo ACTUAL
        risk_amount = balance * RIESGO_POR_TRADE
        
        # PnL del trade
        pnl = risk_amount * r
        balance += pnl
        equity_curve.append(balance)
        
        if r > 0: wins += 1
        else: losses += 1

    net_profit = balance - CAPITAL_INICIAL
    roi = (net_profit / CAPITAL_INICIAL) * 100
    win_rate = (wins / len(trade_outcomes)) * 100

    print("-" * 40)
    print(f"💰 CAPITAL INICIAL:  ${CAPITAL_INICIAL:,.2f}")
    print(f"💰 CAPITAL FINAL:    ${balance:,.2f}")
    print(f"📈 BENEFICIO NETO:   ${net_profit:,.2f} (+{roi:.2f}%)")
    print("-" * 40)
    print(f"📊 Win Rate Real:    {win_rate:.2f}%")
    print(f"🎲 Total Trades:     {len(trade_outcomes)}")
    
    # --- GRÁFICA ---
    plt.figure(figsize=(10, 6))
    plt.plot(equity_curve, label='Curva de Equidad (Compuesta)', color='green', linewidth=1.5)
    plt.axhline(y=CAPITAL_INICIAL, color='r', linestyle='--', alpha=0.5, label='Capital Inicial')
    plt.title(f"Crecimiento de Cuenta: {CAPITAL_INICIAL} -> {balance:,.0f}\n(RR: {best_config['RR']} | Stop: {best_config['StopMult']} ATR)")
    plt.xlabel("# Operaciones")
    plt.ylabel("Saldo (MXN)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.show()

if __name__ == "__main__":
    run_full_system()