"""
PARK+ : Machine Learning Module
Model Training Script: Parking Duration & Demand Prediction
Uses Scikit-Learn, Pandas, and SQLite
"""

import os
import sys
import sqlite3
import joblib
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sklearn.ensemble import RandomForestRegressor, IsolationForest
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "backend" / "instance" / "parksentinel.db"
MODELS_DIR = Path(__file__).resolve().parent / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

def load_data_from_db():
    if not DB_PATH.exists():
        print(f"[!] Database file not found at {DB_PATH}")
        return pd.DataFrame()

    conn = sqlite3.connect(DB_PATH)
    query = """
        SELECT s.id, s.entry_time, s.exit_time, s.duration_seconds,
               v.vehicle_type, u.id as user_id, p.plan_type
        FROM parking_sessions s
        JOIN vehicles v ON s.vehicle_id = v.id
        JOIN users u ON s.user_id = u.id
        LEFT JOIN subscriptions sub ON sub.user_id = u.id
        LEFT JOIN subscription_plans p ON sub.plan_id = p.id
        WHERE s.status = 'completed' AND s.duration_seconds > 60
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def generate_synthetic_samples_if_needed(df, count=150):
    """
    Generates realistic historical data for college viva demonstration 
    if real hardware traffic has not accumulated enough records yet.
    """
    if len(df) >= 20:
        print(f"[+] Found {len(df)} real historical sessions in database. Using real data for training.")
        return df

    print(f"[*] Real database contains {len(df)} completed sessions. Bootstrapping {count} realistic demonstration sessions...")
    np.random.seed(42)
    records = []
    base_time = datetime.now(timezone.utc) - timedelta(days=30)

    vehicle_types = ['car', 'suv', 'bike', 'ev']
    plan_types = ['monthly', 'prepaid']

    for i in range(count):
        day_offset = np.random.randint(0, 30)
        hour = np.random.choice([8, 9, 10, 11, 14, 15, 17, 18, 19], p=[0.15, 0.20, 0.15, 0.10, 0.10, 0.05, 0.10, 0.10, 0.05])
        minute = np.random.randint(0, 60)
        entry = base_time + timedelta(days=day_offset, hours=int(hour), minutes=int(minute))

        v_type = np.random.choice(vehicle_types, p=[0.55, 0.25, 0.15, 0.05])
        p_type = np.random.choice(plan_types, p=[0.6, 0.4])

        # Realistic duration distribution centered around peak hours
        if hour in [9, 10]: # Morning shift
            duration_min = np.random.normal(240, 45) # ~4 hours
        elif hour in [14, 15]: # Short meeting
            duration_min = np.random.normal(90, 25)  # ~1.5 hours
        else:
            duration_min = np.random.normal(120, 35) # ~2 hours

        duration_sec = max(300, int(duration_min * 60))
        exit_time = entry + timedelta(seconds=duration_sec)

        records.append({
            'entry_time': entry.isoformat(),
            'exit_time': exit_time.isoformat(),
            'duration_seconds': duration_sec,
            'vehicle_type': v_type,
            'plan_type': p_type
        })

    return pd.DataFrame(records)

def train_models():
    print("[*] Loading parking dataset...")
    df = load_data_from_db()
    df = generate_synthetic_samples_if_needed(df)

    # Feature engineering
    df['entry_dt'] = pd.to_datetime(df['entry_time'])
    df['arrival_hour'] = df['entry_dt'].dt.hour
    df['day_of_week'] = df['entry_dt'].dt.dayofweek
    df['is_weekend'] = df['day_of_week'].isin([5, 6]).astype(int)

    # One-hot encode categorical features
    feature_df = pd.get_dummies(df[['arrival_hour', 'day_of_week', 'is_weekend', 'vehicle_type', 'plan_type']], drop_first=True)
    X = feature_df
    y = df['duration_seconds']

    print(f"[*] Training dataset shape: {X.shape}")
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # 1. Duration Regression Model
    regressor = RandomForestRegressor(n_estimators=100, max_depth=8, random_state=42)
    regressor.fit(X_train, y_train)

    y_pred = regressor.predict(X_test)
    mae_mins = mean_absolute_error(y_test, y_pred) / 60.0
    r2 = r2_score(y_test, y_pred)

    print(f"[+] Model Trained: RandomForest Duration Predictor")
    print(f"    - Mean Absolute Error (MAE): {mae_mins:.2f} minutes")
    print(f"    - R-squared (R2) Score: {r2:.3f}")

    # 2. Anomaly Detection Model (Unusual Parking Duration)
    anomaly_detector = IsolationForest(contamination=0.05, random_state=42)
    anomaly_detector.fit(X[['arrival_hour', 'day_of_week']])

    # Save artifacts
    joblib.dump(regressor, MODELS_DIR / "duration_regressor.pkl")
    joblib.dump(anomaly_detector, MODELS_DIR / "duration_anomaly_detector.pkl")
    joblib.dump(list(X.columns), MODELS_DIR / "model_features.pkl")

    print(f"[+] Trained model artifacts saved to {MODELS_DIR}")
    return True

if __name__ == "__main__":
    train_models()

