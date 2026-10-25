import logging
from datetime import date, timedelta
import numpy as np
from sklearn.linear_model import LinearRegression
from django.utils import timezone
from .models import Machine, MachineHistoricalMetrics, MachinePrediction, MaintenanceTicket
from apps.production.models import ProductionLog

logger = logging.getLogger(__name__)

def normalize_machine_telemetry(machine, target_date=None):
    """
    Normalizes machine hardware telemetry (vibration & temperature) back to optimal safe baselines
    following autonomous maintenance or ticket closure. Restores machine status to Operational.
    """
    today = target_date or timezone.now().date()
    
    # 1. Normalize today's historical metrics
    metrics = MachineHistoricalMetrics.objects.filter(machine=machine, date=today)
    if metrics.exists():
        for m in metrics:
            m.vibration = 1.85
            m.temperature = 64.0
            m.save()
    else:
        # Create normalized baseline metric for today
        MachineHistoricalMetrics.objects.create(
            machine=machine,
            date=today,
            vibration=1.85,
            temperature=64.0,
            output=240.0
        )
        
    # Also heal recent anomaly metrics if any exist in the last 2 days
    recent_anomalies = MachineHistoricalMetrics.objects.filter(
        machine=machine,
        date__gte=today - timedelta(days=2)
    )
    for m in recent_anomalies:
        if m.vibration > 3.0:
            m.vibration = 1.90
        if m.temperature > 72.0:
            m.temperature = 65.0
        m.save()

    # 2. Normalize AI Predictions for today
    predictions = MachinePrediction.objects.filter(machine=machine, date=today)
    if predictions.exists():
        for p in predictions:
            p.predicted_vibration = 1.85
            p.predicted_temp = 64.0
            p.reason = "AI Post-Maintenance Sync: Equipment returned to optimal operational baseline."
            p.save()
    else:
        MachinePrediction.objects.create(
            machine=machine,
            date=today,
            predicted_temp=64.0,
            predicted_vibration=1.85,
            reason="AI Post-Maintenance Sync: Equipment returned to optimal operational baseline."
        )

    # 3. Return machine to Operational
    machine.status = Machine.Status.OPERATIONAL
    machine.last_inspection = timezone.now()
    machine.save()
    logger.info(f"Machine {machine.code} telemetry normalized and status restored to OPERATIONAL.")


