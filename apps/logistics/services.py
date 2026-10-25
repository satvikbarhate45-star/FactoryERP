from datetime import date
import numpy as np
from sklearn.linear_model import LinearRegression
from django.db import models
from .models import Dispatch

def predict_logistics_demand():
    """
    Predicts overall logistics demand (total quantity dispatched and estimated logistics cost)
    for the current day based on historical dispatch data.
    """
    today = date.today()
    
    # Aggregate total dispatch per day
    daily_dispatches = Dispatch.objects.filter(created_at__lt=today).values('created_at__date').annotate(
        total_quantity=models.Sum('quantity'),
        total_cost=models.Sum('cost')
    ).order_by('created_at__date')
    
    if daily_dispatches.count() < 3:
        return {
            "predicted_dispatch_quantity": 5000.0,
            "predicted_dispatch_cost": 1500.0,
            "status": "baseline (insufficient data)"
        }

    # Prepare dataset for Scikit-Learn
    X = np.arange(len(daily_dispatches)).reshape(-1, 1)
    y_quantity = np.array([float(d['total_quantity']) for d in daily_dispatches])
    y_cost = np.array([float(d['total_cost']) for d in daily_dispatches])
    
    # Train the models on overall logistics demand
    model_quantity = LinearRegression()
    model_quantity.fit(X, y_quantity)
    
    model_cost = LinearRegression()
    model_cost.fit(X, y_cost)
    
    # Predict logistics demand for today
    next_index = np.array([[len(daily_dispatches)]])
    predicted_quantity = model_quantity.predict(next_index)[0]
    predicted_cost = model_cost.predict(next_index)[0]
    
    return {
        "predicted_dispatch_quantity": round(predicted_quantity, 2),
        "predicted_dispatch_cost": round(predicted_cost, 2),
        "status": "ML predicted"
    }
