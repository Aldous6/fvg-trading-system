import pandas as pd

# Lista de archivos de entrada y salida
files = [
    ("data_xauusd_m23.csv", "data_xauusd_m1_clean_2023.csv"),
    ("data_xauusd_m24.csv", "data_xauusd_m1_clean_2024.csv"),
    ("data_xauusd_m26.csv", "data_xauusd_m1_clean_2026.csv"),
    ("data_spxusd_m25.csv", "data_spxusd_m1_clean_spx_2025.csv"),
]

for input_file, output_file in files:
    print(f"Procesando {input_file}...")

    # 1) Leer archivo crudo de HistData
    raw = pd.read_csv(
        input_file,
        sep=";",                # HistData usa ';'
        header=None,            # no tiene encabezado
        names=["dt", "open", "high", "low", "close", "volume"]
    )

    # 2) Convertir "20250101 180000" a timestamp
    raw["timestamp"] = pd.to_datetime(raw["dt"], format="%Y%m%d %H%M%S")

    # 3) Interpretar como UTC y convertir a New York
    df = raw.set_index("timestamp").tz_localize("UTC")
    df = df.tz_convert("America/New_York").tz_localize(None)

    # 4) Quedarnos solo con OHLC
    df_out = df[["open", "high", "low", "close"]]

    # 5) Guardar CSV limpio
    df_out.to_csv(output_file)
    print(df_out.head())
    print(f"Listo: creado {output_file}\n")

print("Conversión finalizada.")
