from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from .decorators import role_required
from django.contrib import messages
from django.db.models import Sum, Avg, Count, Q
from django.utils import timezone
from datetime import timedelta, datetime
from apps.maintenance.models import Machine, MachineHistoricalMetrics, MaintenanceTicket
from apps.production.models import ProductionLog
from django.core.cache import cache
import json

User = get_user_model()

def login_view(request):
    if request.method == 'POST':
        u = request.POST.get('username')
        p = request.POST.get('password')
        
        # FR-1.1: Support both username and email for login
        if '@' in u:
            try:
                user_obj = get_user_model().objects.get(email=u)
                u = user_obj.username
            except get_user_model().DoesNotExist:
                pass
                
        user = authenticate(request, username=u, password=p)
        if user is not None:
            if not user.is_active:
                messages.error(request, "Your account is pending Admin KYC approval. You cannot access the portal yet.")
                return redirect('login')
                
            login(request, user)
            # FR-1.1: Redirect to the role's dashboard
            if user.role == 'AD':
                return redirect('dashboard')
            elif user.role == 'PM' or user.role == 'EM':
                return redirect('production_manager_dashboard')
            elif user.role == 'SU':
                return redirect('supervisor_portal')
            elif user.role == 'LO':
                return redirect('inventory_dashboard')
            elif user.role == 'MA':
                return redirect('equipment')
            else:
                return redirect('dashboard')
        else:
            messages.error(request, "Invalid username or password.")
    return render(request, 'login.html')

def logout_view(request):
    logout(request)
    return redirect('login')

def signup_view(request):
    if request.method == 'POST':
        work_email = request.POST.get('work_email')
        full_name = request.POST.get('full_name')
        selected_role = request.POST.get('role')
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists. Please choose another one.")
            return redirect('signup')
            
        role_map = {
            "Maintenance Tech": "MA",
            "Equipments Manager": "MA",
            "Supervisor": "SU",
            "Production": "PM",
            "Local Operator": "EM",
            "Logistics": "LO"
        }
        
        user_role = role_map.get(selected_role, "EM")
        
        new_user = User.objects.create_user(username=username, password=password, email=work_email, role=user_role)
        new_user.first_name = full_name
        new_user.is_active = False # Requires Admin KYC approval
        new_user.save()
        
        messages.success(request, "KYC Submitted! Your account is pending Admin verification. Once approved, you can log in with your chosen password.")
        return redirect('login')
        
    return render(request, 'signup.html')

@login_required(login_url='/login/')
@role_required('AD')
def user_management_view(request):
    from apps.accounts.models import Shift
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'approve_kyc':
            user_id = request.POST.get('user_id')
            if user_id:
                u = User.objects.get(id=user_id)
                u.is_active = True
                u.save()
                messages.success(request, f"KYC Approved for {u.username}!")
            return redirect('user_management')
            
        elif action == 'create_user':
            username = request.POST.get('username')
            password = request.POST.get('password')
            role = request.POST.get('role')
            shift_id = request.POST.get('shift_id')
            machine_id = request.POST.get('machine_id')
            
            if not User.objects.filter(username=username).exists():
                new_user = User.objects.create_user(username=username, password=password, role=role)
                if shift_id:
                    new_user.shift = Shift.objects.get(id=shift_id)
                if machine_id:
                    new_user.machine = Machine.objects.get(id=machine_id)
                new_user.save()
                messages.success(request, f"User {username} successfully registered!")
            else:
                messages.error(request, f"User {username} already exists.")
            return redirect('user_management')
            
    context = {
        'all_users': list(User.objects.select_related('shift', 'machine').order_by('-date_joined')),
        'roles': User.Role.choices,
        'shifts': list(Shift.objects.all()),
        'machines': list(Machine.objects.all())
    }
    return render(request, 'user_management.html', context)

