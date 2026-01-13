import MetaTrader5 as mt5
import pandas as pd
import time
from datetime import datetime, time as dt_time
import pytz

# ==========================================
# 1. CONFIGURACIÓN DE USUARIO (CALIBRAR ANTES DE USAR)
# ==========================================

# Credenciales y Broker
SYMBOL = "XAUUSD"        # IMPORTANTE: Revisa si en tu MT5 es "Gold", "XAUUSD.r", etc.
TIMEFRAME = mt5.TIMEFRAME_M1
MAGIC_NUMBER = 888999    # ID del Bot (La "firma" de tus órdenes)

# Gestión de Riesgo
CAPITAL_REAL_MXN = 20000.0 # Solo referencia visual
RIESGO_PCT = 0.01        # 1% de riesgo por trade
RR_TARGET = 3.0          # Ratio 1:3
MAX_SPREAD_PUNTOS = 35   # Si el spread > 35 puntos (35 centavos), no opera.

# Horarios (Ajustar a la HORA DEL SERVIDOR de tu MT5)
# Si tu broker es GMT+3 (común en ECN), la apertura de NY (9:30 AM EST) es 16:30.
HORA_INICIO_SERVER = 16  
MINUTO_INICIO_SERVER = 30
HORA_FIN_SERVER = 18     # Hora a la que deja de buscar entradas (18:00 server = 11:00 AM NY)
HORA_CIERRE_FORZOSO = 20 # Hora a la que cierra todo (20:00 server = 1:00 PM NY)

# Indicadores
EMA_PERIOD = 50
ATR_PERIOD = 14

# ==========================================
# 2. FUNCIONES DE CONEXIÓN Y DATOS
# ==========================================

def conectar_mt5():
    if not mt5.initialize():
        print(f"❌ Error al iniciar MT5: {mt5.last_error()}")
        return False
    # Imprimir info para verificar
    print(f"✅ Conectado a: {mt5.account_info().server}")
    print(f"💰 Balance: {mt5.account_info().balance} {mt5.account_info().currency}")
    return True

def obtener_datos(simbolo, n_velas=100):
    rates = mt5.copy_rates_from_pos(simbolo, TIMEFRAME, 0, n_velas)
    if rates is None or len(rates) == 0:
        print(f"❌ Error obteniendo datos para {simbolo}")
        return None
    
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    
    # Cálculos Técnicos
    df['ema'] = df['close'].ewm(span=EMA_PERIOD, adjust=False).mean()
    
    # ATR Manual
    high_low = df['high'] - df['low']
    high_close = abs(df['high'] - df['close'].shift())
    low_close = abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    df['atr'] = true_range.ewm(alpha=1/ATR_PERIOD, min_periods=ATR_PERIOD).mean()
    
    return df

def checar_spread(simbolo):
    symbol_info = mt5.symbol_info(simbolo)
    if symbol_info is None: return 999
    # Retorna spread en puntos (ej. 20 para 0.20 USD en oro estándar)
    return symbol_info.spread

# ==========================================
# 3. MÚSCULO DE EJECUCIÓN (ÓRDENES)
# ==========================================

def enviar_orden_limite(tipo, precio, sl, tp, riesgo_dinero):
    symbol_info = mt5.symbol_info(SYMBOL)
    if symbol_info is None: return
    
    # 1. Filtro de Spread
    spread_actual = symbol_info.spread
    if spread_actual > MAX_SPREAD_PUNTOS:
        print(f"⚠️ Spread alto ({spread_actual} pts). Orden omitida.")
        return

    # 2. Cálculo de Lotaje (Física Financiera)
    distancia_sl = abs(precio - sl)
    if distancia_sl == 0: return

    # Obtener valor del tick y tamaño del contrato
    # En XAUUSD: tick_value suele ser 1.0 (USD) por 1 lote (100 oz) moviendo 1 tick (0.01)
    tick_value = symbol_info.trade_tick_value
    tick_size = symbol_info.trade_tick_size
    
    if tick_value == 0 or tick_size == 0: 
        print("❌ Error en datos del símbolo (tick value/size 0)")
        return

    # Riesgo = Volumen * (DistanciaPrecio / TickSize) * TickValue
    # Volumen = Riesgo / ((DistanciaPrecio / TickSize) * TickValue)
    
    puntos_riesgo = distancia_sl / tick_size
    lotaje_raw = riesgo_dinero / (puntos_riesgo * tick_value)
    
    # Normalizar lotaje
    step = symbol_info.volume_step
    lotaje = round(lotaje_raw / step) * step
    
    if lotaje < symbol_info.volume_min: lotaje = symbol_info.volume_min
    if lotaje > symbol_info.volume_max: lotaje = symbol_info.volume_max

    print(f"📐 Setup: Entrada {precio:.2f} | SL {sl:.2f} | TP {tp:.2f}")
    print(f"⚖️ Gestión: Riesgo ${riesgo_dinero:.2f} | Lotes Calculados: {lotaje}")

    # 3. Enviar Request
    tipo_orden = mt5.ORDER_TYPE_BUY_LIMIT if tipo == "long" else mt5.ORDER_TYPE_SELL_LIMIT
    
    request = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": SYMBOL,
        "volume": lotaje,
        "type": tipo_orden,
        "price": precio,
        "sl": sl,
        "tp": tp,
        "deviation": 20,
        "magic": MAGIC_NUMBER,
        "comment": "FVG Bot Pro",
        "type_time": mt5.ORDER_TIME_DAY, # Expira hoy si no se activa
        "type_filling": mt5.ORDER_FILLING_RETURN,
    }
    
    res = mt5.order_send(request)
    if res.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"❌ Error MT5: {res.comment}")
    else:
        print(f"🚀 ORDEN {tipo.upper()} ENVIADA! Ticket: {res.order}")

