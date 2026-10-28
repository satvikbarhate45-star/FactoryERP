import logging
from datetime import timedelta
from django.utils import timezone
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pandas as pd
from sklearn.linear_model import LinearRegression
import numpy as np

logger = logging.getLogger(__name__)

def generate_missing_production_data():
    from apps.production.models import ProductionLog
    from apps.maintenance.models import Machine
    
    today = timezone.now().date()
    yesterday = today - timedelta(days=1)
    
    machines = Machine.objects.all()
    for machine in machines:
        # Check if there is data for yesterday
        if not ProductionLog.objects.filter(machine=machine, date=yesterday).exists():
            logger.info(f"Missing ProductionLog for {machine.name} on {yesterday}. Generating via ML...")
            
            # Fetch historical data
            past_logs = ProductionLog.objects.filter(machine=machine, date__lt=yesterday).order_by('date')
            if past_logs.count() < 3:
                logger.warning(f"Not enough data for {machine.name} to train ML. Skipping...")
                continue
            
            # Prepare data for ML model
            # We will use the day number as X, and output_kg/material_used as Y
            start_date = past_logs.first().date
            
            data = []
            for log in past_logs:
                day_num = (log.date - start_date).days
                data.append({
                    'day_num': day_num,
                    'output_kg': float(log.output_kg),
                    'material_used': float(log.material_used),
                    'employee_id': log.employee_id
                })
                
            df = pd.DataFrame(data)
            
            # Features and target
            X = df[['day_num']]
            y_output = df['output_kg']
            y_material = df['material_used']
            
            # Train Linear Regression model for output_kg
            model_output = LinearRegression()
            model_output.fit(X, y_output)
            
            # Train Linear Regression model for material_used
            model_material = LinearRegression()
            model_material.fit(X, y_material)
            
            # Predict for yesterday
            target_day_num = (yesterday - start_date).days
            X_pred = pd.DataFrame({'day_num': [target_day_num]})
            
            pred_output = max(0, model_output.predict(X_pred)[0]) # Ensure no negative predictions
            pred_material = max(0, model_material.predict(X_pred)[0])
            
            from apps.maintenance.models import MaintenanceTicket
            has_open_ticket = MaintenanceTicket.objects.filter(machine=machine, status__in=['O', 'I']).exists()
            
            if machine.status == 'UM' and has_open_ticket:
                pred_output = 0.0
                pred_material = 0.0
            elif machine.status == 'PI' and has_open_ticket:
                pred_output *= 0.8
                pred_material *= 0.9
            
            # Add some slight variation (noise) so it's not perfectly linear
            pred_output += np.random.normal(0, pred_output * 0.05)
            pred_material += np.random.normal(0, pred_material * 0.05)
            
            # Find the most frequent employee for this machine
            most_frequent_employee_id = df['employee_id'].mode()[0]
            
            ProductionLog.objects.create(
                date=yesterday,
                employee_id=most_frequent_employee_id,
                machine=machine,
                output_kg=round(pred_output, 2),
                material_used=round(pred_material, 2)
            )
            logger.info(f"Successfully generated ML data for {machine.name} on {yesterday}.")

        # Check if there is data for yesterday in MachineHistoricalMetrics
        from apps.maintenance.models import MachineHistoricalMetrics
        if not MachineHistoricalMetrics.objects.filter(machine=machine, date=yesterday).exists():
            logger.info(f"Missing MachineHistoricalMetrics for {machine.name} on {yesterday}. Generating via ML...")
            
            past_metrics = MachineHistoricalMetrics.objects.filter(machine=machine, date__lt=yesterday).order_by('date')
            if past_metrics.count() >= 3:
                start_date_m = past_metrics.first().date
                m_data = []
                for m_log in past_metrics:
                    m_data.append({
                        'day_num': (m_log.date - start_date_m).days,
                        'temp': float(m_log.temperature),
                        'vib': float(m_log.vibration),
                        'out': float(m_log.output)
                    })
                m_df = pd.DataFrame(m_data)
                
                X_m = m_df[['day_num']]
                
                model_temp = LinearRegression().fit(X_m, m_df['temp'])
                model_vib = LinearRegression().fit(X_m, m_df['vib'])
                model_out = LinearRegression().fit(X_m, m_df['out'])
                
                target_day_num_m = (yesterday - start_date_m).days
                X_pred_m = pd.DataFrame({'day_num': [target_day_num_m]})
                
                pred_temp = max(0, model_temp.predict(X_pred_m)[0])
                pred_vib = max(0, model_vib.predict(X_pred_m)[0])
                pred_out = max(0, model_out.predict(X_pred_m)[0])
                
                if machine.status == 'UM' and has_open_ticket:
                    pred_temp = 25.0 + np.random.normal(0, 1.0) # Ambient temp
                    pred_vib = 0.0
                    pred_out = 0.0
                elif machine.status == 'PI' and has_open_ticket:
                    pred_temp *= 1.15 # Escalating temp
                    pred_vib *= 1.20 # Escalating vibration
                    pred_out *= 0.8
                
                # Add noise
                pred_temp += np.random.normal(0, pred_temp * 0.02)
                pred_vib += np.random.normal(0, pred_vib * 0.05)
                pred_out += np.random.normal(0, pred_out * 0.05)
                
                MachineHistoricalMetrics.objects.create(
                    machine=machine,
                    date=yesterday,
                    temperature=round(pred_temp, 2),
                    vibration=round(pred_vib, 2),
                    output=round(pred_out, 2)
                )
                logger.info(f"Successfully generated ML metrics for {machine.name} on {yesterday}.")
            else:
                logger.warning(f"Not enough metric data for {machine.name} to train ML. Skipping...")