@login_required(login_url='/login/')
def dashboard_view(request):
    user = request.user
    if user.is_authenticated and user.role != 'AD':
        if user.role in ['PM', 'EM']:
            return redirect('production_manager_dashboard')
        elif user.role == 'SU':
            return redirect('supervisor_portal')
        elif user.role == 'LO':
            return redirect('inventory_dashboard')
        elif user.role == 'MA':
            return redirect('equipment')
            
    try:
        week_offset = int(request.GET.get('week_offset', 0))
    except ValueError:
        week_offset = 0
        
    today = timezone.now().date()
    cache_key = f'admin_dashboard_stats_{week_offset}_{today}'
    cached_context = cache.get(cache_key)
    if cached_context is not None:
        return render(request, 'dashboard.html', cached_context)

    # Make Sunday the start of the week: weekday() is 0 for Mon, 6 for Sun.
    idx = (today.weekday() + 1) % 7
    start_of_week = today - timedelta(days=idx) + timedelta(weeks=week_offset)
    end_of_week = start_of_week + timedelta(days=6)
    
    # Pre-fill 7 days array (Sun to Sat)
    days = []
    chart_dates = []
    uptime_data_dict = {}
    yield_data_dict = {}
    for i in range(7):
        d = start_of_week + timedelta(days=i)
        days.append(d)
        chart_dates.append(d.strftime('%a')) # 'Sun', 'Mon', etc.
        uptime_data_dict[d] = 0.0
        yield_data_dict[d] = 0.0
    
    # --- Chart 1: Vibration over week ---
    metrics = MachineHistoricalMetrics.objects.filter(date__gte=start_of_week, date__lte=end_of_week).values('date').annotate(avg_vibration=Avg('vibration'))
    for m in metrics:
        if m['date'] in uptime_data_dict:
            uptime_data_dict[m['date']] = float(round(m['avg_vibration'], 1))
            
    # Fallback to MachinePrediction for Vibration
    from apps.maintenance.models import MachinePrediction
    predictions = MachinePrediction.objects.filter(date__gte=start_of_week, date__lte=end_of_week).values('date').annotate(avg_vibration=Avg('predicted_vibration'))
    for p in predictions:
        if p['date'] in uptime_data_dict and uptime_data_dict[p['date']] == 0.0:
            uptime_data_dict[p['date']] = float(round(p['avg_vibration'], 1))

    uptime_data = [uptime_data_dict[d] for d in days]
        
    # --- Chart 2: Production Yield % over week ---
    prod_logs = ProductionLog.objects.filter(date__gte=start_of_week, date__lte=end_of_week).values('date').annotate(total_raw=Sum('material_used'), total_out=Sum('output_kg'))
    for p in prod_logs:
        if p['date'] in yield_data_dict and p['total_raw'] and p['total_raw'] > 0:
            yield_data_dict[p['date']] = float(round((p['total_out'] / p['total_raw']) * 100, 1))
            
    # Fallback to SystemOverview for Yield
    from apps.production.models import SystemOverview
    system_overviews = SystemOverview.objects.filter(date__gte=start_of_week, date__lte=end_of_week)
    for so in system_overviews:
        if so.date in yield_data_dict and yield_data_dict[so.date] == 0.0:
            if so.total_material_used_kg and so.total_material_used_kg > 0:
                yield_data_dict[so.date] = float(round((so.total_output_kg / so.total_material_used_kg) * 100, 1))

    yield_data = [yield_data_dict[d] for d in days]

    # --- Chart 3: Production Output by Machine (Pie) ---
    machine_output = ProductionLog.objects.filter(date__gte=start_of_week, date__lte=end_of_week).values('machine__code').annotate(total_out=Sum('output_kg'))
    pie_labels = [mo['machine__code'] for mo in machine_output]
    pie_data = [float(mo['total_out']) for mo in machine_output]

    # --- Inventory & Logistics Data ---
    from apps.logistics.models import Dispatch
    from apps.production.models import SystemAlert
    
    # Fetch autonomous decisions from SystemAlerts
    system_alerts = list(SystemAlert.objects.order_by('-created_at')[:10])
    recent_dispatches = list(Dispatch.objects.order_by('-created_at')[:4])

    # General Stats
    open_tickets = MaintenanceTicket.objects.filter(status='O').count()
    machine_counts = Machine.objects.aggregate(
        warning=Count('id', filter=Q(status='PI')),
        down=Count('id', filter=Q(status='UM'))
    )
    machines_warning = machine_counts['warning'] or 0
    machines_down = machine_counts['down'] or 0
    
    context = {
        'week_offset': week_offset,
        'start_of_week': start_of_week,
        'end_of_week': end_of_week,
        'chart_dates_json': json.dumps(chart_dates),
        'uptime_data_json': json.dumps(uptime_data),
        'yield_data_json': json.dumps(yield_data),
        'pie_labels_json': json.dumps(pie_labels),
        'pie_data_json': json.dumps(pie_data),
        'system_alerts': system_alerts,
        'recent_dispatches': recent_dispatches,
        'open_tickets': open_tickets,
        'machines_warning': machines_warning,
        'machines_down': machines_down,
    }
    
    cache.set(cache_key, context, timeout=60)
    return render(request, 'dashboard.html', context)

