import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from apps.production.models import SystemOverview, ProductionLog, SystemAlert, MaterialRequest
from apps.maintenance.models import Machine, MachineHistoricalMetrics, MaintenanceTicket
from apps.inventory.models import WarehouseStock
from apps.accounts.models import User
import random

class Command(BaseCommand):
    help = 'Daily check and ML imputation for SystemOverview'

    def handle(self, *args, **options):
        yesterday = (timezone.now() - timedelta(days=1)).date()
        
        # 1. Target Identification & Auto-Row Creation
        record, created = SystemOverview.objects.get_or_create(date=yesterday)
        if created:
            self.stdout.write(self.style.SUCCESS(f"No existing record found. Automatically created new database row for {yesterday}."))

        # CONDITION A (User Input Exists)
        if record.total_output_kg is not None and record.total_material_used_kg is not None:
            self.stdout.write(self.style.SUCCESS(f"Data for {yesterday} was manually provided. No imputation needed."))
            return

        machines = Machine.objects.all()
        employees = User.objects.filter(role='EM')
        if not employees.exists():
            employees = User.objects.all()

        # SUNDAY / HOLIDAY EXCEPTION HANDLING
        if yesterday.weekday() == 6:  # 6 is Sunday
            record.total_output_kg = 0.0
            record.total_material_used_kg = 0.0
            record.active_machines_count = 0
            record.is_auto_filled = True
            record.save()
            
            for m in machines:
                emp = employees.first()
                if emp:
                    ProductionLog.objects.get_or_create(
                        date=yesterday, machine=m, employee=emp,
                        defaults={'output_kg': 0, 'material_used': 0}
                    )
                MachineHistoricalMetrics.objects.get_or_create(
                    date=yesterday, machine=m,
                    defaults={'temperature': 0, 'vibration': 0, 'output': 0}
                )

            self.stdout.write(self.style.SUCCESS(f"Yesterday {yesterday} was a Sunday. Applied weekend exception rule (values set to 0)."))
            return

        # CONDITION B (Missing/Incomplete Data on Working Day)
        self.stdout.write(self.style.WARNING(f"Missing data for normal working day {yesterday}. Triggering ML Model for Imputation..."))

        # 3. Mandatory ML Prediction Execution
        logs = ProductionLog.objects.all().values('date', 'output_kg', 'material_used')
        df = pd.DataFrame(logs)

        # Basic defaults if not enough data
        if df.empty or len(df['date'].unique()) < 3:
            record.total_output_kg = 500.0
            record.total_material_used_kg = 520.0
            record.active_machines_count = Machine.objects.filter(status='OP').count()
            record.is_auto_filled = True
            record.save()
            self.stdout.write(self.style.SUCCESS(f"Fallback values populated for {yesterday} due to lack of historical data."))
            return

        # Prepare Historical Dataset
        df['date'] = pd.to_datetime(df['date'])
        daily_df = df.groupby('date').agg({
            'output_kg': 'sum',
            'material_used': 'sum'
        }).reset_index()

        daily_df['day_of_week'] = daily_df['date'].dt.dayofweek
        daily_df['month'] = daily_df['date'].dt.month

        X = daily_df[['day_of_week', 'month']]
        y_out = daily_df['output_kg']
        y_mat = daily_df['material_used']

        # Train Random Forest Regressor
        rf_out = RandomForestRegressor(n_estimators=100, random_state=42)
        rf_out.fit(X, y_out)
        
        rf_mat = RandomForestRegressor(n_estimators=100, random_state=42)
        rf_mat.fit(X, y_mat)

        # Predict for yesterday
        yesterday_dt = pd.to_datetime(yesterday)
        X_pred = pd.DataFrame([{
            'day_of_week': yesterday_dt.dayofweek,
            'month': yesterday_dt.month
        }])

        pred_out = rf_out.predict(X_pred)[0]
        pred_mat = rf_mat.predict(X_pred)[0]

        # Active Machines Context
        active_machines = Machine.objects.filter(status='OP').count()

        # Write to database
        record.total_output_kg = round(pred_out, 2)
        record.total_material_used_kg = round(pred_mat, 2)
        record.active_machines_count = active_machines
        record.is_auto_filled = True
        record.save()

        if machines.exists():
            per_machine_out = pred_out / machines.count()
            per_machine_mat = pred_mat / machines.count()
            
            for m in machines:
                emp = employees.order_by('?').first()
                if not emp:
                    emp = employees.first()
                
                if emp:
                    ProductionLog.objects.get_or_create(
                        date=yesterday, machine=m, employee=emp,
                        defaults={'output_kg': round(per_machine_out, 2), 'material_used': round(per_machine_mat, 2)}
                    )
                
                vibration = 2.0 + random.uniform(0.1, 1.5)
                temperature = 65.0 + random.uniform(2.0, 10.0)
                
                MachineHistoricalMetrics.objects.get_or_create(
                    date=yesterday, machine=m,
                    defaults={
                        'temperature': round(temperature, 2),
                        'vibration': round(vibration, 2),
                        'output': round(per_machine_out, 2)
                    }
                )

            # --- OUTBOUND INVENTORY SYNC ---
            raw_material, _ = WarehouseStock.objects.get_or_create(
                material='Eucalyptus Pulp',
                defaults={'quantity': 15000, 'unit': 'kg', 'reorder_level': 5000}
            )
            finished_goods, _ = WarehouseStock.objects.get_or_create(
                material='Finished Pharmaceuticals',
                defaults={'quantity': 0, 'unit': 'kg', 'reorder_level': 1000}
            )

            raw_material.quantity -= Decimal(str(round(pred_mat, 2)))
            finished_goods.quantity += Decimal(str(round(pred_out, 2)))
            raw_material.save()
            finished_goods.save()
            self.stdout.write(self.style.SUCCESS(f"[INVENTORY SYNC] Deducted {pred_mat:.2f} kg raw material. Added {pred_out:.2f} kg finished goods."))

            # --- WARNING ENGINE & AUTO-RESOLVE ---
            # 1. Low Stock Warning
            if raw_material.quantity < raw_material.reorder_level:
                alert = SystemAlert.objects.create(
                    alert_type=SystemAlert.AlertType.LOW_STOCK,
                    message=f"Low stock for {raw_material.material}: {raw_material.quantity} kg."
                )
                self.stdout.write(self.style.WARNING(f"[WARNING ENGINE] {alert.message}"))

            # 2. Low Efficiency Warning
            efficiency = (pred_out / pred_mat) * 100 if pred_mat > 0 else 0
            if efficiency < 90.0:
                alert = SystemAlert.objects.create(
                    alert_type=SystemAlert.AlertType.LOW_EFFICIENCY,
                    message=f"Low production yield efficiency: {efficiency:.1f}%."
                )
                self.stdout.write(self.style.WARNING(f"[WARNING ENGINE] {alert.message}"))

            # 3. High Vibration Warning
            for m in machines:
                metric = MachineHistoricalMetrics.objects.filter(machine=m, date=yesterday).first()
                if metric and metric.vibration > 3.0:
                    alert = SystemAlert.objects.create(
                        alert_type=SystemAlert.AlertType.CRITICAL,
                        message=f"High vibration ({metric.vibration} mm/s) on machine {m.code}."
                    )
                    self.stdout.write(self.style.WARNING(f"[WARNING ENGINE] {alert.message}"))

        # 4. DELEGATE ALL RESOLUTIONS TO DELIBERATE DECISION ENGINE
        from apps.production.decision_engine import run_autonomous_decision_engine
        run_autonomous_decision_engine()

        self.stdout.write(self.style.SUCCESS(
            f"Successfully imputed {yesterday} data. Output: {pred_out:.2f} kg. Engine handled all resolutions."
        ))
