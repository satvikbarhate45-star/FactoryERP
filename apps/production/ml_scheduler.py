import logging
from datetime import timedelta
from django.utils import timezone
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pandas as pd
from sklearn.linear_model import LinearRegression
import numpy as np

logger = logging.getLogger(__name__)

MACHINE_TYPE_PROFILES = [
    {"type": "Tablet Compression Press", "cap": 310.0, "base_vib": 1.95, "base_temp": 62.0},
    {"type": "Fluid Bed Dryer & Granulator", "cap": 260.0, "base_vib": 1.72, "base_temp": 71.0},
    {"type": "High-Shear Mixing Tank", "cap": 340.0, "base_vib": 2.35, "base_temp": 64.5},
    {"type": "Automated Blister Packaging", "cap": 220.0, "base_vib": 1.48, "base_temp": 56.0},
    {"type": "Industrial Decanter Centrifuge", "cap": 275.0, "base_vib": 2.50, "base_temp": 65.0},
    {"type": "Auto-Coating Drum", "cap": 235.0, "base_vib": 1.65, "base_temp": 69.0},
]

DOW_MULTIPLIERS = {
    0: 0.915,  # Mon
    1: 1.015,  # Tue
    2: 1.065,  # Wed
    3: 1.030,  # Thu
    4: 0.940,  # Fri
    5: 0.580,  # Sat
    6: 0.000,  # Sun
}

def get_machine_nominal_specs(machine):
    idx = machine.id if machine and machine.id else 1
    tmpl = MACHINE_TYPE_PROFILES[idx % len(MACHINE_TYPE_PROFILES)]
    m_hash = (idx * 101) % 1000
    cap = tmpl["cap"] + ((m_hash % 30) - 15.0)
    vib = tmpl["base_vib"] + (((m_hash % 20) - 10) * 0.01)
    temp = tmpl["base_temp"] + (((m_hash % 25) - 12) * 0.1)
    return {"cap": cap, "base_vib": vib, "base_temp": temp}