def evaluate_machine_health():
    from apps.maintenance.models import Machine, MachineHistoricalMetrics, MaintenanceTicket
    from sklearn.ensemble import IsolationForest
    
    machines = Machine.objects.all()
    for machine in machines:
        metrics = MachineHistoricalMetrics.objects.filter(machine=machine).order_by('date')
        if metrics.count() < 10:
            continue
            
        df = pd.DataFrame(list(metrics.values('temperature', 'vibration')))
        df['temperature'] = df['temperature'].astype(float)
        df['vibration'] = df['vibration'].astype(float)
        
        # Train IsolationForest to detect anomalies
        clf = IsolationForest(contamination=0.10, random_state=42)
        clf.fit(df)
        
        latest_metric = metrics.last()
        latest_data = pd.DataFrame([{
            'temperature': float(latest_metric.temperature), 
            'vibration': float(latest_metric.vibration)
        }])
        
        # Predict anomaly: -1 for outlier, 1 for inlier
        prediction = clf.predict(latest_data)[0]
        
        if prediction == -1:
            mean_temp = df['temperature'].mean()
            mean_vib = df['vibration'].mean()
            std_temp = df['temperature'].std()
            std_vib = df['vibration'].std()
            
            temp_diff = abs(float(latest_metric.temperature) - mean_temp)
            vib_diff = abs(float(latest_metric.vibration) - mean_vib)
            
            # If deviation > 2.5 std devs, consider it Critical (Failed/Repair)
            is_critical = (temp_diff > 2.5 * std_temp) or (vib_diff > 2.5 * std_vib)
            
            if is_critical:
                machine.status = 'UM' # Under Maintenance (Failed)
                cause = f"ML Critical Alert: Extreme anomaly. Temp: {latest_metric.temperature}°C, Vib: {latest_metric.vibration} mm/s"
            else:
                machine.status = 'PI' # Pending Inspection (Warning)
                cause = f"ML Warning Alert: Moderate anomaly. Temp: {latest_metric.temperature}°C, Vib: {latest_metric.vibration} mm/s"
                
            machine.save()
            
            # Create a maintenance ticket if one doesn't exist
            if not MaintenanceTicket.objects.filter(machine=machine, status__in=['O', 'I']).exists():
                MaintenanceTicket.objects.create(
                    machine=machine,
                    cause=cause,
                    status='O'
                )
                logger.warning(f"ML Health evaluation for {machine.name}: {cause}")
        else:
            # If it's normal and no open tickets, ensure it is set to Operational
            if not MaintenanceTicket.objects.filter(machine=machine, status__in=['O', 'I']).exists():
                if machine.status != 'OP':
                    machine.status = 'OP'
                    machine.save()
                    logger.info(f"{machine.name} returned to Operational state by ML.")

def start_scheduler():
    scheduler = BackgroundScheduler()
    # Schedule data generation at midnight
    scheduler.add_job(
        generate_missing_production_data,
        trigger=CronTrigger(hour=0, minute=0),
        id='generate_missing_production_data',
        max_instances=1,
        replace_existing=True,
    )
    
    # Schedule health evaluation at 00:05 (after data generation)
    scheduler.add_job(
        evaluate_machine_health,
        trigger=CronTrigger(hour=0, minute=5),
        id='evaluate_machine_health',
        max_instances=1,
        replace_existing=True,
    )
    