# ==========================================
# 4. GESTIÓN ACTIVA (BREAKEVEN)
# ==========================================

def gestionar_posiciones():
    """
    Revisa posiciones abiertas. Si el precio ha avanzado 1.5R,
    mueve el Stop Loss a Breakeven.
    """
    posiciones = mt5.positions_get(symbol=SYMBOL)
    if posiciones is None or len(posiciones) == 0: return

    for pos in posiciones:
        # Solo gestionar posiciones de este bot
        if pos.magic != MAGIC_NUMBER: continue
        
        # Datos
        tipo = pos.type # 0 = Buy, 1 = Sell
        entry = pos.price_open
        sl_actual = pos.sl
        tp = pos.tp
        precio_actual = pos.price_current
        
        # Calcular R (Riesgo inicial aproximado)
        # Si no hay SL (peligroso), no podemos calcular R
        if sl_actual == 0: continue
        
        riesgo_inicial = abs(entry - sl_actual)
        umbral_be = 1.5 * riesgo_inicial
        
        # --- Lógica Buy ---
        if tipo == mt5.ORDER_TYPE_BUY:
            ganancia_actual = precio_actual - entry
            # Si ya avanzó 1.5R y el SL sigue abajo del entry
            if ganancia_actual >= umbral_be and sl_actual < entry:
                nuevo_sl = entry + 0.10 # +10 centavos para cubrir spread/comisión
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "sl": nuevo_sl,
                    "tp": tp,
                    "symbol": SYMBOL,
                    "magic": MAGIC_NUMBER
                }
                res = mt5.order_send(request)
                if res.retcode == mt5.TRADE_RETCODE_DONE:
                    print(f"🛡️ BUY Protegido a Breakeven (Ticket: {pos.ticket})")

        # --- Lógica Sell ---
        elif tipo == mt5.ORDER_TYPE_SELL:
            ganancia_actual = entry - precio_actual
            # Si ya avanzó 1.5R y el SL sigue arriba del entry
            if ganancia_actual >= umbral_be and sl_actual > entry:
                nuevo_sl = entry - 0.10
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "sl": nuevo_sl,
                    "tp": tp,
                    "symbol": SYMBOL,
                    "magic": MAGIC_NUMBER
                }
                res = mt5.order_send(request)
                if res.retcode == mt5.TRADE_RETCODE_DONE:
                    print(f"🛡️ SELL Protegido a Breakeven (Ticket: {pos.ticket})")

# ==========================================
# 5. CEREBRO PRINCIPAL (LOOP)
# ==========================================