@login_required(login_url='/login/')
@role_required('AD')
def reports_view(request):
    from apps.production.models import ProductionLog, ProductionTarget
    from apps.maintenance.models import MachineHistoricalMetrics, MaintenanceTicket
    from apps.logistics.models import Dispatch
    
    target_date_str = request.GET.get('date')
    if target_date_str:
        try:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        except ValueError:
            target_date = timezone.now().date()
    else:
        target_date = timezone.now().date()
        
    cache_key = f'reports_view_{target_date}'
    cached_context = cache.get(cache_key)
    if cached_context is not None:
        return render(request, 'report.html', cached_context)

    # --- Production & Employee Data (bulk fetched with select_related) ---
    logs = list(ProductionLog.objects.filter(date=target_date).select_related('employee', 'employee__shift'))
    
    PRICE_PER_KG = 50.0  # Selling price per kg
    COST_PER_KG = 20.0   # Raw material (cardboard, etc) cost per kg
    
    emp_map = {}
    total_production = 0.0
    total_material = 0.0
    
    for log in logs:
        emp = log.employee
        if not emp:
            continue
        if emp.id not in emp_map:
            emp_map[emp.id] = {
                'employee': emp,
                'out_kg': 0.0,
                'mat_used': 0.0,
            }
        emp_map[emp.id]['out_kg'] += float(log.output_kg or 0.0)
        emp_map[emp.id]['mat_used'] += float(log.material_used or 0.0)
        total_production += float(log.output_kg or 0.0)
        total_material += float(log.material_used or 0.0)
        
    emp_ids = list(emp_map.keys())
    existing_targets = {
        t.employee_id: t 
        for t in ProductionTarget.objects.filter(date=target_date, employee_id__in=emp_ids)
    }
    
    new_targets = []
    for i, emp_id in enumerate(emp_ids):
        if emp_id not in existing_targets:
            default_target = 300.0 + (i * 50.0)
            new_target = ProductionTarget(
                date=target_date,
                employee_id=emp_id,
                target_kg=default_target
            )
            new_targets.append(new_target)
            existing_targets[emp_id] = new_target
            
    if new_targets:
        ProductionTarget.objects.bulk_create(new_targets, ignore_conflicts=True)
        
    employee_data = []
    for emp_id, data in emp_map.items():
        emp = data['employee']
        out_kg = data['out_kg']
        mat_used = data['mat_used']
        
        revenue = out_kg * PRICE_PER_KG
        expense = mat_used * COST_PER_KG
        profit = revenue - expense
        
        target_obj = existing_targets.get(emp_id)
        target_kg = float(target_obj.target_kg) if target_obj else 300.0
        target_achieved = (target_kg > 0 and out_kg >= target_kg)
        
        shift_name = emp.shift.name if emp.shift else 'No Shift'
        
        employee_data.append({
            'employee': emp,
            'shift': shift_name,
            'output': out_kg,
            'material': mat_used,
            'profit': profit,
            'target': target_kg,
            'target_achieved': target_achieved,
        })
        
    # --- Maintenance & Logistics Data ---
    metrics_count = MachineHistoricalMetrics.objects.filter(date=target_date).count()
    tickets = list(MaintenanceTicket.objects.select_related('machine').filter(opened_at__date=target_date))
    dispatches = list(Dispatch.objects.filter(created_at__date=target_date))
    
    # --- Chart Data Preparation ---
    chart_emp_names = []
    chart_emp_outputs = []
    chart_emp_targets = []
    chart_emp_profits = []
    shift_output = {'Morning Shift': 0, 'Evening Shift': 0, 'Night Shift': 0, 'No Shift': 0}
    
    employee_data.sort(key=lambda x: x['output'], reverse=True)
    
    for item in employee_data:
        chart_emp_names.append(item['employee'].first_name or item['employee'].username)
        chart_emp_outputs.append(item['output'])
        chart_emp_targets.append(item['target'])
        chart_emp_profits.append(item['profit'])
        
        shift_name = item['shift']
        if shift_name in shift_output:
            shift_output[shift_name] += item['output']
        else:
            shift_output['No Shift'] += item['output']
            
    shift_labels = [k for k, v in shift_output.items() if v > 0]
    shift_data = [v for k, v in shift_output.items() if v > 0]
    
    context = {
        'target_date': target_date,
        'target_date_str': target_date.strftime('%Y-%m-%d'),
        'employee_data': employee_data,
        'total_production': total_production,
        'total_material': total_material,
        'metrics_count': metrics_count,
        'tickets': tickets,
        'dispatches': dispatches,
        'chart_emp_names_json': json.dumps(chart_emp_names),
        'chart_emp_outputs_json': json.dumps(chart_emp_outputs),
        'chart_emp_targets_json': json.dumps(chart_emp_targets),
        'chart_emp_profits_json': json.dumps(chart_emp_profits),
        'shift_labels_json': json.dumps(shift_labels),
        'shift_data_json': json.dumps(shift_data),
    }
    
    cache.set(cache_key, context, timeout=60)
    return render(request, 'report.html', context)

