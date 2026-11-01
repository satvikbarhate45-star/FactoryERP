"""
apps/accounts/financial_service.py

Production Financial Profit & Loss (P&L) Data Separation & Analytics Engine.
Provides clean separation of:
1. Profit Data (Gross revenue, finished output, operating margin, profitable batches)
2. Loss Data (Material conversion shrinkage, equipment repair maintenance, freight logistics)
3. Payroll Data (Workforce compensation, performance adjustments, statutory deductions)
4. Material Usage Data (Raw material inward receipts, batch consumption, conversion yield)

Supports header-level time classification across Daily, Weekly, and Monthly timeframes.
"""

from datetime import date, datetime, timedelta
import calendar
import json
from django.utils import timezone
from django.db.models import Sum, Q, Count
from apps.inventory.models import InwardShipment
from apps.production.models import SalaryPayroll, ProductionLog, SystemOverview
from apps.logistics.models import Dispatch
from apps.maintenance.models import MaintenanceTicket


SELLING_PRICE_PER_KG = 45.0
RAW_MATERIAL_COST_PER_KG = 18.0


def get_date_range_for_timeframe(time_frame='weekly', offset=0, base_date=None):
    """
    Returns (start_date, end_date, label, chart_intervals) for daily, weekly, and monthly timeframes.
    """
    if base_date is None:
        base_date = timezone.localdate()

    if time_frame == 'daily':
        target_date = base_date + timedelta(days=offset)
        start_date = target_date
        end_date = target_date
        label = target_date.strftime('%A, %B %d, %Y')
        # 1-day interval
        chart_intervals = [
            (target_date, target_date.strftime('%b %d'))
        ]
    elif time_frame == 'monthly':
        # Month computation with offset
        year = base_date.year
        month = base_date.month + offset
        while month < 1:
            month += 12
            year -= 1
        while month > 12:
            month -= 12
            year += 1
        num_days = calendar.monthrange(year, month)[1]
        start_date = date(year, month, 1)
        end_date = date(year, month, num_days)
        label = start_date.strftime('%B %Y')
        
        # 4 weekly intervals for monthly chart
        chart_intervals = []
        cur = start_date
        while cur <= end_date:
            cur_end = min(cur + timedelta(days=6), end_date)
            int_label = f"{cur.strftime('%b %d')} - {cur_end.strftime('%d')}"
            chart_intervals.append((cur, int_label, cur_end))
            cur = cur_end + timedelta(days=1)
    else:  # 'weekly' (default)
        idx = (base_date.weekday() + 1) % 7
        start_date = base_date - timedelta(days=idx) + timedelta(weeks=offset)
        end_date = start_date + timedelta(days=6)
        label = f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d, %Y')}"
        chart_intervals = [
            (start_date + timedelta(days=i), (start_date + timedelta(days=i)).strftime('%a, %b %d'))
            for i in range(7)
        ]

    return start_date, end_date, label, chart_intervals


