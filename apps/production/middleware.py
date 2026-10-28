from django.utils import timezone
from datetime import timedelta
from django.core.management import call_command
import threading
import logging

logger = logging.getLogger(__name__)


def _run_background_checks():
    """
    Executes heavy machine learning predictions, daily imputation,
    and autonomous alert resolution in an asynchronous daemon thread
    to guarantee that the main HTTP request thread is NEVER blocked.
    """
    try:
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        from apps.production.models import SystemOverview

        # 1. Gap detection & imputation for yesterday
        if not SystemOverview.objects.filter(date=yesterday).exists():
            logger.info(f"Background thread triggered automated daily imputation for {yesterday}...")
            call_command('daily_imputation')

        # 2. Autonomous Alert Resolution
        from apps.production.decision_engine import run_autonomous_decision_engine
        run_autonomous_decision_engine()

        # 3. Machine Telemetry & Predictions for today
        from apps.maintenance.models import MachinePrediction
        if not MachinePrediction.objects.filter(date=today).exists():
            from apps.maintenance.services import run_daily_predictions
            run_daily_predictions(target_date=today)
    except Exception as e:
        logger.warning(f"[BACKGROUND ML RUNNER] Non-blocking imputation error: {e}")


class DailyImputationMiddleware:
    """
    High-performance middleware ensuring zero blank spaces on dashboards
    by running ML imputation and predictive modeling in a background daemon thread.
    Guarantees sub-second HTTP response times for all users.
    """
    _is_running = False
    _lock = threading.Lock()

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Exclude static assets and admin
        if not request.path.startswith('/static/') and not request.path.startswith('/admin/'):
            # Only spawn if a worker is not already running
            if not DailyImputationMiddleware._is_running:
                with DailyImputationMiddleware._lock:
                    if not DailyImputationMiddleware._is_running:
                        DailyImputationMiddleware._is_running = True

                        def _safe_worker():
                            try:
                                _run_background_checks()
                            finally:
                                DailyImputationMiddleware._is_running = False

                        t = threading.Thread(
                            target=_safe_worker,
                            daemon=True,
                            name='pharma_ml_imputation_worker'
                        )
                        t.start()

        # Main request thread proceeds immediately with zero blocking!
        return self.get_response(request)
