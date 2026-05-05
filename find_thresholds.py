#!/usr/bin/env python3
"""
STEP2_train_and_export.py
=========================

Runs on your PC. Does 5 things:
  1) collect          — record EMG gestures to CSV
  2) windows          — slice CSVs into training windows
  3) train            — train CNN gesture classifier
  4) export_uc        — export CNN weights for RP2040
  5) train_thresholds — train AI to learn FLEX thresholds

"""

import argparse, csv, json, time
from pathlib import Path
from collections import Counter
import numpy as np
from scipy.signal import butter, lfilter, iirnotch

try:
    import serial
except ImportError:
    serial = None

try:
    import tensorflow as tf
except ImportError:
    tf = None

# ───────────────────────── Config ─────────────────────────
FS       = 1000
WIN      = 128
OVERLAP  = 0.5
BP_LOW   = 20.0
BP_HIGH  = 450.0
NOTCH    = 60.0
ENV_LP   = 10.0

RAW_DIR  = Path("data/raw")
PROC_DIR = Path("data/processed")
MDL_DIR  = Path("models")

CLASSES  = ["rest", "flex", "extend", "grip_close", "grip_open"]

# ───────────────────────── DSP ─────────────────────────────
def _butter_bp(x, fs, lo, hi, order=4):
    nyq = 0.5 * fs
    b, a = butter(order, [lo/nyq, hi/nyq], btype='band')
    return lfilter(b, a, x)

def _notch(x, fs, f0=60.0, Q=30.0):
    if f0 <= 0: return x
    b, a = iirnotch(f0, Q, fs)
    return lfilter(b, a, x)

def _lp(x, fs, cutoff, order=4):
    nyq = 0.5 * fs
    b, a = butter(order, cutoff/nyq, btype='low')
    return lfilter(b, a, x)

def preprocess(x, fs=FS):
    x = _butter_bp(x, fs, BP_LOW, BP_HIGH)
    x = _notch(x, fs, NOTCH)
    x = np.abs(x)
    x = _lp(x, fs, ENV_LP)
    return x

# ───────────────────────── Helpers ─────────────────────────
def window_array(x, win, step):
    idx = range(0, len(x) - win + 1, step)
    return np.stack([x[s:s+win] for s in idx], 0) if len(list(range(0, len(x)-win+1, step))) else np.zeros((0, win))

def ensure_dirs():
    for d in [RAW_DIR, PROC_DIR, MDL_DIR]:
        d.mkdir(parents=True, exist_ok=True)

# ───────────────────────── 1. Collect ──────────────────────
def cmd_collect(args):
    if serial is None:
        raise SystemExit("pip install pyserial")
    ensure_dirs()

    fname = RAW_DIR / f"{int(time.time())}_{args.label}.csv"

    print(f"\n[collect] {args.label} for {args.seconds}s")
    time.sleep(3)

    ser = serial.Serial(args.port, baudrate=115200, timeout=1)
    t_end = time.time() + args.seconds

    with open(fname, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['emg', 'label'])
        while time.time() < t_end:
            line = ser.readline().decode(errors='ignore').strip()
            try:
                val = int(line)
                w.writerow([val, args.label])
            except:
                continue

    ser.close()
    print(f"[collect] saved → {fname}")

# ───────────────────────── 2. Windows ──────────────────────
def cmd_windows(args):
    ensure_dirs()
    step = int(WIN * (1 - OVERLAP))

    X_list, y_list = [], []

    for csvp in RAW_DIR.glob("*.csv"):
        label = csvp.stem.split("_")[-1]
        raw = np.loadtxt(csvp, delimiter=",", skiprows=1, usecols=(0,))
        env = preprocess(raw)
        W = window_array(env, WIN, step)

        if len(W) == 0: continue

        X_list.append(W)
        y_list.append(np.array([label]*len(W)))

    X = np.concatenate(X_list)[:, :, None]
    y = np.concatenate(y_list)

    np.save(PROC_DIR / "X.npy", X)
    np.save(PROC_DIR / "y.npy", y)

    print(f"[windows] X{X.shape} saved")