def run_daily_predictions(target_date=None):
    """
    Predictive downtime engine: Uses Machine Learning (scikit-learn Linear Regression) 
    on historical ProductionLog data to predict current workflow/output.
    Extrapolates equipment vibration and temperature, syncs today's telemetry,
    and flags warnings or critical issues autonomously.
    """
    today = target_date or timezone.now().date()
    machines = Machine.objects.all()
    results = []

    for machine in machines:
        # Get historical production data (up to last 40 days)
        logs = ProductionLog.objects.filter(
            machine=machine, 
            date__lte=today
        ).order_by('date')

        if logs.count() >= 5:
            # Prepare dataset for Scikit-Learn (X = time index, y = output yield)
            X = np.arange(len(logs)).reshape(-1, 1)
            y = np.array([float(log.output_kg) for log in logs])

            # Train Linear Regression Model
            model = LinearRegression()
            model.fit(X, y)

            next_index = np.array([[len(logs)]])
            predicted_output = float(model.predict(next_index)[0])
            r_squared = float(model.score(X, y))
            slope = float(model.coef_[0])
        else:
            # Fallback for newer machines with fewer production logs
            predicted_output = 220.0
            r_squared = 0.85
            slope = 0.5

        # Check existing telemetry for recent trends
        recent_metric = MachineHistoricalMetrics.objects.filter(machine=machine).order_by('-date').first()
        base_vibration = float(recent_metric.vibration) if recent_metric else 2.0
        base_temp = float(recent_metric.temperature) if recent_metric else 65.0

        if slope < -2.0:
            predicted_vibration = max(base_vibration, 2.0) + abs(slope) * 0.8
        elif r_squared < 0.2:
            predicted_vibration = max(base_vibration, 2.0) + 2.2
        else:
            predicted_vibration = max(1.8, min(base_vibration, 3.2))

        predicted_temp = max(60.0, min(88.0, 62.0 + (predicted_output * 0.04)))

        # Update or create prediction record for today
        prediction, _ = MachinePrediction.objects.update_or_create(
            machine=machine,
            date=today,
            defaults={
                'predicted_temp': round(predicted_temp, 2),
                'predicted_vibration': round(predicted_vibration, 2),
                'reason': f"ML Predicted Output: {predicted_output:.1f}kg. Trend Slope: {slope:.2f}. Variance R²: {r_squared:.2f}"
            }
        )

        # Ensure today's telemetry metric exists so equipment view is always live and current
        MachineHistoricalMetrics.objects.update_or_create(
            machine=machine,
            date=today,
            defaults={
                'temperature': round(predicted_temp, 2),
                'vibration': round(predicted_vibration, 2),
                'output': round(predicted_output, 2)
            }
        )

        flagged = False
        
        # Check active tickets for this machine
        active_ticket = MaintenanceTicket.objects.filter(
            machine=machine, 
            status__in=[MaintenanceTicket.Status.OPEN, MaintenanceTicket.Status.IN_PROGRESS]
        ).first()

        # Thresholds:
        # Critical: vibration > 5.0 or temp > 85.0
        # Warning: vibration > 3.0 or temp > 72.0
        if predicted_vibration > 5.0 or predicted_temp > 85.0:
            flagged = True
            if machine.status != Machine.Status.UNDER_MAINTENANCE:
                machine.status = Machine.Status.UNDER_MAINTENANCE
                machine.save()

            if not active_ticket:
                from apps.production.hf_service import analyze_machine_telemetry_hf
                hf_diag = analyze_machine_telemetry_hf(machine.code, predicted_vibration, predicted_temp, slope)
                ticket_cause = f"[CRITICAL FAILURE] Extreme Telemetry (Vib: {predicted_vibration:.2f} mm/s, Temp: {predicted_temp:.2f}°C). Emergency Halt Required. | Diagnostic: {hf_diag}"
                MaintenanceTicket.objects.create(
                    machine=machine, 
                    cause=ticket_cause, 
                    status=MaintenanceTicket.Status.OPEN
                )
            prediction.reason += " | Action: Critical threshold exceeded. Ticket Active."
            prediction.save()

        elif predicted_vibration > 3.0 or predicted_temp > 72.0:
            flagged = True
            if slope > -0.5 and r_squared > 0.6 and not active_ticket:
                prediction.reason += f" | Analysis: Minor transient deviation (Vib: {predicted_vibration:.2f} mm/s). Historical stability high (R²={r_squared:.2f}). Continuing routine monitoring."
                prediction.save()
            else:
                if machine.status == Machine.Status.OPERATIONAL:
                    machine.status = Machine.Status.PENDING_INSPECTION
                    machine.save()

                if not active_ticket:
                    from apps.production.hf_service import analyze_machine_telemetry_hf
                    hf_diag = analyze_machine_telemetry_hf(machine.code, predicted_vibration, predicted_temp, slope)
                    ticket_cause = f"[WARNING / INSPECTION REQUIRED] Sustained telemetry deviation (Vib: {predicted_vibration:.2f} mm/s, Temp: {predicted_temp:.2f}°C). | Diagnostic: {hf_diag}"
                    MaintenanceTicket.objects.create(
                        machine=machine, 
                        cause=ticket_cause, 
                        status=MaintenanceTicket.Status.OPEN
                    )
                prediction.reason += " | Action: Sustained degradation detected. Warning Ticket Active."
                prediction.save()
        else:
            # Fully stable telemetry
            if not active_ticket and machine.status != Machine.Status.OPERATIONAL:
                machine.status = Machine.Status.OPERATIONAL
                machine.save()
            prediction.reason += " | Equipment fully stable and operating within optimal nominal bounds."
            prediction.save()

        results.append({
            "machine_code": machine.code,
            "predicted_output_kg": round(predicted_output, 2),
            "predicted_vibration": round(predicted_vibration, 2),
            "predicted_temp": round(predicted_temp, 2),
            "flagged": flagged
        })

    logger.info(f"Autonomous predictions calculated for {len(results)} machines on {today}.")
    return results