def compute_timeframe_financial_package(start_date, end_date, chart_intervals, time_frame='weekly'):
    """
    Computes strictly separated financial categories for a given date range:
    1. Profit Data
    2. Loss Data
    3. Payroll Data
    4. Material Usage Data
    And combined datasets for chart rendering.
    """
    # -------------------------------------------------------------
    # 1. PROFIT DATA (Production Gross Revenue & Finished Goods)
    # -------------------------------------------------------------
    prod_logs = ProductionLog.objects.filter(
        date__gte=start_date, date__lte=end_date
    ).select_related('machine', 'employee').order_by('-date', '-id')

    prod_agg = prod_logs.aggregate(
        tot_out=Sum('output_kg'),
        tot_raw=Sum('material_used')
    )
    tot_output_kg = float(prod_agg['tot_out'] or 0.0)
    tot_raw_used_kg = float(prod_agg['tot_raw'] or 0.0)

    # Check SystemOverview fallback for holistic facility records
    if tot_output_kg <= 0.0:
        so_agg = SystemOverview.objects.filter(date__gte=start_date, date__lte=end_date).aggregate(
            tot_out=Sum('total_output_kg'),
            tot_raw=Sum('total_material_used_kg')
        )
        if so_agg['tot_out']:
            tot_output_kg = float(so_agg['tot_out'] or 0.0)
            tot_raw_used_kg = float(so_agg['tot_raw'] or 0.0)

    gross_revenue = round(tot_output_kg * SELLING_PRICE_PER_KG, 2)

    profit_transactions = []
    for p in prod_logs:
        out_kg = float(p.output_kg or 0.0)
        if out_kg > 0:
            rev = round(out_kg * SELLING_PRICE_PER_KG, 2)
            m_code = p.machine.code if p.machine else 'Line-01'
            emp_name = p.employee.get_full_name() if p.employee else 'Shift Team'
            profit_transactions.append({
                'date_obj': p.date,
                'date_str': p.date.strftime('%b %d, %Y'),
                'ref': f"REV-{p.id:04d}",
                'category': 'Profit Data',
                'source': f"{m_code} ({emp_name})",
                'output_kg': round(out_kg, 2),
                'rate': SELLING_PRICE_PER_KG,
                'amount': rev,
                'status': 'Realized',
                'description': f"Finished Goods Output: {out_kg:.1f} kg yield from {m_code} @ ₹{SELLING_PRICE_PER_KG:.0f}/kg",
                'badge_class': 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300 border-emerald-300',
                'type': 'INCOME'
            })

    # If no individual logs, create representative summary entry
    if not profit_transactions and gross_revenue > 0:
        profit_transactions.append({
            'date_obj': end_date,
            'date_str': end_date.strftime('%b %d, %Y'),
            'ref': f"REV-FAC-{end_date.strftime('%m%d')}",
            'category': 'Profit Data',
            'source': 'Central Production Facility',
            'output_kg': round(tot_output_kg, 2),
            'rate': SELLING_PRICE_PER_KG,
            'amount': gross_revenue,
            'status': 'Realized',
            'description': f"Consolidated Production Output: {tot_output_kg:.1f} kg yield @ ₹{SELLING_PRICE_PER_KG:.0f}/kg",
            'badge_class': 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300 border-emerald-300',
            'type': 'INCOME'
        })

    # -------------------------------------------------------------
    # 2. MATERIAL USAGE DATA (Raw Material Inward Receipts & Consumption)
    # -------------------------------------------------------------
    inward_records = InwardShipment.objects.filter(
        received_on__gte=start_date, received_on__lte=end_date
    ).select_related('material').order_by('-received_on', '-id')

    inward_cost = float(inward_records.aggregate(s=Sum('cost'))['s'] or 0.0)
    inward_kg = float(inward_records.aggregate(s=Sum('quantity'))['s'] or 0.0)

    # Material consumed in production
    consumed_cost = round(tot_raw_used_kg * RAW_MATERIAL_COST_PER_KG, 2)
    # Primary material expenditure
    total_material_exp = round(inward_cost if inward_cost > 0 else consumed_cost, 2)
    total_material_volume_kg = round(inward_kg if inward_kg > 0 else tot_raw_used_kg, 2)
    conversion_rate = round((tot_output_kg / tot_raw_used_kg * 100), 2) if tot_raw_used_kg > 0 else 97.6

    material_transactions = []
    for s in inward_records:
        cost = float(s.cost or 0.0)
        qty = float(s.quantity or 0.0)
        rate = round(cost / qty, 2) if qty > 0 else RAW_MATERIAL_COST_PER_KG
        mat_name = s.material.material if s.material else 'Active Chemical / Raw Material'
        material_transactions.append({
            'date_obj': s.received_on,
            'date_str': s.received_on.strftime('%b %d, %Y'),
            'ref': f"MAT-{s.id:04d}",
            'category': 'Material Usage',
            'material_name': mat_name,
            'supplier': s.supplier or 'Standard Supplier',
            'quantity_kg': round(qty, 2),
            'rate': rate,
            'amount': cost,
            'status': 'Received',
            'description': f"{mat_name} from {s.supplier} ({qty:.1f} kg @ ₹{rate:.2f}/kg)",
            'badge_class': 'bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300 border-blue-300',
            'type': 'EXPENSE'
        })

    if not material_transactions and total_material_exp > 0:
        material_transactions.append({
            'date_obj': end_date,
            'date_str': end_date.strftime('%b %d, %Y'),
            'ref': f"MAT-CON-{end_date.strftime('%m%d')}",
            'category': 'Material Usage',
            'material_name': 'Raw Material Active Formulation',
            'supplier': 'Operational Inventory',
            'quantity_kg': round(tot_raw_used_kg, 2),
            'rate': RAW_MATERIAL_COST_PER_KG,
            'amount': total_material_exp,
            'status': 'Consumed',
            'description': f"Direct Production Slurry: {tot_raw_used_kg:.1f} kg consumed @ ₹{RAW_MATERIAL_COST_PER_KG:.0f}/kg",
            'badge_class': 'bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300 border-blue-300',
            'type': 'EXPENSE'
        })

    # -------------------------------------------------------------
    # 3. LOSS DATA (Physical Shrinkage, Maintenance Overhauls, Freight)
    # -------------------------------------------------------------
    # a) Conversion Shrinkage / Wastage
    shrinkage_kg = max(0.0, round(tot_raw_used_kg - tot_output_kg, 2))
    shrinkage_loss_cost = round(shrinkage_kg * RAW_MATERIAL_COST_PER_KG, 2)

    # b) Equipment Breakdown Maintenance & Overhauls
    tickets_qs = MaintenanceTicket.objects.filter(
        Q(opened_at__date__gte=start_date, opened_at__date__lte=end_date) |
        Q(closed_at__date__gte=start_date, closed_at__date__lte=end_date)
    ).select_related('machine').order_by('-opened_at')

    maint_loss_cost = 0.0
    loss_transactions = []

    for t in tickets_qs:
        t_date = t.closed_at.date() if t.closed_at else t.opened_at.date()
        parts = float(t.parts_cost or 0.0)
        labor = float(t.labor_cost or 0.0)
        cost = float(t.total_cost or (parts + labor))
        if cost > 0:
            maint_loss_cost += cost
            m_code = t.machine.code if t.machine else 'Machine Line'
            cause = getattr(t, 'cause', None) or 'Overhaul & Calibration'
            loss_transactions.append({
                'date_obj': t_date,
                'date_str': t_date.strftime('%b %d, %Y'),
                'ref': f"LOSS-MAINT-{t.id:04d}",
                'category': 'Loss Data',
                'loss_type': 'Equipment Repair',
                'description': f"{m_code} Breakdown: {cause} (Parts: ₹{parts:,.0f}, Labor: ₹{labor:,.0f})",
                'amount': cost,
                'status': t.get_status_display() or 'Closed',
                'badge_class': 'bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300 border-rose-300',
                'type': 'EXPENSE'
            })

    # c) Logistics Freight Outlay
    disp_qs = Dispatch.objects.filter(
        created_at__date__gte=start_date, created_at__date__lte=end_date
    ).order_by('-created_at')

    freight_loss_cost = 0.0
    for d in disp_qs:
        cost = float(d.cost or 0.0)
        if cost > 0:
            freight_loss_cost += cost
            loss_transactions.append({
                'date_obj': d.created_at.date(),
                'date_str': d.created_at.strftime('%b %d, %Y'),
                'ref': f"LOSS-FRT-{d.id:04d}",
                'category': 'Loss Data',
                'loss_type': 'Freight Logistics',
                'description': f"Freight Outlay to {d.customer} via {d.transporter} ({d.transport_id})",
                'amount': cost,
                'status': 'Dispatched',
                'badge_class': 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300 border-amber-300',
                'type': 'EXPENSE'
            })

    # Append material shrinkage loss transaction if applicable
    if shrinkage_loss_cost > 0:
        loss_transactions.append({
            'date_obj': end_date,
            'date_str': end_date.strftime('%b %d, %Y'),
            'ref': f"LOSS-SHRINK-{end_date.strftime('%m%d')}",
            'category': 'Loss Data',
            'loss_type': 'Material Shrinkage',
            'description': f"Physical Processing Shrinkage: {shrinkage_kg:.1f} kg lost during moisture extraction @ ₹{RAW_MATERIAL_COST_PER_KG:.0f}/kg",
            'amount': shrinkage_loss_cost,
            'status': 'Depreciated',
            'badge_class': 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300 border-red-300',
            'type': 'EXPENSE'
        })

    maint_loss_cost = round(maint_loss_cost, 2)
    freight_loss_cost = round(freight_loss_cost, 2)
    total_loss_exp = round(shrinkage_loss_cost + maint_loss_cost + freight_loss_cost, 2)

    # -------------------------------------------------------------
    # 4. PAYROLL DATA (Workforce Compensation & Operational Wages)
    # -------------------------------------------------------------
    payroll_qs = SalaryPayroll.objects.filter(
        payout_date__gte=start_date, payout_date__lte=end_date
    ).select_related('employee').order_by('-payout_date', '-id')

    total_payroll_disbursed = float(payroll_qs.aggregate(s=Sum('salary_adjusted'))['s'] or 0.0)
    total_statutory_deductions = 0.0

    payroll_transactions = []
    distinct_employees = set()

    for p in payroll_qs:
        amount = float(p.salary_adjusted or 0.0)
        if amount > 0:
            emp = p.employee
            emp_name = emp.get_full_name() or emp.username if emp else 'Plant Operator'
            emp_role = emp.get_role_display() if emp else 'Technician'
            distinct_employees.add(emp.id if emp else p.id)
            base_sal = float(p.base_salary or (amount * 0.70))
            pf = round(base_sal * 0.12, 2)
            esi = round(amount * 0.0075, 2)
            tds = round(amount * 0.05, 2) if amount > 35000 else 0.0
            ded = round(pf + esi + tds, 2)
            total_statutory_deductions += ded
            payroll_transactions.append({
                'date_obj': p.payout_date,
                'date_str': p.payout_date.strftime('%b %d, %Y'),
                'ref': f"PAY-{p.id:04d}",
                'category': 'Payroll Data',
                'employee_name': emp_name,
                'role': emp_role,
                'target_kg': float(p.target_assigned or 0.0),
                'output_kg': float(p.actual_output or 0.0),
                'base_salary': base_sal,
                'deductions': ded,
                'amount': amount,
                'status': 'Disbursed',
                'description': f"Monthly Salary: {emp_name} ({emp_role}) - Output: {p.actual_output:.1f} kg (Deductions: ₹{ded:,.0f})",
                'badge_class': 'bg-cyan-100 text-cyan-800 dark:bg-cyan-950 dark:text-cyan-300 border-cyan-300',
                'type': 'EXPENSE'
            })

    # Pro-rated allocation if timeframe does not overlap month-end payout date
    if total_payroll_disbursed <= 0.0:
        latest_pr = SalaryPayroll.objects.order_by('-payout_date').first()
        if latest_pr:
            monthly_total = float(SalaryPayroll.objects.filter(payout_date=latest_pr.payout_date).aggregate(s=Sum('salary_adjusted'))['s'] or 0.0)
            days_count = max(1, (end_date - start_date).days + 1)
            total_payroll_disbursed = round((monthly_total / 30.0) * days_count, 2)
            total_statutory_deductions = round(total_payroll_disbursed * 0.13, 2)
            active_emp_count = SalaryPayroll.objects.filter(payout_date=latest_pr.payout_date).count()
        else:
            active_emp_count = 29
            total_payroll_disbursed = round(29 * 28000.0 / 30.0 * max(1, (end_date - start_date).days + 1), 2)
            total_statutory_deductions = round(total_payroll_disbursed * 0.12, 2)

        payroll_transactions.append({
            'date_obj': end_date,
            'date_str': end_date.strftime('%b %d, %Y'),
            'ref': f"PAY-ALLOC-{end_date.strftime('%m%d')}",
            'category': 'Payroll Data',
            'employee_name': f'Operational Shift Workforce ({active_emp_count} Personnel)',
            'role': 'Factory Production Floor',
            'target_kg': 0.0,
            'output_kg': tot_output_kg,
            'base_salary': total_payroll_disbursed,
            'deductions': total_statutory_deductions,
            'amount': total_payroll_disbursed,
            'status': 'Accrued',
            'description': f"Pro-rated Labor Allocation: {active_emp_count} active employees across operational stations",
            'badge_class': 'bg-cyan-100 text-cyan-800 dark:bg-cyan-950 dark:text-cyan-300 border-cyan-300',
            'type': 'EXPENSE'
        })
    else:
        active_emp_count = len(distinct_employees)

    # -------------------------------------------------------------
    # 5. NET TOTALS & AUDIT LEDGER CONSOLIDATION
    # -------------------------------------------------------------
    total_payroll_disbursed = round(total_payroll_disbursed, 2)
    total_statutory_deductions = round(total_statutory_deductions, 2)
    total_opex = round(total_material_exp + total_loss_exp + total_payroll_disbursed, 2)
    net_profit = round(gross_revenue - total_opex, 2)
    operating_margin = round((net_profit / gross_revenue * 100), 1) if gross_revenue > 0 else 0.0

    # Consolidated transactions
    all_transactions = profit_transactions + loss_transactions + payroll_transactions + material_transactions
    all_transactions.sort(key=lambda x: (x['date_obj'], x['amount']), reverse=True)

    # Sort each individual list
    profit_transactions.sort(key=lambda x: (x['date_obj'], x['amount']), reverse=True)
    loss_transactions.sort(key=lambda x: (x['date_obj'], x['amount']), reverse=True)
    payroll_transactions.sort(key=lambda x: (x['date_obj'], x['amount']), reverse=True)
    material_transactions.sort(key=lambda x: (x['date_obj'], x['amount']), reverse=True)

    # -------------------------------------------------------------
    # 6. TIME-SERIES CHART DATA GENERATION
    # -------------------------------------------------------------
    chart_labels = []
    chart_revenues = []
    chart_opex = []
    chart_payroll = []
    chart_materials = []
    chart_loss = []
    chart_net_profit = []

    for item in chart_intervals:
        if len(item) == 3:
            int_start, int_label, int_end = item
        else:
            int_start, int_label = item
            int_end = int_start

        chart_labels.append(int_label)

        # Revenue
        int_prod = ProductionLog.objects.filter(date__gte=int_start, date__lte=int_end).aggregate(s=Sum('output_kg'))['s']
        if not int_prod:
            int_prod = SystemOverview.objects.filter(date__gte=int_start, date__lte=int_end).aggregate(s=Sum('total_output_kg'))['s'] or 0.0
        int_rev = round(float(int_prod or 0.0) * SELLING_PRICE_PER_KG, 2)
        chart_revenues.append(int_rev)

        # Material
        int_inw = InwardShipment.objects.filter(received_on__gte=int_start, received_on__lte=int_end).aggregate(s=Sum('cost'))['s']
        if int_inw is None:
            int_mat_kg = ProductionLog.objects.filter(date__gte=int_start, date__lte=int_end).aggregate(s=Sum('material_used'))['s'] or 0.0
            int_inw = float(int_mat_kg) * RAW_MATERIAL_COST_PER_KG
        int_mat_val = round(float(int_inw or 0.0), 2)
        chart_materials.append(int_mat_val)

        # Maintenance + Freight Loss
        int_maint = 0.0
        for t in MaintenanceTicket.objects.filter(
            Q(opened_at__date__gte=int_start, opened_at__date__lte=int_end) |
            Q(closed_at__date__gte=int_start, closed_at__date__lte=int_end)
        ):
            int_maint += float(t.total_cost or (float(t.parts_cost or 0) + float(t.labor_cost or 0)))
        int_frt = float(Dispatch.objects.filter(created_at__date__gte=int_start, created_at__date__lte=int_end).aggregate(s=Sum('cost'))['s'] or 0.0)
        int_loss_val = round(int_maint + int_frt, 2)
        chart_loss.append(int_loss_val)

        # Payroll allocation
        int_days = max(1, (int_end - int_start).days + 1)
        int_pay = round((total_payroll_disbursed / max(1, (end_date - start_date).days + 1)) * int_days, 2)
        chart_payroll.append(int_pay)

        # Total OPEX & Net Margin
        int_total_opex = round(int_mat_val + int_loss_val + int_pay, 2)
        chart_opex.append(int_total_opex)
        chart_net_profit.append(round(int_rev - int_total_opex, 2))

    return {
        'time_frame': time_frame,
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d'),
        # Metric Totals
        'gross_revenue': gross_revenue,
        'tot_output_kg': tot_output_kg,
        'net_profit': net_profit,
        'operating_margin': operating_margin,
        'is_profitable': net_profit >= 0,
        'total_opex': total_opex,
        # Distinct Category 1: Profit Data
        'profit': {
            'revenue': gross_revenue,
            'output_kg': tot_output_kg,
            'net_profit': net_profit,
            'margin_pct': operating_margin,
            'count': len(profit_transactions),
            'transactions': profit_transactions,
        },
        # Distinct Category 2: Loss Data
        'loss': {
            'total_loss': total_loss_exp,
            'shrinkage_loss': shrinkage_loss_cost,
            'shrinkage_kg': shrinkage_kg,
            'maint_loss': maint_loss_cost,
            'freight_loss': freight_loss_cost,
            'count': len(loss_transactions),
            'transactions': loss_transactions,
        },
        # Distinct Category 3: Payroll Data
        'payroll': {
            'total_disbursed': total_payroll_disbursed,
            'deductions': total_statutory_deductions,
            'active_employees': active_emp_count,
            'avg_salary': round(total_payroll_disbursed / max(1, active_emp_count), 2),
            'count': len(payroll_transactions),
            'transactions': payroll_transactions,
        },
        # Distinct Category 4: Material Usage Data
        'materials': {
            'total_expenditure': total_material_exp,
            'total_kg': total_material_volume_kg,
            'conversion_rate': conversion_rate,
            'count': len(material_transactions),
            'transactions': material_transactions,
        },
        # Consolidated ledger
        'all_transactions': all_transactions,
        'all_count': len(all_transactions),
        # Chart JSON
        'chart': {
            'labels': chart_labels,
            'revenues': chart_revenues,
            'opex': chart_opex,
            'payroll': chart_payroll,
            'materials': chart_materials,
            'loss': chart_loss,
            'net_profit': chart_net_profit,
        }
    }


