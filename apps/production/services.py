from datetime import date
import numpy as np
from sklearn.linear_model import LinearRegression
from django.db import models
from apps.accounts.models import User
from .models import ProductionLog, ProductionTarget

def predict_factory_production():
    """
    Predicts overall factory production output for the current day based on 
    historical total production data across all machines and operators.
    """
    today = date.today()
    
    # Aggregate total production per day
    daily_logs = ProductionLog.objects.filter(date__lt=today).values('date').annotate(
        total_output=models.Sum('output_kg')
    ).order_by('date')
    
    if daily_logs.count() < 3:
        return {"predicted_factory_output_kg": 2500.0, "status": "baseline (insufficient data)"}

    # Prepare dataset for Scikit-Learn
    X = np.arange(len(daily_logs)).reshape(-1, 1)
    y = np.array([float(log['total_output']) for log in daily_logs])
    
    # Train the model on overall factory performance
    model = LinearRegression()
    model.fit(X, y)
    
    # Predict factory output for today
    next_index = np.array([[len(daily_logs)]])
    predicted_output = model.predict(next_index)[0]
    
    return {
        "predicted_factory_output_kg": round(predicted_output, 2),
        "status": "ML predicted"
    }