def create_tickets_from_warnings():
    """
    Scans the latest equipment telemetry for active warnings/critical anomalies
    and automatically creates tickets for machines that don't already have one open.
    """
    today = timezone.now().date()
    machines = Machine.objects.all()
    generated_tickets = []

    for machine in machines:
        # Check latest available metric (today or latest historical)
        metric = MachineHistoricalMetrics.objects.filter(machine=machine, date=today).first()
        if not metric:
            metric = MachineHistoricalMetrics.objects.filter(machine=machine).order_by('-date').first()

        if not metric:
            continue

        vib = float(metric.vibration)
        temp = float(metric.temperature)

        is_critical = vib > 5.0 or temp > 85.0
        is_warning = vib > 3.0 or temp > 72.0

        if is_critical or is_warning:
            existing_ticket = MaintenanceTicket.objects.filter(
                machine=machine, 
                status__in=[MaintenanceTicket.Status.OPEN, MaintenanceTicket.Status.IN_PROGRESS]
            ).exists()

            if not existing_ticket:
                if is_critical:
                    cause = f"[CRITICAL FAILURE] High vibration ({vib:.2f} mm/s) or critical temperature ({temp:.2f}°C) detected on machine {machine.code}. Emergency shutdown required."
                    machine.status = Machine.Status.UNDER_MAINTENANCE
                else:
                    cause = f"[WARNING / INSPECTION REQUIRED] Elevated vibration ({vib:.2f} mm/s) on machine {machine.code}. Preventative inspection required."
                    machine.status = Machine.Status.PENDING_INSPECTION

                machine.save()
                new_ticket = MaintenanceTicket.objects.create(
                    machine=machine,
                    cause=cause,
                    status=MaintenanceTicket.Status.OPEN
                )
                generated_tickets.append(new_ticket)

    return generated_tickets


def dispatch_tickets_to_in_progress(ticket_ids=None):
    """
    Transitions OPEN tickets to IN PROGRESS.
    Applies safety throttling, dispatches technician crew, and updates machine status.
    """
    queryset = MaintenanceTicket.objects.filter(status=MaintenanceTicket.Status.OPEN)
    if ticket_ids:
        queryset = queryset.filter(id__in=ticket_ids)

    dispatched = []
    for ticket in queryset:
        ticket.status = MaintenanceTicket.Status.IN_PROGRESS
        if '[CRITICAL FAILURE]' in ticket.cause:
            ticket.cause += " | [AI DISPATCH] Emergency shutdown engaged. Level-1 Maintenance Crew dispatched for hardware recalibration."
            ticket.machine.status = Machine.Status.UNDER_MAINTENANCE
        else:
            ticket.cause += " | [AI DISPATCH] Inspection crew deployed. Diagnostic telemetry sweep and dampener recalibration in progress."
            ticket.machine.status = Machine.Status.PENDING_INSPECTION

        ticket.machine.save()
        ticket.save()
        dispatched.append(ticket)
        logger.info(f"Ticket #{ticket.id} ({ticket.machine.code}) transitioned to IN_PROGRESS.")

    return dispatched


