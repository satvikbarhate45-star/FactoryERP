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
    Safely handles date-rollover, missing previous days, and weekend gaps with dynamic DB binding.
    """
    try:
        today = timezone.localdate()
        
        # Aggregate total production per day prior to today
        daily_logs = ProductionLog.objects.filter(date__lt=today).values('date').annotate(
            total_output=models.Sum('output_kg')
        ).order_by('date')
        
        valid_logs = [log for log in daily_logs if log.get('total_output') is not None and float(log['total_output']) > 0]
        
        if len(valid_logs) < 3:
            from apps.production.models import SystemOverview
            recent_so = SystemOverview.objects.filter(total_output_kg__gt=0).order_by('-date').first()
            live_val = float(recent_so.total_output_kg) if recent_so and recent_so.total_output_kg else 5200.0
            return {
                "predicted_factory_output_kg": round(live_val, 2),
                "status": "Live DB Baseline"
            }

        # Prepare dataset for Scikit-Learn
        X = np.arange(len(valid_logs)).reshape(-1, 1)
        y = np.array([float(log['total_output']) for log in valid_logs])
        
        # Train the model on overall factory performance
        model = LinearRegression().fit(X, y)
        
        # Predict factory output for today
        next_index = np.array([[len(valid_logs)]])
        raw_output = float(model.predict(next_index)[0])
        
        # Factor in day-of-week operations
        dow = today.weekday()
        dow_mult = 0.0 if dow == 6 else (0.58 if dow == 5 else 1.0)
        predicted_output = max(0.0 if dow == 6 else 1200.0, round(raw_output * dow_mult, 2))
        
        return {
            "predicted_factory_output_kg": round(predicted_output, 2),
            "status": "ML predicted (Live DB)"
        }
    except Exception as exc:
        logger.warning("Error predicting factory production: %s", exc)
        from apps.production.models import SystemOverview
        recent_so = SystemOverview.objects.filter(total_output_kg__gt=0).order_by('-date').first()
        live_val = float(recent_so.total_output_kg) if recent_so and recent_so.total_output_kg else 5200.0
        return {
            "predicted_factory_output_kg": round(live_val, 2),
            "status": "Live DB Fallback"
        }
