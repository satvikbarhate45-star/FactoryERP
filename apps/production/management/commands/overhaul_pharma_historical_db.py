import math
import random
import logging
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from apps.maintenance.models import Machine, MachineHistoricalMetrics, MachinePrediction, MaintenanceTicket
from apps.production.models import ProductionLog, SystemOverview, SalaryPayroll, ProductionTarget
from apps.inventory.models import WarehouseStock, InwardShipment
from apps.logistics.models import Dispatch
from apps.accounts.models import User, Shift

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Executes complete pharmaceutical historical database overhaul & time-series migration (Supabase PostgreSQL & SQLite)'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE(
            "==================================================================\n"
            "STARTING PHARMACEUTICAL DATABASE OVERHAUL & TIME-SERIES MIGRATION\n"
            "=================================================================="
        ))

        # -----------------------------------------------------------------------------
        # 1. PHARMACEUTICAL WAREHOUSE STOCKS OVERHAUL
        # -----------------------------------------------------------------------------
        self.stdout.write("[STEP 1] Overhauling Warehouse Stocks with cGMP Pharmaceutical Standards...")

        PHARMA_STOCKS = [
            {
                "material": "Paracetamol IP/USP Grade API",
                "quantity": Decimal("24500.00"),
                "unit": "kg",
                "reorder_level": Decimal("6000.00")
            },
            {
                "material": "Metformin Hydrochloride BP/USP API",
                "quantity": Decimal("18200.00"),
                "unit": "kg",
                "reorder_level": Decimal("5000.00")
            },
            {
                "material": "Microcrystalline Cellulose (Avicel PH-102)",
                "quantity": Decimal("32400.00"),
                "unit": "kg",
                "reorder_level": Decimal("8000.00")
            },
            {
                "material": "Lactose Monohydrate Compression Grade",
                "quantity": Decimal("28100.00"),
                "unit": "kg",
                "reorder_level": Decimal("7000.00")
            },
            {
                "material": "Magnesium Stearate Vegetable Excipient",
                "quantity": Decimal("4800.00"),
                "unit": "kg",
                "reorder_level": Decimal("1500.00")
            },
            {
                "material": "Povidone K-30 Binder Polymer",
                "quantity": Decimal("6200.00"),
                "unit": "kg",
                "reorder_level": Decimal("2000.00")
            },
            {
                "material": "ALU-ALU Cold-Form Blister Foil",
                "quantity": Decimal("38000.00"),
                "unit": "units",
                "reorder_level": Decimal("10000.00")
            },
            {
                "material": "Finished Solid Oral Dosages (Coated Tablets)",
                "quantity": Decimal("42500.00"),
                "unit": "kg",
                "reorder_level": Decimal("5000.00")
            },
        ]

        existing_stocks = list(WarehouseStock.objects.all().order_by('id'))
        for idx, stock_data in enumerate(PHARMA_STOCKS):
            if idx < len(existing_stocks):
                s = existing_stocks[idx]
                s.material = stock_data["material"]
                s.quantity = stock_data["quantity"]
                s.unit = stock_data["unit"]
                s.reorder_level = stock_data["reorder_level"]
                s.save()
            else:
                WarehouseStock.objects.create(
                    material=stock_data["material"],
                    quantity=stock_data["quantity"],
                    unit=stock_data["unit"],
                    reorder_level=stock_data["reorder_level"]
                )

        # Remove extra mock stocks beyond our standard 8 pharma items
        extra_stocks = list(WarehouseStock.objects.all().order_by('id')[len(PHARMA_STOCKS):])
        primary_stock = WarehouseStock.objects.all().order_by('id').first()
        for es in extra_stocks:
            if primary_stock:
                InwardShipment.objects.filter(material=es).update(material=primary_stock)
            es.delete()

        active_stocks = list(WarehouseStock.objects.all().order_by('id'))
        self.stdout.write(f"Warehouse stocks updated to {len(active_stocks)} authentic pharmaceutical standards.")

        # -----------------------------------------------------------------------------
        # 2. PHARMACEUTICAL EQUIPMENT FLEET OVERHAUL
        # -----------------------------------------------------------------------------
        self.stdout.write("[STEP 2] Verifying 24 Pharmaceutical Manufacturing Machine Lines...")
        machines = list(Machine.objects.all().order_by('id'))
        PHARMA_MACHINE_SPECS = [
            {"type": "Rotary Tablet Press", "model": "Fette Compacting 3090i", "cap": 310.0, "base_vib": 1.95, "base_temp": 62.0},
            {"type": "Fluid Bed Dryer & Granulator", "model": "Glatt Pro FB-500", "cap": 260.0, "base_vib": 1.72, "base_temp": 71.0},
            {"type": "High-Shear Rapid Mixer", "model": "Siemens MixPro 1200", "cap": 340.0, "base_vib": 2.35, "base_temp": 64.5},
            {"type": "Automated Blister Packager", "model": "Uhlmann UPS-4 Suite", "cap": 220.0, "base_vib": 1.48, "base_temp": 56.0},
            {"type": "Decanter Centrifuge Unit", "model": "Alfa Laval Clara 80", "cap": 275.0, "base_vib": 2.50, "base_temp": 65.0},
            {"type": "Auto-Coating Drum", "model": "Bosch CoatMaster 800", "cap": 235.0, "base_vib": 1.65, "base_temp": 69.0},
        ]

        machine_profiles = {}
        for idx, m in enumerate(machines):
            spec = PHARMA_MACHINE_SPECS[idx % len(PHARMA_MACHINE_SPECS)]
            rng = random.Random(m.id * 101)
            
            m.name = f"{spec['type']} Line {idx+1:02d}"
            m.model_name = spec["model"]
            m.featured_for = f"Pharmaceutical Solid Oral Formulation & Packaging - {spec['type']}"
            m.status = Machine.Status.OPERATIONAL
            m.save(update_fields=['name', 'model_name', 'featured_for', 'status'])

            machine_profiles[m.id] = {
                "model": spec["model"],
                "name": m.name,
                "nominal_cap": spec["cap"] + rng.uniform(-12.0, 12.0),
                "base_vib": spec["base_vib"] + rng.uniform(-0.10, 0.10),
                "base_temp": spec["base_temp"] + rng.uniform(-1.5, 1.5),
                "wear_rate": rng.uniform(0.85, 1.15),
                "initial_rul": 72 + (m.id % 6) * 2,
            }

        self.stdout.write(f"Updated {len(machines)} machines with cGMP pharmaceutical specs.")

        # -----------------------------------------------------------------------------
        # 3. EMPLOYEES & CLEANROOM OPERATOR RATINGS
        # -----------------------------------------------------------------------------
        employees = list(User.objects.filter(role='EM').order_by('id'))
        if not employees:
            employees = list(User.objects.all().order_by('id'))

        emp_skills = {}
        for emp in employees:
            rng = random.Random(emp.id * 77)
            emp_skills[emp.id] = {
                "efficiency": rng.uniform(0.92, 1.12),
                "volatility": rng.uniform(0.02, 0.05),
            }

        # -----------------------------------------------------------------------------
        # 4. TIME-SERIES CHRONOLOGICAL GENERATION (2026-08-25 TO 2026-10-31)
        # -----------------------------------------------------------------------------
        start_date = date(2026, 8, 25)
        end_date = date(2026, 10, 31)
        total_days = (end_date - start_date).days + 1
        self.stdout.write(f"[STEP 3] Synchronizing {total_days} days of non-flat pharmaceutical telemetry ({start_date} to {end_date})...")

        DOW_MULTIPLIERS = {
            0: 0.915,  # Mon (startup calibration & cleanroom prep)
            1: 1.015,  # Tue (peak continuous processing)
            2: 1.065,  # Wed (peak batch throughput)
            3: 1.030,  # Thu (high steady-state)
            4: 0.940,  # Fri (end of week winding down)
            5: 0.580,  # Sat (half-day operations & scheduled PM)
            6: 0.000,  # Sun (cleanroom sanitation, autoclave & CIP)
        }

        PHARMA_SUPPLIERS = [
            "Aarti Drugs Ltd (API Division)",
            "Divi's Laboratories Ltd",
            "BASF Pharma Solutions",
            "Colorcon Asia Excipients",
            "Bilcare Research Packaging",
        ]

        PHARMA_CUSTOMERS = [
            ("Apollo Pharmacy Central Distribution", "DHL Pharma Cold-Chain Logix"),
            ("MedPlus Health Services Warehouse", "Blue Dart Temperature-Controlled"),
            ("Fortis Healthcare Hospital Supply", "FedEx Healthcare Priority"),
            ("Cipla Global Export Distribution", "TCI Supply Chain Pharma Logix"),
            ("Sun Pharma International Logistics", "DHL Pharma Cold-Chain Logix"),
            ("Max Healthcare Central Depot", "Blue Dart Temperature-Controlled"),
        ]

        # Fast lookups for existing records to ensure idempotent updates
        existing_pl_map = {}
        for pl in ProductionLog.objects.filter(date__gte=start_date, date__lte=end_date).values('id', 'date', 'machine_id'):
            existing_pl_map[(pl['date'], pl['machine_id'])] = pl['id']

        existing_mhm_map = {}
        for mhm in MachineHistoricalMetrics.objects.filter(date__gte=start_date, date__lte=end_date).values('id', 'date', 'machine_id'):
            existing_mhm_map[(mhm['date'], mhm['machine_id'])] = mhm['id']

        existing_pred_map = {}
        for pred in MachinePrediction.objects.filter(date__gte=start_date, date__lte=end_date).values('id', 'date', 'machine_id'):
            existing_pred_map[(pred['date'], pred['machine_id'])] = pred['id']

        existing_so_map = {}
        for so in SystemOverview.objects.filter(date__gte=start_date, date__lte=end_date).values('id', 'date'):
            existing_so_map[so['date']] = so['id']

        existing_pr_map = {}
        for pr in SalaryPayroll.objects.filter(payout_date__gte=start_date, payout_date__lte=end_date).values('id', 'payout_date', 'employee_id'):
            existing_pr_map[(pr['payout_date'], pr['employee_id'])] = pr['id']

        logs_to_create = []
        metrics_to_create = []
        preds_to_create = []
        so_to_create = []
        pr_to_create = []
        inward_to_create = []
        disp_to_create = []

        raw_materials_for_shipments = active_stocks[:6]

        for day_idx in range(total_days):
            curr_date = start_date + timedelta(days=day_idx)
            dow = curr_date.weekday()
            dow_mult = DOW_MULTIPLIERS[dow]
            date_rng = random.Random(curr_date.toordinal() * 41)
            is_sunday = (dow == 6)

            daily_total_output = 0.0
            daily_total_material = 0.0
            active_machines_count = 0

            # A. Inward Shipments (Bi-weekly Tuesdays & Fridays)
            if dow in [1, 4] and not InwardShipment.objects.filter(received_on=curr_date).exists() and raw_materials_for_shipments:
                sup = date_rng.choice(PHARMA_SUPPLIERS)
                mat = date_rng.choice(raw_materials_for_shipments)
                s_qty = round(date_rng.uniform(2500.0, 7200.0), 2)
                unit_price = date_rng.uniform(18.0, 32.0)
                s_cost = round(s_qty * unit_price, 2)
                inward_to_create.append(InwardShipment(
                    supplier=sup, material=mat, quantity=s_qty, cost=s_cost, received_on=curr_date
                ))

            # B. Finished Goods Dispatches (Mondays, Wednesdays, Saturdays)
            if dow in [0, 2, 5] and not Dispatch.objects.filter(created_at__date=curr_date).exists():
                cust, transp = date_rng.choice(PHARMA_CUSTOMERS)
                d_qty = round(date_rng.uniform(2200.0, 5800.0), 2)
                d_cost = round(date_rng.uniform(22500.0, 48000.0), 2)
                d_time = timezone.make_aware(
                    timezone.datetime.combine(curr_date, timezone.datetime.min.time()) + 
                    timedelta(hours=14, minutes=date_rng.randint(5, 55))
                )
                disp_to_create.append(Dispatch(
                    customer=cust, transporter=transp,
                    transport_id=f"PH-{curr_date.strftime('%y%m')}-{date_rng.randint(100, 999)}",
                    maps_location_id="LOC-PHARMA-CENTRAL",
                    quantity=d_qty, cost=d_cost, dispatch_type="EXPORT",
                    is_automated=True, created_at=d_time
                ))

            # C. Machine Production & Telemetry
            for m_idx, m in enumerate(machines):
                prof = machine_profiles[m.id]
                m_rng = random.Random((curr_date.toordinal() * 100) + m.id)

                # Historical Degradation Events
                is_m07_wear = (m.code == 'M-07' and date(2026, 10, 12) <= curr_date <= date(2026, 10, 26))
                is_m07_restored = (m.code == 'M-07' and curr_date > date(2026, 10, 26))
                is_m12_issue = (m.code == 'M-12' and date(2026, 9, 20) <= curr_date <= date(2026, 9, 25))

                if is_sunday:
                    m_out = 0.0
                    m_raw = 0.0
                    m_vib = 0.0
                    m_temp = round(24.0 + m_rng.uniform(-0.4, 0.6), 2)
                    m_rul = prof["initial_rul"] - int((curr_date - start_date).days * 0.7)
                    m_rul = max(15, m_rul)
                    m_health = 98.8
                else:
                    active_machines_count += 1
                    harmonic_wave = 0.075 * math.sin((curr_date.toordinal() * 0.45) + (m.id * 1.3))
                    noise_factor = m_rng.uniform(-0.035, 0.035)
                    eff_rate = dow_mult * (1.0 + harmonic_wave + noise_factor)
                    nominal_cap = prof["nominal_cap"]
                    m_out = round(max(75.0, nominal_cap * eff_rate), 2)

                    # cGMP Batch Yield ratio (94.2% - 97.8%)
                    m_yield = 0.952 + m_rng.uniform(-0.018, 0.022)
                    if is_m07_wear:
                        m_yield -= 0.04
                        m_out = round(m_out * 0.86, 2)
                    elif is_m12_issue:
                        m_yield -= 0.035
                        m_out = round(m_out * 0.89, 2)

                    m_raw = round(m_out / m_yield, 2)
                    daily_total_output += m_out
                    daily_total_material += m_raw

                    # Telemetry Physics: Vibration & Cleanroom Temperature
                    load_ratio = (m_out / nominal_cap)
                    vib_dynamic = prof["base_vib"] + (0.18 * (load_ratio - 1.0)) + (0.05 * math.sin(curr_date.day * 1.1 + m.id)) + m_rng.uniform(-0.04, 0.04)
                    temp_dynamic = prof["base_temp"] + (0.032 * m_out) + (0.8 * math.cos(curr_date.day * 0.8 + m.id)) + m_rng.uniform(-0.5, 0.5)

                    if is_m07_wear:
                        days_wear = (curr_date - date(2026, 10, 12)).days
                        w_factor = days_wear / 14.0
                        vib_dynamic += (0.6 + 2.5 * w_factor)
                        temp_dynamic += (3.0 + 8.0 * w_factor)
                        m_rul = max(6, int(35 - (days_wear * 2.1)))
                        m_health = round(max(46.0, 88.0 - (w_factor * 38.0)), 2)
                    elif is_m07_restored:
                        days_post = (curr_date - date(2026, 10, 26)).days
                        vib_dynamic = prof["base_vib"] - 0.04 + m_rng.uniform(-0.03, 0.03)
                        temp_dynamic = prof["base_temp"] - 1.1 + m_rng.uniform(-0.4, 0.4)
                        m_rul = max(70, 84 - days_post)
                        m_health = round(min(99.4, 98.8 - days_post * 0.08), 2)
                    elif is_m12_issue:
                        vib_dynamic += 1.45
                        temp_dynamic += 4.5
                        m_rul = max(18, int(45 - (curr_date - date(2026, 9, 20)).days * 4))
                        m_health = 74.0
                    else:
                        op_days = (curr_date - start_date).days
                        cycle_wear = (op_days * 0.65 * prof["wear_rate"]) % 50
                        m_rul = max(14, int(prof["initial_rul"] - cycle_wear + (4 * math.sin(curr_date.day * 0.5 + m.id))))
                        m_health = round(max(78.0, min(99.4, 99.2 - (cycle_wear * 0.32) - ((vib_dynamic - prof["base_vib"]) * 4.2))), 2)

                    m_vib = round(max(1.15, vib_dynamic), 2)
                    m_temp = round(max(48.0, temp_dynamic), 2)

                # 1. Update/Create MachineHistoricalMetrics
                metric_id = existing_mhm_map.get((curr_date, m.id))
                if metric_id:
                    MachineHistoricalMetrics.objects.filter(id=metric_id).update(
                        vibration=m_vib, temperature=m_temp, output=m_out
                    )
                else:
                    metrics_to_create.append(MachineHistoricalMetrics(
                        machine=m, date=curr_date, vibration=m_vib, temperature=m_temp, output=m_out
                    ))

                # 2. Update/Create ProductionLog
                assigned_emp = employees[(m_idx + curr_date.day) % len(employees)]
                pl_id = existing_pl_map.get((curr_date, m.id))
                if pl_id:
                    ProductionLog.objects.filter(id=pl_id).update(
                        output_kg=m_out, material_used=m_raw, employee=assigned_emp
                    )
                else:
                    logs_to_create.append(ProductionLog(
                        date=curr_date, machine=m, employee=assigned_emp,
                        output_kg=m_out, material_used=m_raw, is_auto_predicted=False
                    ))

                # 3. MachinePrediction (Oct 01 to Oct 31)
                if curr_date >= date(2026, 10, 1):
                    pred_vib = round(m_vib + m_rng.uniform(-0.06, 0.06), 2) if not is_sunday else round(prof["base_vib"], 2)
                    pred_temp = round(m_temp + m_rng.uniform(-0.5, 0.5), 2) if not is_sunday else round(prof["base_temp"], 2)
                    conf_pct = round(max(89.20, min(96.80, 95.20 - (abs(m_vib - prof["base_vib"]) * 2.6) + m_rng.uniform(-0.7, 0.7))), 2)
                    reason_text = f"cGMP Telemetry Fit: {m_out:.1f}kg yield. Cleanroom kinetic vib: {pred_vib}mm/s, Temp: {pred_temp}°C. RUL: {m_rul}d (Health: {m_health}%, Conf: {conf_pct}%)."

                    pred_id = existing_pred_map.get((curr_date, m.id))
                    if pred_id:
                        MachinePrediction.objects.filter(id=pred_id).update(
                            predicted_vibration=pred_vib, predicted_temp=pred_temp,
                            predicted_rul_days=m_rul, health_score=m_health,
                            accuracy_pct=conf_pct, reason=reason_text
                        )
                    else:
                        preds_to_create.append(MachinePrediction(
                            machine=m, date=curr_date, predicted_vibration=pred_vib,
                            predicted_temp=pred_temp, predicted_rul_days=m_rul,
                            health_score=m_health, accuracy_pct=conf_pct,
                            is_auto_predicted=True, reason=reason_text
                        ))

            # D. SystemOverview
            daily_total_output = round(daily_total_output, 2)
            daily_total_material = round(daily_total_material, 2)
            so_id = existing_so_map.get(curr_date)
            if so_id:
                SystemOverview.objects.filter(id=so_id).update(
                    total_output_kg=daily_total_output,
                    total_material_used_kg=daily_total_material,
                    active_machines_count=active_machines_count,
                    is_auto_filled=False
                )
            else:
                so_to_create.append(SystemOverview(
                    date=curr_date, total_output_kg=daily_total_output,
                    total_material_used_kg=daily_total_material,
                    active_machines_count=active_machines_count,
                    is_auto_filled=False
                ))

            # E. SalaryPayroll
            if not is_sunday and employees:
                for e_idx, emp in enumerate(employees):
                    e_skill = emp_skills[emp.id]
                    e_rng = random.Random((curr_date.toordinal() * 50) + emp.id)
                    target_kg = 165.0
                    actual_out = round(max(110.0, 165.0 * e_skill["efficiency"] * dow_mult + e_rng.uniform(-6.0, 6.0)), 1)
                    comp_pct = round((actual_out / target_kg) * 100, 1)
                    base_pay = 450.0
                    if comp_pct >= 95.0:
                        perf_bonus = 1.10 + (min(25.0, comp_pct - 95.0) * 0.005)
                        adj_pay = round(base_pay * perf_bonus, 2)
                    else:
                        adj_pay = round(base_pay * max(0.85, comp_pct / 100.0), 2)
                    adj_pay = round(max(380.0, min(525.0, adj_pay)), 2)

                    pr_id = existing_pr_map.get((curr_date, emp.id))
                    if pr_id:
                        SalaryPayroll.objects.filter(id=pr_id).update(
                            base_salary=base_pay, target_assigned=target_kg,
                            actual_output=actual_out, completion_percentage=comp_pct,
                            salary_adjusted=adj_pay, is_incremented=(comp_pct >= 95.0),
                            is_auto_predicted=False
                        )
                    else:
                        pr_to_create.append(SalaryPayroll(
                            employee=emp, payout_date=curr_date,
                            base_salary=base_pay, target_assigned=target_kg,
                            actual_output=actual_out, completion_percentage=comp_pct,
                            salary_adjusted=adj_pay, is_incremented=(comp_pct >= 95.0),
                            is_auto_predicted=False
                        ))

        # Bulk creations
        if inward_to_create:
            InwardShipment.objects.bulk_create(inward_to_create, batch_size=500)
        if disp_to_create:
            Dispatch.objects.bulk_create(disp_to_create, batch_size=500)
        if logs_to_create:
            ProductionLog.objects.bulk_create(logs_to_create, batch_size=500)
        if metrics_to_create:
            MachineHistoricalMetrics.objects.bulk_create(metrics_to_create, batch_size=500)
        if preds_to_create:
            MachinePrediction.objects.bulk_create(preds_to_create, batch_size=500)
        if so_to_create:
            SystemOverview.objects.bulk_create(so_to_create, batch_size=500)
        if pr_to_create:
            SalaryPayroll.objects.bulk_create(pr_to_create, batch_size=500)

        self.stdout.write(f"Batch created: {len(logs_to_create)} logs, {len(metrics_to_create)} metrics, {len(preds_to_create)} preds, {len(inward_to_create)} inward, {len(disp_to_create)} dispatches.")

        # -----------------------------------------------------------------------------
        # 5. OVERHAUL MAINTENANCE TICKETS WITH AUTHENTIC CGMP STANDARDS
        # -----------------------------------------------------------------------------
        self.stdout.write("[STEP 4] Overhauling Maintenance Tickets with cGMP Overhaul Standards...")
        GMP_REPAIR_SCENARIOS = [
            {
                "cause": "cGMP Cleanroom HEPA filter differential pressure breach and perimeter gasket degradation.",
                "diag": "Airflow velocity dropped below 0.36 m/s. Filter media saturation detected via magnehelic gauge.",
                "resolution": "HEPA filter unit H14 replaced, perimeter silicone gasket certified, DOP leak integrity tested.",
                "parts": 18500.0, "labor": 4500.0, "downtime": 120
            },
            {
                "cause": "Rotary tablet punch upper tooling galling and die table turret mechanical misalignment.",
                "diag": "Tooling friction thermal rise to 76.5°C with kinetic oscillation variance > 2.8 mm/s.",
                "resolution": "EU-D punch set polished, die table zero-point recalibrated, food-grade synthetic lubrication replenished.",
                "parts": 24000.0, "labor": 6200.0, "downtime": 150
            },
            {
                "cause": "Fluid bed granulator stainless exhaust mesh rupture and peristaltic binder pump pressure drop.",
                "diag": "Differential pressure collapse across 5-micron filter mesh with particulate flow spike.",
                "resolution": "316L SS filter cart replaced, binder nozzle spray atomization calibrated at 2.2 bar.",
                "parts": 14200.0, "labor": 3800.0, "downtime": 90
            },
            {
                "cause": "Automated blister packager heat-seal roller thermocouple drift and intermittent sealing failure.",
                "diag": "Thermal variance +/- 8.5°C causing incomplete aluminum foil hermetic bond.",
                "resolution": "PID controller re-tuned, heating cartridge replaced, burst pressure vacuum leak test passed.",
                "parts": 9800.0, "labor": 2600.0, "downtime": 60
            },
            {
                "cause": "Decanter centrifuge drive shaft mechanical seal degradation and bearing vibration harmonic spike.",
                "diag": "Rotational kinetic vibration reached 4.6 mm/s at 3,200 RPM indicating mechanical seal wear.",
                "resolution": "SKF ceramic hybrid bearing installed, silicon-carbide mechanical seal renewed, dynamic balancing tuned to 1.72 mm/s.",
                "parts": 32500.0, "labor": 8500.0, "downtime": 180
            },
            {
                "cause": "Perforated coating drum exhaust air velocity dampener damper servo positioning stall.",
                "diag": "Negative pressure fluctuation inside drum chamber resulting in irregular film deposition.",
                "resolution": "Belimo damper actuator replaced, exhaust air velocity recalibrated to 2,800 m³/hr.",
                "parts": 16500.0, "labor": 3200.0, "downtime": 75
            },
        ]

        tickets = list(MaintenanceTicket.objects.all().order_by('id'))
        for idx, t in enumerate(tickets):
            scen = GMP_REPAIR_SCENARIOS[idx % len(GMP_REPAIR_SCENARIOS)]
            rng = random.Random(t.id * 89)
            p_cost = scen["parts"] * rng.uniform(0.90, 1.15)
            l_cost = scen["labor"] * rng.uniform(0.90, 1.10)
            tot_cost = p_cost + l_cost
            dt = int(scen["downtime"] * rng.uniform(0.85, 1.25))

            t.parts_cost = round(Decimal(str(p_cost)), 2)
            t.labor_cost = round(Decimal(str(l_cost)), 2)
            t.total_cost = round(Decimal(str(tot_cost)), 2)
            t.downtime_min = dt
            
            if t.status == MaintenanceTicket.Status.CLOSED:
                t.cause = f"[cGMP COMPLIANCE] {scen['cause']} | Diagnostic: {scen['diag']} | [RESOLVED] {scen['resolution']}"
            elif t.status == MaintenanceTicket.Status.IN_PROGRESS:
                t.cause = f"[ACTIVE INTERVENTION] {scen['cause']} | Diagnostic: {scen['diag']} | [IN PROGRESS] On-site certified validation technician tuning hardware."
            else:
                t.cause = f"[INSPECTION REQUIRED] {scen['cause']} | Diagnostic: {scen['diag']} | Scheduled for cGMP calibration."
            
            t.save(update_fields=['parts_cost', 'labor_cost', 'total_cost', 'downtime_min', 'cause'])

        self.stdout.write(f"Updated {len(tickets)} maintenance tickets with authentic pharmaceutical cGMP records.")
        self.stdout.write(self.style.SUCCESS(
            "==================================================================\n"
            "PHARMACEUTICAL DATABASE OVERHAUL & TIME-SERIES MIGRATION COMPLETE!\n"
            "=================================================================="
        ))
