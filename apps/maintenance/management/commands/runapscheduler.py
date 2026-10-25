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
    machines = Machine.objects.all()
    today = timezone.now().date()
    
    for m in machines:
        # Get last 7 days of history
        recent_history = MachineHistoricalMetrics.objects.filter(
            machine=m, 
            date__gte=today - timedelta(days=7)
        ).order_by('-date')
        
        if len(recent_history) < 3:
            continue # Need more data
            
        # Very simple predictive algorithm: if average vibration trend is rising and > 4.5
        vib_trend = [h.vibration for h in recent_history]
        avg_recent_vib = sum(vib_trend) / len(vib_trend)
        
        predicted_vib = avg_recent_vib + 0.2 # Simple linear drift projection
        predicted_temp = recent_history[0].temperature + 1.5
        
        # Save prediction
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
            MaintenanceTicket.objects.create(
                machine=m,
                cause='Predicted High Vibration (>5.0 mm/s)',
                status='O'
            )
            logger.warning(f"ALERT: {m.code} flagged for critical predictive maintenance!")
            
def rollover_production_targets():
    """FR-2.2: Auto-rollover yesterday's targets to today."""
    logger.info("Running target auto-rollover...")
    yesterday = timezone.now().date() - timedelta(days=1)
    today = timezone.now().date()
    
    past_targets = ProductionTarget.objects.filter(date=yesterday)
    for pt in past_targets:
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
            
def check_warehouse_stock():
    """FR-6.2: Reorder alerts when stock is low."""
    logger.info("Checking warehouse stock levels...")
    low_stock = WarehouseStock.objects.filter(quantity__lte=10000) # Assuming 10k is standard reorder
    for stock in low_stock:
        logger.warning(f"REORDER ALERT: {stock.material} is critically low ({stock.quantity} {stock.unit})")

def auto_fill_missing_data():
    """Fully Automated System: Fills previous day's missing actuals using predictions."""
    logger.info("Running auto-fill missing data job...")
    yesterday = timezone.now().date() - timedelta(days=1)
    
    # Check if data was filled yesterday for machines
    machines = Machine.objects.all()
    if machines.exists():
        for m in machines:
            if not MachineHistoricalMetrics.objects.filter(machine=m, date=yesterday).exists():
                # Get average of last 7 days to auto-fill
                recent = MachineHistoricalMetrics.objects.filter(machine=m, date__lt=yesterday).order_by('-date')[:7]
                if recent:
                    avg_vib = sum(r.vibration for r in recent) / len(recent)
                    avg_temp = sum(r.temperature for r in recent) / len(recent)
                    avg_out = sum(r.output for r in recent) / len(recent)
                else:
                    avg_vib, avg_temp, avg_out = 2.0, 60.0, 250.0
                
                MachineHistoricalMetrics.objects.create(
                    machine=m, date=yesterday,
                    vibration=avg_vib, temperature=avg_temp, output=avg_out
                )
    
    # Check Production Logs
    employees = User.objects.filter(role='EM')
    if not ProductionLog.objects.filter(date=yesterday).exists() and employees.exists() and machines.exists():
        for m in machines:
            # Predict basic production for this machine
            ProductionLog.objects.create(
                date=yesterday,
                employee=employees.order_by('?').first(),
                machine=m,
                material_used=250.0,
                output_kg=245.0
            )
        logger.info(f"Auto-filled ProductionLogs for {yesterday}")

class Command(BaseCommand):
    help = "Runs APScheduler."
    def handle(self, *args, **options):
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