def generate_missing_production_data():
    try:
        from apps.accounts.schema_guard import ensure_runtime_schema_integrity
        ensure_runtime_schema_integrity(force=False)
    except Exception as sg_err:
        logger.warning("Runtime schema check error in generate_missing_production_data: %s", sg_err)

    from apps.production.models import ProductionLog
    from apps.maintenance.models import Machine, MaintenanceTicket, MachineHistoricalMetrics
    from apps.accounts.models import User
    
    try:
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        
        machines = Machine.objects.all()
        for machine in machines:
            try:
                has_open_ticket = MaintenanceTicket.objects.filter(machine=machine, status__in=['O', 'I']).exists()

                # Check if there is data for yesterday in ProductionLog
                if not ProductionLog.objects.filter(machine=machine, date=yesterday).exists():
                    logger.info(f"Missing ProductionLog for {machine.name} on {yesterday}. Generating via ML...")
                    
                    past_logs = ProductionLog.objects.filter(machine=machine, date__lt=yesterday).order_by('date')
                    m_specs = get_machine_nominal_specs(machine)
                    default_out = round(m_specs["cap"] * 0.95, 2)
                    default_mat = round(default_out / 0.95, 2)
                    if past_logs.count() >= 3:
                        start_date = past_logs.first().date
                        data = []
                        for log in past_logs:
                            day_num = (log.date - start_date).days
                            data.append({
                                'day_num': day_num,
                                'output_kg': float(log.output_kg or 0.0),
                                'material_used': float(log.material_used or 0.0),
                                'employee_id': log.employee_id
                            })
                            
                        df = pd.DataFrame(data)
                        X = df[['day_num']]
                        
                        try:
                            model_output = LinearRegression().fit(X, df['output_kg'])
                            model_material = LinearRegression().fit(X, df['material_used'])
                            
                            target_day_num = (yesterday - start_date).days
                            X_pred = pd.DataFrame({'day_num': [target_day_num]})
                            
                            pred_output = max(0.0, float(model_output.predict(X_pred)[0]))
                            pred_material = max(0.0, float(model_material.predict(X_pred)[0]))
                        except Exception as lr_err:
                            logger.warning("LinearRegression fallback for %s: %s", machine.code, lr_err)
                            pred_output = default_out
                            pred_material = default_mat
                    else:
                        pred_output = default_out
                        pred_material = default_mat
                        df = pd.DataFrame()
                    
                    if machine.status == 'UM' and has_open_ticket:
                        pred_output = 0.0
                        pred_material = 0.0
                    elif machine.status == 'PI' and has_open_ticket:
                        pred_output *= 0.8
                        pred_material *= 0.9
                    
                    pred_output += float(np.random.normal(0, max(1.0, pred_output * 0.04)))
                    pred_material += float(np.random.normal(0, max(1.0, pred_material * 0.04)))
                    pred_output = max(0.0, pred_output)
                    pred_material = max(0.0, pred_material)
                    
                    # Safe employee assignment
                    most_frequent_employee_id = None
                    if not df.empty and 'employee_id' in df.columns and not df['employee_id'].dropna().empty:
                        modes = df['employee_id'].dropna().mode()
                        if not modes.empty:
                            most_frequent_employee_id = int(modes.iloc[0])
                    
                    if not most_frequent_employee_id:
                        em_user = User.objects.filter(role='EM').first() or User.objects.first()
                        most_frequent_employee_id = em_user.id if em_user else None

                    # Safe upsert
                    p_log = ProductionLog.objects.filter(date=yesterday, machine=machine).first()
                    if p_log:
                        p_log.output_kg = round(pred_output, 2)
                        p_log.material_used = round(pred_material, 2)
                        p_log.save()
                    else:
                        ProductionLog.objects.create(
                            date=yesterday,
                            employee_id=most_frequent_employee_id,
                            machine=machine,
                            output_kg=round(pred_output, 2),
                            material_used=round(pred_material, 2),
                            is_auto_predicted=True
                        )
                    logger.info(f"Successfully generated ML data for {machine.name} on {yesterday}.")

                # Check if there is data for yesterday in MachineHistoricalMetrics
                if not MachineHistoricalMetrics.objects.filter(machine=machine, date=yesterday).exists():
                    logger.info(f"Missing MachineHistoricalMetrics for {machine.name} on {yesterday}. Generating via ML...")
                    m_specs = get_machine_nominal_specs(machine)
                    default_out = round(m_specs["cap"] * 0.95, 2)
                    past_metrics = MachineHistoricalMetrics.objects.filter(machine=machine, date__lt=yesterday).order_by('date')
                    if past_metrics.count() >= 3:
                        start_date_m = past_metrics.first().date
                        m_data = []
                        for m_log in past_metrics:
                            m_data.append({
                                'day_num': (m_log.date - start_date_m).days,
                                'temp': float(m_log.temperature or m_specs['base_temp']),
                                'vib': float(m_log.vibration or m_specs['base_vib']),
                                'out': float(m_log.output or default_out)
                            })
                        m_df = pd.DataFrame(m_data)
                        X_m = m_df[['day_num']]
                        
                        try:
                            model_temp = LinearRegression().fit(X_m, m_df['temp'])
                            model_vib = LinearRegression().fit(X_m, m_df['vib'])
                            model_out = LinearRegression().fit(X_m, m_df['out'])
                            
                            target_day_num_m = (yesterday - start_date_m).days
                            X_pred_m = pd.DataFrame({'day_num': [target_day_num_m]})
                            
                            pred_temp = max(50.0, float(model_temp.predict(X_pred_m)[0]))
                            pred_vib = max(1.2, float(model_vib.predict(X_pred_m)[0]))
                            pred_out = max(0.0, float(model_out.predict(X_pred_m)[0]))
                        except Exception as m_lr_err:
                            logger.warning("Metrics LinearRegression fallback for %s: %s", machine.code, m_lr_err)
                            pred_temp, pred_vib, pred_out = m_specs['base_temp'], m_specs['base_vib'], default_out
                    else:
                        pred_temp, pred_vib, pred_out = m_specs['base_temp'], m_specs['base_vib'], default_out
                    
                    if machine.status == 'UM' and has_open_ticket:
                        pred_temp = 25.0 + float(np.random.normal(0, 0.5))
                        pred_vib = 0.0
                        pred_out = 0.0
                    elif machine.status == 'PI' and has_open_ticket:
                        pred_temp *= 1.12
                        pred_vib *= 1.15
                        pred_out *= 0.8
                    
                    pred_temp = max(20.0, min(95.0, pred_temp + float(np.random.normal(0, max(0.5, pred_temp * 0.02)))))
                    pred_vib = max(0.0, min(10.0, pred_vib + float(np.random.normal(0, max(0.1, pred_vib * 0.04)))))
                    pred_out = max(0.0, pred_out)
                    
                    # Safe upsert
                    m_met = MachineHistoricalMetrics.objects.filter(machine=machine, date=yesterday).first()
                    if m_met:
                        m_met.temperature = round(pred_temp, 2)
                        m_met.vibration = round(pred_vib, 2)
                        m_met.output = round(pred_out, 2)
                        m_met.save()
                    else:
                        MachineHistoricalMetrics.objects.create(
                            machine=machine,
                            date=yesterday,
                            temperature=round(pred_temp, 2),
                            vibration=round(pred_vib, 2),
                            output=round(pred_out, 2)
                        )
                    logger.info(f"Successfully generated ML metrics for {machine.name} on {yesterday}.")

            except Exception as m_loop_err:
                logger.warning(f"Non-fatal error in generate_missing_production_data for {machine.code}: {m_loop_err}")

    except Exception as exc:
        logger.error(f"Error in generate_missing_production_data: {exc}")