# ───────────────────────── 3. CNN Train ────────────────────
def build_model(win, n_classes):
    i = tf.keras.Input(shape=(win,1))
    x = tf.keras.layers.Conv1D(8,7,activation='relu',padding='same')(i)
    x = tf.keras.layers.MaxPool1D(2)(x)
    x = tf.keras.layers.Conv1D(16,5,activation='relu',padding='same')(x)
    x = tf.keras.layers.GlobalAveragePooling1D()(x)
    o = tf.keras.layers.Dense(n_classes,activation='softmax')(x)

    m = tf.keras.Model(i,o)
    m.compile(optimizer='adam',loss='sparse_categorical_crossentropy',metrics=['accuracy'])
    return m

def cmd_train(args):
    X = np.load(PROC_DIR/"X.npy")
    y_str = np.load(PROC_DIR/"y.npy",allow_pickle=True)

    labels = sorted(set(y_str))
    lab2id = {l:i for i,l in enumerate(labels)}
    y = np.array([lab2id[v] for v in y_str])

    model = build_model(WIN,len(labels))
    model.fit(X,y,epochs=args.epochs,batch_size=64)

    model.save(MDL_DIR/"emg_savedmodel")
    print("[train] done")

# ───────────────────────── 4. Threshold AI ─────────────────
def extract_features(X):
    X = X.squeeze(-1)
    return np.stack([
        X.mean(axis=1),
        X.std(axis=1),
        X.max(axis=1),
        np.sqrt((X**2).mean(axis=1))
    ], axis=1)

def generate_targets(X,y):
    Xf = extract_features(X)

    rest = Xf[y=="rest"]
    flex = Xf[y=="flex"]

    mu = rest[:,0].mean()
    std = rest[:,1].mean()

    FLEX_ON  = mu + 3*std
    FLEX_OFF = mu + 1.5*std
    FLEX_MAX = np.percentile(flex[:,2],95)

    return Xf, np.tile([FLEX_ON,FLEX_OFF,FLEX_MAX],(len(Xf),1))

def cmd_train_thresholds(args):
    X = np.load(PROC_DIR/"X.npy")
    y = np.load(PROC_DIR/"y.npy",allow_pickle=True)

    Xf, targets = generate_targets(X,y)

    model = tf.keras.Sequential([
        tf.keras.layers.Dense(16,activation='relu',input_shape=(4,)),
        tf.keras.layers.Dense(16,activation='relu'),
        tf.keras.layers.Dense(3)
    ])

    model.compile(optimizer='adam',loss='mse')
    model.fit(Xf,targets,epochs=40)

    preds = model.predict(Xf)
    FLEX_ON,FLEX_OFF,FLEX_MAX = preds.mean(axis=0)

    FLEX_ON  = int(FLEX_ON)
    FLEX_OFF = int(FLEX_OFF)
    FLEX_MAX = int(FLEX_MAX)

    print("\n=== AI THRESHOLDS ===")
    print(FLEX_ON,FLEX_OFF,FLEX_MAX)

    (MDL_DIR/"thresholds.json").write_text(json.dumps({
        "FLEX_ON":FLEX_ON,
        "FLEX_OFF":FLEX_OFF,
        "FLEX_MAX":FLEX_MAX
    },indent=2))

# ───────────────────────── CLI ─────────────────────────────
if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd",required=True)

    pc = sub.add_parser("collect")
    pc.add_argument("--label",required=True,choices=CLASSES)
    pc.add_argument("--seconds",type=int,default=20)
    pc.add_argument("--port",required=True)
    pc.set_defaults(func=cmd_collect)

    sub.add_parser("windows").set_defaults(func=cmd_windows)

    pt = sub.add_parser("train")
    pt.add_argument("--epochs",type=int,default=30)
    pt.set_defaults(func=cmd_train)

    sub.add_parser("train_thresholds").set_defaults(func=cmd_train_thresholds)

    args = p.parse_args()
    args.func(args)


"""
==================== HOW TO USE ====================

1. Install dependencies:
   pip install numpy scipy pyserial tensorflow

2. Collect data:
   python STEP2_train_and_export.py collect --label rest --port COM5
   python STEP2_train_and_export.py collect --label flex --port COM5

3. Process data:
   python STEP2_train_and_export.py windows

4. Train threshold AI:
   python STEP2_train_and_export.py train_thresholds

5. Copy printed values into RP2040 code:
   FLEX_ON
   FLEX_OFF
   FLEX_MAX

====================================================
"""