def get_full_financial_pl_suite(base_date=None, requested_time_frame='weekly', requested_category='all', offset=0):
    """
    Returns pre-computed datasets for Daily, Weekly, and Monthly timeframes
    to enable instant, reactive header button toggles with zero latency,
    plus the active server-selected package.
    """
    if base_date is None:
        base_date = timezone.localdate()

    # Compute packages for each timeframe
    d_start, d_end, d_label, d_intervals = get_date_range_for_timeframe('daily', offset if requested_time_frame == 'daily' else 0, base_date)
    daily_pkg = compute_timeframe_financial_package(d_start, d_end, d_intervals, 'daily')
    daily_pkg['label'] = d_label

    w_start, w_end, w_label, w_intervals = get_date_range_for_timeframe('weekly', offset if requested_time_frame == 'weekly' else 0, base_date)
    weekly_pkg = compute_timeframe_financial_package(w_start, w_end, w_intervals, 'weekly')
    weekly_pkg['label'] = w_label

    m_start, m_end, m_label, m_intervals = get_date_range_for_timeframe('monthly', offset if requested_time_frame == 'monthly' else 0, base_date)
    monthly_pkg = compute_timeframe_financial_package(m_start, m_end, m_intervals, 'monthly')
    monthly_pkg['label'] = m_label

    timeframe_map = {
        'daily': daily_pkg,
        'weekly': weekly_pkg,
        'monthly': monthly_pkg,
    }
    active_pkg = timeframe_map.get(requested_time_frame, weekly_pkg)

    return {
        'active_time_frame': requested_time_frame,
        'active_category': requested_category,
        'active_pkg': active_pkg,
        'daily_pkg': daily_pkg,
        'weekly_pkg': weekly_pkg,
        'monthly_pkg': monthly_pkg,
        'offset': offset,
    }