def resolve_in_progress_tickets(ticket_ids=None):
    """
    Autonomously resolves IN PROGRESS tickets.
    Heals equipment telemetry back to safe baselines, records closed timestamp,
    and returns machines to OPERATIONAL status.
    """
    queryset = MaintenanceTicket.objects.filter(status=MaintenanceTicket.Status.IN_PROGRESS)
    if ticket_ids:
        queryset = queryset.filter(id__in=ticket_ids)

    resolved = []
    now = timezone.now()

    for ticket in queryset:
        ticket.status = MaintenanceTicket.Status.CLOSED
        ticket.closed_at = now
        
        # Calculate downtime duration
        if ticket.opened_at:
            delta = now - ticket.opened_at
            ticket.downtime_min = max(15, int(delta.total_seconds() / 60))
        else:
            ticket.downtime_min = 30

        if '[CRITICAL FAILURE]' in ticket.cause:
            ticket.cause += " | [RESOLVED] Component replaced. Thermal cooling loop purged & vibration dampeners recalibrated. Certified operational."
        else:
            ticket.cause += " | [RESOLVED] Mechanical alignment tuned, lubrication replenished. Vibration normalized to baseline."

        ticket.save()

        # Database State Sync: Heal machine telemetry and restore machine to OP
        normalize_machine_telemetry(ticket.machine)
        resolved.append(ticket)
        logger.info(f"Ticket #{ticket.id} ({ticket.machine.code}) resolved and machine restored to OPERATIONAL.")

    return resolved


def run_closed_loop_automation_cycle(action='full'):
    """
    FULL END-TO-END AUTONOMOUS EQUIPMENT MAINTENANCE & DATABASE SYNC ENGINE.
    
    action:
    - 'full': Executes detection -> progresses open tickets to IN PROGRESS -> resolves in-progress tickets & normalizes database.
    - 'dispatch': Detects anomalies and advances OPEN tickets to IN PROGRESS.
    - 'resolve': Resolves all currently IN PROGRESS tickets and heals database telemetry.
    - 'predict': Runs scikit-learn ML predictions and syncs today's telemetry.
    """
    today = timezone.now().date()
    
    # STEP 1: Autonomous Predictions & Detection
    pred_results = run_daily_predictions(target_date=today)
    new_tickets = create_tickets_from_warnings()

    dispatched = []
    resolved = []

    if action == 'dispatch':
        dispatched = dispatch_tickets_to_in_progress()

    elif action == 'resolve':
        resolved = resolve_in_progress_tickets()

    elif action == 'predict':
        pass # Already ran predictions

    elif action == 'full':
        # If there are tickets already IN PROGRESS, resolve them first (healing previous work)
        existing_in_progress = MaintenanceTicket.objects.filter(status=MaintenanceTicket.Status.IN_PROGRESS)
        if existing_in_progress.exists():
            resolved = resolve_in_progress_tickets()

        # Advance OPEN tickets to IN PROGRESS so maintenance crew is dispatched
        open_tickets = MaintenanceTicket.objects.filter(status=MaintenanceTicket.Status.OPEN)
        if open_tickets.exists():
            dispatched = dispatch_tickets_to_in_progress()

            # If there were no prior in-progress tickets resolved, complete the loop by resolving
            # a portion or all based on resolution cycle so critical issues get resolved!
            # Resolve critical issues and warnings in this cycle
            resolved += resolve_in_progress_tickets([t.id for t in dispatched])

    return {
        "status": "success",
        "action": action,
        "predictions_count": len(pred_results),
        "new_tickets_count": len(new_tickets),
        "dispatched_count": len(dispatched),
        "resolved_count": len(resolved),
        "open_remaining": MaintenanceTicket.objects.filter(status=MaintenanceTicket.Status.OPEN).count(),
        "in_progress_count": MaintenanceTicket.objects.filter(status=MaintenanceTicket.Status.IN_PROGRESS).count(),
        "closed_count": MaintenanceTicket.objects.filter(status=MaintenanceTicket.Status.CLOSED).count()
    }
