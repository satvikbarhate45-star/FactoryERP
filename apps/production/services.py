import logging
from django.utils import timezone
import numpy as np
from sklearn.linear_model import LinearRegression
from django.db import models
from .models import ProductionLog

logger = logging.getLogger(__name__)

def predict_factory_production():
    """
    Predicts overall factory production output for the current day based on 
    historical total production data across all machines and operators.
    Safely handles date-rollover, missing previous days, and weekend gaps.
    """
    try:
        today = timezone.localdate()
        
        # Aggregate total production per day prior to today
        daily_logs = ProductionLog.objects.filter(date__lt=today).values('date').annotate(
            total_output=models.Sum('output_kg')
        ).order_by('date')
        
        valid_logs = [log for log in daily_logs if log.get('total_output') is not None and float(log['total_output']) > 0]
        
        if len(valid_logs) < 3:
            return {"predicted_factory_output_kg": 2500.0, "status": "baseline (insufficient data)"}

        # Prepare dataset for Scikit-Learn
        X = np.arange(len(valid_logs)).reshape(-1, 1)
        y = np.array([float(log['total_output']) for log in valid_logs])
        
        # Train the model on overall factory performance
        model = LinearRegression()
        model.fit(X, y)
        
        # Predict factory output for today
        next_index = np.array([[len(valid_logs)]])
        predicted_output = float(model.predict(next_index)[0])
        predicted_output = max(500.0, min(10000.0, predicted_output))
        
        return {
            "predicted_factory_output_kg": round(predicted_output, 2),
            "status": "ML predicted"
        }
    except Exception as exc:
        logger.warning("Error predicting factory production: %s. Using safe fallback.", exc)
        return {
            "predicted_factory_output_kg": 2500.0,
            "status": "fallback"
        }
