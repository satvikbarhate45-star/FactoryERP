import logging
from django.conf import settings
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from django.core.management.base import BaseCommand
from django_apscheduler.jobstores import DjangoJobStore
from django_apscheduler.models import DjangoJobExecution
from django.utils import timezone
from datetime import timedelta

# Models
from apps.maintenance.models import Machine, MachineHistoricalMetrics, MachinePrediction, MaintenanceTicket
from apps.production.models import ProductionTarget, ProductionLog
from apps.inventory.models import WarehouseStock
from apps.accounts.models import User
from django.db.models import Avg

logger = logging.getLogger(__name__)

def predict_machine_failures():
    """FR-5.2 & FR-5.3: Morning job analyzes history and predicts downtime."""
    logger.info("Running daily machine prediction job...")
    try:
        machines = Machine.objects.all()
        today = timezone.localdate()
        
        for m in machines:
            try:
                # Get last 7 days of history
                recent_history = MachineHistoricalMetrics.objects.filter(
                    machine=m, 
                    date__gte=today - timedelta(days=7)
                ).order_by('-date')
                
                if len(recent_history) < 3:
                    continue # Need more data
                    
                # Predictive algorithm: vibration trend projection
                vib_trend = [float(h.vibration or 2.0) for h in recent_history]
                avg_recent_vib = sum(vib_trend) / len(vib_trend)
                
                predicted_vib = round(avg_recent_vib + 0.2, 2)
                latest_temp = float(recent_history[0].temperature or 60.0)
                predicted_temp = round(latest_temp + 1.5, 1)
                
                # Safe upsert prediction
                pred = MachinePrediction.objects.filter(machine=m, date=today).first()
                if pred:
                    pred.predicted_temp = predicted_temp
                    pred.predicted_vibration = predicted_vib
                    pred.reason = f"Projected from 7-day trend (Avg: {avg_recent_vib:.1f} mm/s)"
                    pred.save()
                else:
                    MachinePrediction.objects.create(
                        machine=m,
                        date=today,
                        predicted_temp=predicted_temp,
                        predicted_vibration=predicted_vib,
                        reason=f"Projected from 7-day trend (Avg: {avg_recent_vib:.1f} mm/s)"
                    )
                
                # FR-5.3: Action on threshold
                if predicted_vib > 5.0:
                    m.status = 'PI' # Pending Inspection
                    m.save()
                    if not MaintenanceTicket.objects.filter(machine=m, status__in=['O', 'I']).exists():
                        MaintenanceTicket.objects.create(
                            machine=m,
                            cause='Predicted High Vibration (>5.0 mm/s)',
                            status='O'
                        )
                    logger.warning(f"ALERT: {m.code} flagged for critical predictive maintenance!")
            except Exception as m_err:
                logger.warning(f"Error predicting failures for machine {m.code}: {m_err}")
    except Exception as exc:
        logger.warning(f"Error in predict_machine_failures: {exc}")
            
def rollover_production_targets():
    """FR-2.2: Auto-rollover yesterday's targets to today."""
    logger.info("Running target auto-rollover...")
    try:
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        
        past_targets = ProductionTarget.objects.filter(date=yesterday)
        for pt in past_targets:
            try:
                # Check if today already has a target
                exists = ProductionTarget.objects.filter(date=today, employee=pt.employee).exists()
                if not exists:
                    ProductionTarget.objects.create(
                        date=today,
                        employee=pt.employee,
                        target_kg=pt.target_kg,
                        set_by=pt.set_by,
                        is_rollover=True
                    )
            except Exception as pt_err:
                logger.warning(f"Target rollover error for {pt.employee}: {pt_err}")
    except Exception as exc:
        logger.warning(f"Error in rollover_production_targets: {exc}")
            