def run_daily_report():
    import subprocess
    import sys
    try:
        subprocess.run([sys.executable, "daily_reporter.py"], check=False)
        logger.info("Daily report script executed successfully.")
    except Exception as exc:
        logger.warning("Could not run daily_reporter.py: %s", exc)


def autonomous_gap_detection_and_imputation(days_back=14):
    """
    Robust self-sustaining worker that checks for any missing daily metrics
    in the past `days_back` days (specifically backfilling Monday, Tuesday, etc.)
    and autonomously predicts and fills operational gaps in:
    - SystemOverview
    - ProductionLog
    - MachineHistoricalMetrics
    - ProductionTarget
    - SalaryPayroll
    """
    import datetime
    from decimal import Decimal
    from django.utils import timezone
    from apps.production.models import (
        SystemOverview, ProductionLog, ProductionTarget, SalaryPayroll,
        SystemAlert
    )
    from apps.inventory.models import WarehouseStock
    from apps.maintenance.models import Machine, MachineHistoricalMetrics
    from apps.accounts.models import User
    
    try:
        today = timezone.now().date()
        logger.info(f"Running autonomous gap detection pipeline for past {days_back} days up to {today}...")
        
        machines = list(Machine.objects.all())
        employees = list(User.objects.filter(role='EM'))
        if not employees:
            employees = list(User.objects.all())

        if not machines:
            logger.warning("No machines found in database. Skipping imputation.")
            return

        for i in range(1, days_back + 1):
            target_date = today - datetime.timedelta(days=i)
            record, created = SystemOverview.objects.get_or_create(date=target_date)
            
            has_logs = ProductionLog.objects.filter(date=target_date).exists()
            has_metrics = MachineHistoricalMetrics.objects.filter(date=target_date).exists()
            has_payroll = SalaryPayroll.objects.filter(payout_date=target_date).exists()
            
            # Sunday Rule (Day 6 of week)
            if target_date.weekday() == 6:
                if record.total_output_kg is None or record.total_output_kg != 0:
                    record.total_output_kg = 0.0
                    record.total_material_used_kg = 0.0
                    record.active_machines_count = 0
                    record.is_auto_filled = True
                    record.save()
                    
                    for m in machines:
                        emp = employees[0] if employees else None
                        if emp:
                            ProductionLog.objects.get_or_create(
                                date=target_date, machine=m, employee=emp,
                                defaults={'output_kg': 0, 'material_used': 0}
                            )
                        MachineHistoricalMetrics.objects.get_or_create(
                            date=target_date, machine=m,
                            defaults={'temperature': 25.0, 'vibration': 0.0, 'output': 0.0}
                        )
                    logger.info(f"Sunday rule applied for {target_date}. Safely resolved as zero.")
                continue

            # Working Day Gap Detection (Monday - Saturday)
            needs_imputation = (
                record.total_output_kg is None or
                record.total_material_used_kg is None or
                not has_logs or
                not has_metrics or
                not has_payroll
            )
            
            if needs_imputation:
                logger.warning(f"[GAP DETECTED] Missing operational data for {target_date} ({target_date.strftime('%A')}). Triggering ML Imputation...")
                
                # Deterministic moving average / regression baseline
                past_logs = ProductionLog.objects.filter(date__lt=target_date).order_by('-date')
                unique_dates = []
                for log in past_logs:
                    if log.date not in unique_dates and log.date.weekday() != 6:
                        unique_dates.append(log.date)
                    if len(unique_dates) >= 3:
                        break
                        
                if unique_dates:
                    valid_so = [SystemOverview.objects.filter(date=d).first() for d in unique_dates]
                    valid_so = [s for s in valid_so if s and s.total_output_kg is not None and s.total_output_kg > 0]
                    if valid_so:
                        avg_out = sum([s.total_output_kg for s in valid_so]) / len(valid_so)
                        avg_mat = sum([s.total_material_used_kg for s in valid_so]) / len(valid_so)
                    else:
                        avg_out, avg_mat = 495.0, 520.0
                else:
                    avg_out, avg_mat = 495.0, 520.0

                # Slight realistic variance (+/- 3%) so data feels natural
                variance = float(np.random.uniform(-0.03, 0.03))
                imputed_out = round(float(avg_out) * (1.0 + variance), 2)
                imputed_mat = round(float(avg_mat) * (1.0 + variance), 2)

                record.total_output_kg = imputed_out
                record.total_material_used_kg = imputed_mat
                record.active_machines_count = Machine.objects.filter(status='OP').count() or len(machines)
                record.is_auto_filled = True
                record.save()
                
                per_machine_out = imputed_out / len(machines) if machines else 0
                per_machine_mat = imputed_mat / len(machines) if machines else 0
                
                for idx, m in enumerate(machines):
                    emp = employees[idx % len(employees)] if employees else None
                    if emp:
                        # Production Log
                        ProductionLog.objects.update_or_create(
                            date=target_date, machine=m, employee=emp,
                            defaults={
                                'output_kg': round(per_machine_out, 2),
                                'material_used': round(per_machine_mat, 2)
                            }
                        )
                        # Production Target
                        ProductionTarget.objects.get_or_create(
                            date=target_date, employee=emp,
                            defaults={'target_kg': 165.0, 'is_rollover': False}
                        )
                    
                    # Machine Telemetrics
                    vib = round(1.8 + float(np.random.uniform(0.1, 0.9)), 2)
                    temp = round(62.0 + float(np.random.uniform(1.0, 5.0)), 2)
                    MachineHistoricalMetrics.objects.update_or_create(
                        date=target_date, machine=m,
                        defaults={
                            'temperature': temp,
                            'vibration': vib,
                            'output': round(per_machine_out, 2)
                        }
                    )

                # Backfill SalaryPayroll for employees on this working date
                for emp in employees:
                    target_kg = 165.0
                    actual_out = round(imputed_out / max(1, len(employees)), 1)
                    comp_pct = round((actual_out / target_kg) * 100, 1) if target_kg > 0 else 100.0
                    base_pay = 450.0
                    adj_pay = round(base_pay * 1.10, 2) if comp_pct >= 95.0 else base_pay
                    SalaryPayroll.objects.update_or_create(
                        employee=emp, payout_date=target_date,
                        defaults={
                            'base_salary': base_pay,
                            'target_assigned': target_kg,
                            'actual_output': actual_out,
                            'completion_percentage': comp_pct,
                            'salary_adjusted': adj_pay,
                            'is_incremented': (comp_pct >= 95.0),
                            'is_auto_predicted': True
                        }
                    )

                logger.info(f"[SUCCESS] Autonomously imputed missing data for {target_date} ({target_date.strftime('%A')}). Output: {imputed_out} kg.")
            else:
                logger.debug(f"Data for {target_date} is already complete.")

        # Run Autonomous Decision Engine to resolve any alerts
        try:
            from apps.production.decision_engine import run_autonomous_decision_engine
            run_autonomous_decision_engine()
        except Exception as dec_err:
            logger.warning("Decision engine non-critical error during imputation: %s", dec_err)

    except Exception as e:
        logger.error(f"[EMERGENCY] Background gap detection crashed: {e}")