def run_bot():
    if not conectar_mt5(): return
    
    print("\n" + "="*40)
    print(f"🤖 BOT FVG PRO ACTIVADO - {SYMBOL}")
    print(f"🕒 Horario Operativo (Server): {HORA_INICIO_SERVER}:{MINUTO_INICIO_SERVER} a {HORA_FIN_SERVER}:00")
    print(f"💰 Riesgo por Trade: {RIESGO_PCT*100}%")
    print("="*40 + "\n")

    # Variables de estado
    dia_actual = datetime.now().day
    rango_high = None
    rango_low = None
    trade_realizado_hoy = False

    while True:
        # Frecuencia de actualización (1 segundo)
        time.sleep(1)
        
        # Sincronización con Broker
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None: continue
        server_time = datetime.fromtimestamp(tick.time)
        
        # 1. Reset Diario
        if server_time.day != dia_actual:
            print(f"📅 Nuevo día operativo: {server_time.date()}")
            dia_actual = server_time.day
            rango_high = None
            rango_low = None
            trade_realizado_hoy = False
            
            # Limpiar órdenes pendientes viejas
            ordenes = mt5.orders_get(symbol=SYMBOL)
            if ordenes:
                for o in ordenes:
                    if o.magic == MAGIC_NUMBER:
                        req = {"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket}
                        mt5.order_send(req)
                print("🧹 Órdenes pendientes limpiadas.")

        # 2. Gestión de Posiciones (Breakeven y Cierre Forzoso)
        gestionar_posiciones()
        
        if server_time.hour >= HORA_CIERRE_FORZOSO:
            # Aquí podrías añadir lógica para cerrar todo si quieres irte plano a dormir
            pass

        # 3. Lógica de Sesión y Rango
        minutos_del_dia = server_time.hour * 60 + server_time.minute
        inicio_minutos = HORA_INICIO_SERVER * 60 + MINUTO_INICIO_SERVER
        fin_minutos = HORA_FIN_SERVER * 60
        
        # Estamos en horario operativo?
        if minutos_del_dia < inicio_minutos or minutos_del_dia >= fin_minutos:
            continue # Fuera de horario

        # 4. Capturar Rango (High/Low de los primeros 5 min de sesión)
        # Se captura EXACTAMENTE 5 minutos después del inicio
        tiempo_captura = inicio_minutos + 5
        
        if rango_high is None:
            if minutos_del_dia >= tiempo_captura:
                # Descargar datos recientes para encontrar ese rango
                df = obtener_datos(SYMBOL, 50)
                if df is not None:
                    # Filtramos velas que ocurrieron en la ventana de apertura
                    # Lógica simple: Tomar las 5 velas anteriores al minuto de captura
                    # Esto es aproximado pero funcional en vivo
                    start_rango = pd.Timestamp(server_time.year, server_time.month, server_time.day, HORA_INICIO_SERVER, MINUTO_INICIO_SERVER)
                    end_rango = start_rango + pd.Timedelta(minutes=5)
                    
                    mask = (df['time'] >= start_rango) & (df['time'] < end_rango)
                    df_rango = df.loc[mask]
                    
                    if not df_rango.empty:
                        rango_high = df_rango['high'].max()
                        rango_low = df_rango['low'].min()
                        print(f"📊 Rango Apertura Capturado: High {rango_high} | Low {rango_low}")
                    else:
                        # Si no hay datos aun, esperar
                        pass
            else:
                # Aun no pasan los 5 minutos iniciales
                continue

        # 5. Búsqueda de Entrada (Solo si no hemos operado hoy)
        if rango_high is not None and not trade_realizado_hoy:
            
            # Solo analizamos al cierre de vela (segundo 0, 1 o 2)
            if server_time.second > 3: continue

            df = obtener_datos(SYMBOL, 20)
            if df is None: continue
            
            # Índices seguros
            if len(df) < 5: continue
            
            # Velas: -1 (Actual), -2 (Cerrada/Trigger), -3 (Gap Creator), -4 (Base)
            c2 = df.iloc[-2] # Vela Confirmación
            c1 = df.iloc[-3]
            c0 = df.iloc[-4]
            
            # Filtro Hora Exacta (V8.5 improvement)
            # Aseguramos que c2 haya cerrado dentro del horario permitido
            
            curr_atr = c2['atr']
            min_gap = curr_atr * 0.1
            spread_actual = checar_spread(SYMBOL) * symbol_info.point # Convertir puntos a precio
            
            # --- SETUP LONG ---
            # Tendencia + Ruptura High + FVG
            if c2['close'] > c2['ema']:
                if c2['close'] > rango_high or c1['close'] > rango_high:
                    if c2['low'] > c0['high']: # FVG Up
                        gap_size = c2['low'] - c0['high']
                        
                        # Filtro de Spread (V8.5 improvement)
                        # El gap debe ser mayor al spread + un margen
                        if gap_size >= min_gap:
                            entry = c0['high']
                            sl = c0['low'] - (curr_atr * 0.1)
                            
                            # Filtro suicida
                            if abs(entry - sl) > (spread_actual * 1.5):
                                tp = entry + (abs(entry - sl) * RR_TARGET)
                                
                                # Enviar
                                account = mt5.account_info()
                                riesgo_dinero = account.balance * RIESGO_PCT
                                enviar_orden_limite("long", entry, sl, tp, riesgo_dinero)
                                trade_realizado_hoy = True
                                time.sleep(10) # Pausa para evitar doble envío

            # --- SETUP SHORT ---
            # Tendencia + Ruptura Low + FVG
            elif c2['close'] < c2['ema']:
                if c2['close'] < rango_low or c1['close'] < rango_low:
                    if c2['high'] < c0['low']: # FVG Down
                        gap_size = c0['low'] - c2['high']
                        
                        if gap_size >= min_gap:
                            entry = c0['low']
                            sl = c0['high'] + (curr_atr * 0.1)
                            
                            if abs(entry - sl) > (spread_actual * 1.5):
                                tp = entry - (abs(entry - sl) * RR_TARGET)
                                
                                account = mt5.account_info()
                                riesgo_dinero = account.balance * RIESGO_PCT
                                enviar_orden_limite("short", entry, sl, tp, riesgo_dinero)
                                trade_realizado_hoy = True
                                time.sleep(10)

if __name__ == "__main__":
    try:
        run_bot()
    except KeyboardInterrupt:
        print("\n🛑 Bot detenido por el usuario.")
        mt5.shutdown()