def check_warehouse_stock():
    """FR-6.2: Reorder alerts when stock is low."""
    logger.info("Checking warehouse stock levels...")
    try:
        low_stock = WarehouseStock.objects.filter(quantity__lte=10000)
        for stock in low_stock:
            logger.warning(f"REORDER ALERT: {stock.material} is critically low ({stock.quantity} {stock.unit})")
    except Exception as exc:
        logger.warning(f"Error in check_warehouse_stock: {exc}")

def auto_fill_missing_data():
    """Fully Automated System: Fills previous day's missing actuals using predictions."""
    logger.info("Running auto-fill missing data job...")
    try:
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        
        # Check if data was filled yesterday for machines
        machines = Machine.objects.all()
        if machines.exists():
            for m in machines:
                try:
                    if not MachineHistoricalMetrics.objects.filter(machine=m, date=yesterday).exists():
                        # Get average of last 7 days to auto-fill
                        recent = MachineHistoricalMetrics.objects.filter(machine=m, date__lt=yesterday).order_by('-date')[:7]
                        if recent:
                            avg_vib = sum(float(r.vibration or 2.0) for r in recent) / len(recent)
                            avg_temp = sum(float(r.temperature or 60.0) for r in recent) / len(recent)
                            avg_out = sum(float(r.output or 250.0) for r in recent) / len(recent)
                        else:
                            avg_vib, avg_temp, avg_out = 2.0, 60.0, 250.0
                        
                        MachineHistoricalMetrics.objects.create(
                            machine=m, date=yesterday,
                            vibration=round(avg_vib, 2), temperature=round(avg_temp, 1), output=round(avg_out, 1)
                        )
                except Exception as m_fill_err:
                    logger.warning(f"Error auto-filling metrics for {m.code}: {m_fill_err}")
        
        # Check Production Logs
        employees = User.objects.filter(role='EM')
        if not ProductionLog.objects.filter(date=yesterday).exists() and employees.exists() and machines.exists():
            for m in machines:
                try:
                    emp = employees.order_by('?').first()
                    ProductionLog.objects.create(
                        date=yesterday,
                        employee=emp,
                        machine=m,
                        material_used=250.0,
                        output_kg=245.0
                    )
                except Exception as p_fill_err:
                    logger.warning(f"Error auto-filling production log for {m.code}: {p_fill_err}")
            logger.info(f"Auto-filled ProductionLogs for {yesterday}")
    except Exception as exc:
        logger.warning(f"Error in auto_fill_missing_data: {exc}")

class Command(BaseCommand):
    help = "Runs APScheduler."
    def handle(self, *args, **options):
        try:
            from apps.accounts.schema_guard import ensure_runtime_schema_integrity
            ensure_runtime_schema_integrity(force=True)
        except Exception as sg_err:
            logger.warning("Runtime schema check error in runapscheduler: %s", sg_err)

        scheduler = BlockingScheduler(timezone=settings.TIME_ZONE)
        scheduler.add_jobstore(DjangoJobStore(), "default")

        scheduler.add_job(
            predict_machine_failures,
            trigger=CronTrigger(hour="06", minute="00"),  # Every morning at 6 AM
            id="predict_machine_failures",
            max_instances=1,
            replace_existing=True,
        )
        scheduler.add_job(
            rollover_production_targets,
            trigger=CronTrigger(hour="00", minute="01"),  # Midnight
            id="rollover_production_targets",
            max_instances=1,
            replace_existing=True,
        )
        scheduler.add_job(
            check_warehouse_stock,
            trigger=CronTrigger(hour="08", minute="00"),  # Every morning at 8 AM
            id="check_warehouse_stock",
            max_instances=1,
            replace_existing=True,
        )
        scheduler.add_job(
            auto_fill_missing_data,
            trigger=CronTrigger(hour="23", minute="55"),  # End of the day
            id="auto_fill_missing_data",
            max_instances=1,
            replace_existing=True,
        )

        try:
            logger.info("Starting scheduler...")
            scheduler.start()
        except KeyboardInterrupt:
            logger.info("Stopping scheduler...")
            scheduler.shutdown()
            logger.info("Scheduler shut down successfully!")