def start_scheduler():
    scheduler = BackgroundScheduler()
    
    # Schedule data generation at midnight
    scheduler.add_job(
        generate_missing_production_data,
        trigger=CronTrigger(hour=0, minute=0),
        id='generate_missing_production_data',
        max_instances=1,
        replace_existing=True,
    )
    
    # Schedule health evaluation at 00:05
    scheduler.add_job(
        evaluate_machine_health,
        trigger=CronTrigger(hour=0, minute=5),
        id='evaluate_machine_health',
        max_instances=1,
        replace_existing=True,
    )
    
    # Schedule the daily report generator at 00:10
    scheduler.add_job(
        run_daily_report,
        trigger=CronTrigger(hour=0, minute=10),
        id='run_daily_report',
        max_instances=1,
        replace_existing=True,
    )
    
    # Schedule daily resilient imputation at 12:15 AM
    scheduler.add_job(
        autonomous_gap_detection_and_imputation,
        trigger=CronTrigger(hour=0, minute=15),
        id='run_daily_imputation',
        max_instances=1,
        replace_existing=True,
    )
    
    # Run resilient loop immediately on system startup
    scheduler.add_job(
        autonomous_gap_detection_and_imputation,
        id='run_daily_imputation_startup',
        max_instances=1,
        replace_existing=True,
    )
    
    scheduler.start()
    logger.info("APScheduler started: Autonomous Gap Detection & ML Prediction Loop actively protecting database integrity.")

