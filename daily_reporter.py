import os
import django
from datetime import timedelta
from django.utils import timezone
from collections import defaultdict

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pharma_erp.settings')
django.setup()

from apps.production.models import ProductionLog
from apps.maintenance.models import MachineHistoricalMetrics, MaintenanceTicket
from apps.logistics.models import Dispatch
from apps.accounts.models import User

def is_ml_generated(created_at):
    # Our ML script runs exactly between 00:00 and 00:05.
    # So if created_at hour is 0 and minute < 15, we classify it as ML generated.
    local_time = timezone.localtime(created_at)
    return local_time.hour == 0 and local_time.minute < 15

def generate_report():
    today = timezone.now().date()
    yesterday = today - timedelta(days=1)
    
    report_lines = []
    report_lines.append(f"==================================================")
    report_lines.append(f"DAILY SYSTEM REPORT - {yesterday.strftime('%Y-%m-%d')}")
    report_lines.append(f"==================================================\n")
    
    # 1. PRODUCTION DATA
    report_lines.append("--- PRODUCTION ---")
    prod_logs = ProductionLog.objects.filter(date=yesterday)
    user_prod = 0
    ml_prod = 0
    user_mat = 0
    ml_mat = 0
    emp_stats = defaultdict(lambda: {'user': 0, 'ml': 0})
    
    for log in prod_logs:
        if is_ml_generated(log.created_at):
            ml_prod += float(log.output_kg)
            ml_mat += float(log.material_used)
            emp_stats[log.employee.username]['ml'] += float(log.output_kg)
        else:
            user_prod += float(log.output_kg)
            user_mat += float(log.material_used)
            emp_stats[log.employee.username]['user'] += float(log.output_kg)
            
    report_lines.append(f"Total Output (User-entered): {user_prod:.2f} kg")
    report_lines.append(f"Total Output (ML-generated): {ml_prod:.2f} kg")
    report_lines.append(f"Material Used (User-entered): {user_mat:.2f} kg")
    report_lines.append(f"Material Used (ML-generated): {ml_mat:.2f} kg\n")
    
    # 2. PER EMPLOYEE PRODUCTION
    report_lines.append("--- PER EMPLOYEE PRODUCTION ---")
    if not emp_stats:
        report_lines.append("No production data logged.")
    for emp, stats in emp_stats.items():
        report_lines.append(f"Employee [{emp}]: User-entered = {stats['user']:.2f} kg | ML-generated = {stats['ml']:.2f} kg")
    report_lines.append("\n")
    
    # 3. MAINTENANCE DATA
    report_lines.append("--- MAINTENANCE ---")
    metrics = MachineHistoricalMetrics.objects.filter(date=yesterday)
    user_metrics = 0
    ml_metrics = 0
    for m in metrics:
        if is_ml_generated(m.created_at):
            ml_metrics += 1
        else:
            user_metrics += 1
            
    tickets_opened = MaintenanceTicket.objects.filter(opened_at__date=yesterday)
    ml_tickets = 0
    user_tickets = 0
    for t in tickets_opened:
        if "ML" in t.cause:
            ml_tickets += 1
        else:
            user_tickets += 1
            
    report_lines.append(f"Machine Sensor Logs (User-entered): {user_metrics} logs")
    report_lines.append(f"Machine Sensor Logs (ML-generated): {ml_metrics} logs")
    report_lines.append(f"Tickets Opened by Users: {user_tickets}")
    report_lines.append(f"Tickets Opened by ML (Anomaly Detection): {ml_tickets}\n")
    
    # 4. LOGISTICS DATA
    report_lines.append("--- LOGISTICS ---")
    dispatches = Dispatch.objects.filter(created_at__date=yesterday)
    user_dispatch = 0
    ml_dispatch = 0
    for d in dispatches:
        if is_ml_generated(d.created_at):
            ml_dispatch += 1
        else:
            user_dispatch += 1
            
    report_lines.append(f"Dispatches (User-entered): {user_dispatch}")
    report_lines.append(f"Dispatches (ML-generated): {ml_dispatch}\n")
    
    report_lines.append(f"==================================================")
    report_lines.append(f"END OF REPORT")
    report_lines.append(f"==================================================")
    
    report_content = "\n".join(report_lines)
    
    # Save to file
    filename = f"c:/projects/PharmaERP/daily_reports/daily_report_{yesterday.strftime('%Y_%m_%d')}.txt"
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(report_content)
        
    print(f"Report successfully generated at {filename}")

if __name__ == "__main__":
    generate_report()
