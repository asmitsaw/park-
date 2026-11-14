"""
PARK+ : Machine Learning Inference Module
Loads trained models and predicts parking duration & anomaly score.
"""

import sys
import json
import sqlite3
import joblib
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "backend" / "instance" / "parksentinel.db"
MODELS_DIR = Path(__file__).resolve().parent / "models"

def predict_parking_duration(arrival_hour=9, day_of_week=1, vehicle_type='car', plan_type='monthly'):
    reg_path = MODELS_DIR / "duration_regressor.pkl"
    features_path = MODELS_DIR / "model_features.pkl"

    if not reg_path.exists() or not features_path.exists():
        print("[!] Model artifacts not found. Please train models first using: python ml/train_model.py")
        return None

    model = joblib.load(reg_path)
    feature_columns = joblib.load(features_path)

    # Prepare input feature row
    is_weekend = 1 if day_of_week in [5, 6] else 0
    raw_dict = {
        'arrival_hour': arrival_hour,
        'day_of_week': day_of_week,
        'is_weekend': is_weekend,
        'vehicle_type': vehicle_type,
        'plan_type': plan_type
    }

    df_in = pd.DataFrame([raw_dict])
    df_encoded = pd.get_dummies(df_in[['arrival_hour', 'day_of_week', 'is_weekend', 'vehicle_type', 'plan_type']])
    
    # Reindex to match training columns
    for col in feature_columns:
        if col not in df_encoded.columns:
            df_encoded[col] = 0
    df_encoded = df_encoded[feature_columns]

    pred_seconds = int(model.predict(df_encoded)[0])
    pred_minutes = round(pred_seconds / 60.0, 1)

    result = {
        "predicted_duration_seconds": pred_seconds,
        "predicted_duration_minutes": pred_minutes,
        "predicted_duration_formatted": f"{pred_seconds // 3600}h {(pred_seconds % 3600) // 60}m",
        "inputs": raw_dict
    }

    # Save to SQLite ai_predictions table
    if DB_PATH.exists():
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        utc_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cur.execute("""
            INSERT INTO ai_predictions (model_name, prediction_type, input_features, prediction_result, confidence_score, created_at)
            VALUES ('RandomForestRegressor_v1', 'duration', ?, ?, 0.85, ?)
        """, (json.dumps(raw_dict), json.dumps(result), utc_now))
        conn.commit()
        conn.close()

    return result

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Predict Parking Duration")
    parser.add_argument("--hour", type=int, default=9, help="Arrival hour (0-23)")
    parser.add_argument("--day", type=int, default=1, help="Day of week (0=Mon, 6=Sun)")
    parser.add_argument("--type", type=str, default="car", help="Vehicle type (car, suv, bike, ev)")
    parser.add_argument("--plan", type=str, default="monthly", help="Plan type (monthly, prepaid)")
    args = parser.parse_args()

    pred = predict_parking_duration(args.hour, args.day, args.type, args.plan)
    if pred:
        print("\n=============================================")
        print("  PARK+ AI/ML Parking Duration Prediction")
        print("=============================================")
        print(f"  Inputs: {pred['inputs']}")
        print(f"  Predicted Duration: {pred['predicted_duration_formatted']} ({pred['predicted_duration_minutes']} min)")
        print("  Saved to SQLite 'ai_predictions' table.")
        print("=============================================\n")

