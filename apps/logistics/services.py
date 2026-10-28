import logging
from django.utils import timezone
import numpy as np
from sklearn.linear_model import LinearRegression
from django.db import models
from .models import Dispatch

logger = logging.getLogger(__name__)

def predict_logistics_demand():
    """
    Predicts overall logistics demand (total quantity dispatched and estimated logistics cost)
    for the current day based on historical dispatch data.
    Safely handles date-rollover, missing records, and weekend gaps with default fallbacks.
    """
    try:
        today = timezone.localdate()
        
        # Aggregate total dispatch per day prior to today
        daily_dispatches = Dispatch.objects.filter(created_at__date__lt=today).values('created_at__date').annotate(
            total_quantity=models.Sum('quantity'),
            total_cost=models.Sum('cost')
        ).order_by('created_at__date')
        
        valid_dispatches = [
            d for d in daily_dispatches 
            if d.get('total_quantity') is not None and float(d['total_quantity']) > 0
        ]
        
        if len(valid_dispatches) < 3:
            return {
                "predicted_dispatch_quantity": 5000.0,
                "predicted_dispatch_cost": 1500.0,
                "status": "baseline (insufficient data)"
            }

        # Prepare dataset for Scikit-Learn
        X = np.arange(len(valid_dispatches)).reshape(-1, 1)
        y_quantity = np.array([float(d['total_quantity'] or 0.0) for d in valid_dispatches])
        y_cost = np.array([float(d['total_cost'] or 0.0) for d in valid_dispatches])
        
        # Train the models on overall logistics demand
        model_quantity = LinearRegression().fit(X, y_quantity)
        model_cost = LinearRegression().fit(X, y_cost)
        
        # Predict logistics demand for today
        next_index = np.array([[len(valid_dispatches)]])
        predicted_quantity = max(500.0, float(model_quantity.predict(next_index)[0]))
        predicted_cost = max(100.0, float(model_cost.predict(next_index)[0]))
        
        return {
            "predicted_dispatch_quantity": round(predicted_quantity, 2),
            "predicted_dispatch_cost": round(predicted_cost, 2),
            "status": "ML predicted"
        }
    except Exception as exc:
        logger.warning("Error predicting logistics demand: %s. Using safe fallback.", exc)
        return {
            "predicted_dispatch_quantity": 5000.0,
            "predicted_dispatch_cost": 1500.0,
            "status": "fallback"
        }