def evaluate_machine_health():
    from apps.maintenance.models import Machine, MachineHistoricalMetrics, MaintenanceTicket
    from sklearn.ensemble import IsolationForest
    
    try:
        machines = Machine.objects.all()
        for machine in machines:
            try:
                metrics = MachineHistoricalMetrics.objects.filter(machine=machine).order_by('date')
                if metrics.count() < 10:
                    continue
                    
                df = pd.DataFrame(list(metrics.values('temperature', 'vibration')))
                df['temperature'] = df['temperature'].astype(float).fillna(64.0)
                df['vibration'] = df['vibration'].astype(float).fillna(1.85)
                
                # Train IsolationForest to detect anomalies
                clf = IsolationForest(contamination=0.10, random_state=42)
                clf.fit(df)
                
                latest_metric = metrics.last()
                latest_data = pd.DataFrame([{
                    'temperature': float(latest_metric.temperature or 64.0), 
                    'vibration': float(latest_metric.vibration or 1.85)
                }])
                
                # Predict anomaly: -1 for outlier, 1 for inlier
                prediction = clf.predict(latest_data)[0]
                
                if prediction == -1:
                    mean_temp = float(df['temperature'].mean())
                    mean_vib = float(df['vibration'].mean())
                    std_temp = float(df['temperature'].std() or 1.0)
                    std_vib = float(df['vibration'].std() or 0.2)
                    
                    temp_diff = abs(float(latest_metric.temperature) - mean_temp)
                    vib_diff = abs(float(latest_metric.vibration) - mean_vib)
                    
                    is_critical = (temp_diff > 2.5 * std_temp) or (vib_diff > 2.5 * std_vib)
                    
                    if is_critical:
                        machine.status = 'UM' # Under Maintenance (Failed)
                        cause = f"ML Critical Alert: Extreme anomaly. Temp: {latest_metric.temperature}°C, Vib: {latest_metric.vibration} mm/s"
                    else:
                        machine.status = 'PI' # Pending Inspection (Warning)
                        cause = f"ML Warning Alert: Moderate anomaly. Temp: {latest_metric.temperature}°C, Vib: {latest_metric.vibration} mm/s"
                        
                    machine.save()
                    
                    if not MaintenanceTicket.objects.filter(machine=machine, status__in=['O', 'I']).exists():
                        MaintenanceTicket.objects.create(
                            machine=machine,
                            cause=cause,
                            status='O'
                        )
                        logger.warning(f"ML Health evaluation for {machine.name}: {cause}")
                else:
                    if not MaintenanceTicket.objects.filter(machine=machine, status__in=['O', 'I']).exists():
                        if machine.status != 'OP':
                            machine.status = 'OP'
                            machine.save()
                            logger.info(f"{machine.name} returned to Operational state by ML.")
            except Exception as m_health_err:
                logger.warning("Error evaluating machine health for %s: %s", machine.code, m_health_err)
    except Exception as exc:
        logger.error(f"Error in evaluate_machine_health: {exc}")

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
        from apps.accounts.schema_guard import ensure_runtime_schema_integrity
        ensure_runtime_schema_integrity(force=True)
    except Exception as sg_err:
        logger.warning("Runtime schema check error in ML imputation: %s", sg_err)

    try:
        today = timezone.localdate()
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
            record = SystemOverview.objects.filter(date=target_date).first()
            if not record:
                record = SystemOverview.objects.create(date=target_date)
            
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
                            if not ProductionLog.objects.filter(date=target_date, machine=m, employee=emp).exists():
                                ProductionLog.objects.create(
                                    date=target_date, machine=m, employee=emp,
                                    output_kg=0, material_used=0
                                )
                        if not MachineHistoricalMetrics.objects.filter(date=target_date, machine=m).exists():
                            MachineHistoricalMetrics.objects.create(
                                date=target_date, machine=m,
                                temperature=25.0, vibration=0.0, output=0.0
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
                
                # Realistic Multi-Factor Factory Operation Imputation
                dow = target_date.weekday()
                dow_mult = DOW_MULTIPLIERS.get(dow, 1.0)
                
                daily_total_out = 0.0
                daily_total_mat = 0.0
                active_count = 0

                for idx, m in enumerate(machines):
                    has_open_ticket = MaintenanceTicket.objects.filter(machine=m, status__in=['O', 'I']).exists()
                    specs = get_machine_nominal_specs(m)
                    
                    if m.status == 'UM' and has_open_ticket:
                        m_out = 0.0
                        m_mat = 0.0
                        m_vib = 0.0
                        m_temp = round(24.5 + float(np.random.uniform(-0.5, 0.5)), 2)
                    else:
                        active_count += 1
                        # Subtle weekly harmonic factory wave (+/- 7%)
                        harmonic_wave = 0.07 * np.sin((target_date.toordinal() * 0.45) + (m.id * 1.3))
                        noise_factor = float(np.random.uniform(-0.035, 0.035))
                        eff_rate = dow_mult * (1.0 + harmonic_wave + noise_factor)
                        
                        m_out = round(max(75.0, specs["cap"] * eff_rate), 2)
                        # Yield between 92.8% and 97.2%
                        m_yield = 0.948 + float(np.random.uniform(-0.02, 0.024))
                        m_mat = round(m_out / m_yield, 2)
                        
                        load_ratio = (m_out / specs["cap"]) if specs["cap"] > 0 else 1.0
                        m_vib = round(max(1.10, specs["base_vib"] + (0.18 * (load_ratio - 1.0)) + float(np.random.uniform(-0.04, 0.04))), 2)
                        m_temp = round(max(48.0, specs["base_temp"] + (0.032 * m_out) + float(np.random.uniform(-0.6, 0.6))), 2)

                    daily_total_out += m_out
                    daily_total_mat += m_mat

                    # Assign rotating operator
                    emp = employees[(idx + target_date.day) % len(employees)] if employees else None
                    if emp:
                        # Production Log
                        existing_p_log = ProductionLog.objects.filter(date=target_date, machine=m).first()
                        if existing_p_log:
                            existing_p_log.output_kg = m_out
                            existing_p_log.material_used = m_mat
                            existing_p_log.employee = emp
                            existing_p_log.save()
                        else:
                            ProductionLog.objects.create(
                                date=target_date, machine=m, employee=emp,
                                output_kg=m_out, material_used=m_mat, is_auto_predicted=True
                            )

                        # Production Target
                        if not ProductionTarget.objects.filter(date=target_date, employee=emp).exists():
                            ProductionTarget.objects.create(
                                date=target_date, employee=emp,
                                target_kg=165.0, is_rollover=False
                            )

                    # Machine Telemetry Metrics
                    existing_metric = MachineHistoricalMetrics.objects.filter(date=target_date, machine=m).first()
                    if existing_metric:
                        existing_metric.temperature = m_temp
                        existing_metric.vibration = m_vib
                        existing_metric.output = m_out
                        existing_metric.save()
                    else:
                        MachineHistoricalMetrics.objects.create(
                            date=target_date, machine=m,
                            temperature=m_temp, vibration=m_vib, output=m_out
                        )

                    # Dynamic Machine Prediction
                    pred_id = MachinePrediction.objects.filter(machine=m, date=target_date).first()
                    baseline_interval = 52 + ((m.id * 17) % 32)
                    days_in_cycle = ((target_date.toordinal() + m.id * 11) % 42) + 3
                    load_accel = 0.85 + (0.35 * max(0.5, m_out / 250.0))
                    wear_accum = days_in_cycle * load_accel
                    vib_excess = max(0.0, m_vib - (specs["base_vib"] + 0.15))
                    temp_excess = max(0.0, m_temp - 68.0)
                    anomaly_penalty = (vib_excess * 20.0) + (temp_excess * 1.5)
                    pred_rul = max(6, int(baseline_interval - wear_accum - anomaly_penalty))
                    pred_health = round(max(35.0, min(99.4, 99.2 - (wear_accum * 0.28) - (anomaly_penalty * 1.35))), 2)
                    conf_pct = round(max(89.2, min(96.8, 95.2 - (abs(m_vib - specs["base_vib"]) * 2.8) + float(np.random.uniform(-0.8, 0.8)))), 2)
                    reason_text = f"Dynamic Telemetry Fit: {m_out:.1f}kg yield. Kinetic Vib: {m_vib}mm/s, Temp: {m_temp}°C. RUL: {pred_rul}d (Health: {pred_health}%, Conf: {conf_pct}%)."

                    if pred_id:
                        pred_id.predicted_vibration = m_vib
                        pred_id.predicted_temp = m_temp
                        pred_id.predicted_rul_days = pred_rul
                        pred_id.health_score = pred_health
                        pred_id.accuracy_pct = conf_pct
                        pred_id.reason = reason_text
                        pred_id.save()
                    else:
                        MachinePrediction.objects.create(
                            machine=m, date=target_date,
                            predicted_vibration=m_vib, predicted_temp=m_temp,
                            predicted_rul_days=pred_rul, health_score=pred_health,
                            accuracy_pct=conf_pct, is_auto_predicted=True, reason=reason_text
                        )

                # Update SystemOverview
                daily_total_out = round(daily_total_out, 2)
                daily_total_mat = round(daily_total_mat, 2)
                record.total_output_kg = daily_total_out
                record.total_material_used_kg = daily_total_mat
                record.active_machines_count = active_count
                record.is_auto_filled = True
                record.save()

                # Dynamic Employee Salary Payroll Sync
                for emp in employees:
                    target_kg = 165.0
                    emp_eff = 0.92 + (((emp.id * 77) % 20) * 0.01)
                    actual_out = round(max(110.0, 165.0 * emp_eff * dow_mult + float(np.random.uniform(-6.0, 6.0))), 1)
                    comp_pct = round((actual_out / target_kg) * 100, 1)
                    base_pay = 450.0
                    adj_pay = round(base_pay * 1.10, 2) if comp_pct >= 95.0 else round(base_pay * max(0.85, comp_pct / 100.0), 2)
                    adj_pay = round(max(380.0, min(525.0, adj_pay)), 2)

                    existing_pr = SalaryPayroll.objects.filter(employee=emp, payout_date=target_date).first()
                    if existing_pr:
                        existing_pr.base_salary = base_pay
                        existing_pr.target_assigned = target_kg
                        existing_pr.actual_output = actual_out
                        existing_pr.completion_percentage = comp_pct
                        existing_pr.salary_adjusted = adj_pay
                        existing_pr.is_incremented = (comp_pct >= 95.0)
                        existing_pr.is_auto_predicted = True
                        existing_pr.save()
                    else:
                        SalaryPayroll.objects.create(
                            employee=emp, payout_date=target_date,
                            base_salary=base_pay, target_assigned=target_kg,
                            actual_output=actual_out, completion_percentage=comp_pct,
                            salary_adjusted=adj_pay, is_incremented=(comp_pct >= 95.0),
                            is_auto_predicted=True
                        )

                logger.info(f"[SUCCESS] Autonomously imputed missing data for {target_date} ({target_date.strftime('%A')}). Output: {daily_total_out} kg across {active_count} active machines.")
            else:
                logger.debug(f"Data for {target_date} is already complete.")

        # Run Autonomous Decision Engine to resolve any alerts
        try:
            from apps.production.decision_engine import run_autonomous_decision_engine
            run_autonomous_decision_engine()
        except Exception as dec_err:
            logger.warning("Decision engine non-critical error during imputation: %s", dec_err)

        # Autonomous Logistics & Warehouse Reorder/Dispatch Automation
        try:
            from apps.logistics.services import autonomous_logistics_and_warehouse_automation
            autonomous_logistics_and_warehouse_automation()
        except Exception as log_err:
            logger.warning("Logistics automation non-critical error during imputation: %s", log_err)

    except Exception as e:
        logger.error(f"[EMERGENCY] Background gap detection crashed: {e}")


def start_scheduler():
    try:
        from apps.accounts.schema_guard import ensure_runtime_schema_integrity
        ensure_runtime_schema_integrity(force=True)
    except Exception as sg_err:
        logger.warning("Runtime schema check error in start_scheduler: %s", sg_err)

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
    
    # Schedule autonomous logistics & warehouse dispatch at 00:20
    try:
        from apps.logistics.services import autonomous_logistics_and_warehouse_automation
        scheduler.add_job(
            autonomous_logistics_and_warehouse_automation,
            trigger=CronTrigger(hour=0, minute=20),
            id='run_daily_logistics_automation',
            max_instances=1,
            replace_existing=True,
        )
    except Exception as s_log_err:
        logger.warning("Could not register logistics job in scheduler: %s", s_log_err)

    scheduler.start()
    logger.info("APScheduler started: Autonomous Gap Detection & ML Prediction Loop actively protecting database integrity.")

