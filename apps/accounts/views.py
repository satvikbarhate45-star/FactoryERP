from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from .decorators import role_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum, Avg, Count, Q
from django.utils import timezone
from datetime import timedelta, datetime
from apps.maintenance.models import Machine, MachineHistoricalMetrics, MaintenanceTicket
from apps.production.models import ProductionLog
from django.core.cache import cache
import json
import logging

logger = logging.getLogger(__name__)
User = get_user_model()

def login_view(request):
    if request.method == 'POST':
        u = (request.POST.get('username') or '').strip()
        p = request.POST.get('password') or ''
        
        # FR-1.1: Support both username and email for login
        if '@' in u:
            try:
                user_obj = get_user_model().objects.get(email=u)
                u = user_obj.username
            except get_user_model().DoesNotExist:
                pass
                
        user = authenticate(request, username=u, password=p)
        if user is not None:
            # Check KYC Status and Active state
            kyc_stat = getattr(user, 'kyc_status', None)
            if kyc_stat == User.KYCStatus.REJECTED:
                reason = user.rejection_reason or "Verification criteria not met."
                messages.error(request, f"Your KYC registration was rejected by Admin. Reason: {reason}")
                return redirect('login')
            elif kyc_stat == User.KYCStatus.PENDING or not user.is_active:
                messages.error(request, "Your account is pending Admin KYC approval. You cannot access the portal yet.")
                return redirect('login')
                
            login(request, user)
            logger.info("User %s successfully logged in with role %s", user.username, user.role)
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
        try:
            from .schema_guard import ensure_runtime_schema_integrity
            ensure_runtime_schema_integrity(force=False)
        except Exception as sg_err:
            logger.warning("Schema guard notice in signup: %s", sg_err)

        work_email = (request.POST.get('work_email') or '').strip()
        full_name = (request.POST.get('full_name') or '').strip()
        selected_role = (request.POST.get('role') or '').strip()
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        phone = (request.POST.get('phone') or '').strip()
        whatsapp = (request.POST.get('whatsapp') or '').strip()
        pan = (request.POST.get('pan') or '').strip()
        government_id = (request.POST.get('government_id') or '').strip()
        account_number = (request.POST.get('account_number') or '').strip()
        ifsc = (request.POST.get('ifsc') or '').strip()
        photo = request.FILES.get('photo')

        if not username or not password:
            messages.error(request, "Username and password are required.")
            return redirect('signup')

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists. Please choose another one.")
            return redirect('signup')

        if work_email and User.objects.filter(email=work_email).exists():
            messages.error(request, "An account with this work email already exists.")
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

        try:
            with transaction.atomic():
                new_user = User.objects.create_user(
                    username=username,
                    password=password,
                    email=work_email,
                    role=user_role
                )
                new_user.first_name = full_name
                new_user.phone = phone
                new_user.whatsapp = whatsapp
                new_user.pan = pan
                new_user.government_id = government_id
                new_user.account_number = account_number
                new_user.ifsc = ifsc
                new_user.kyc_status = User.KYCStatus.PENDING
                new_user.is_active = False # Default: Requires Admin KYC approval
                if photo:
                    new_user.photo = photo

                # Dynamic Employee Allocation Sync:
                if user_role == 'EM':
                    active_sup = User.objects.filter(role='SU', is_active=True).first()
                    if active_sup:
                        new_user.supervisor = active_sup
                    default_shift = Shift.objects.first()
                    if default_shift:
                        new_user.shift = default_shift
                    default_mach = Machine.objects.first()
                    if default_mach:
                        new_user.machine = default_mach

                new_user.save()
                cache.clear()

                logger.info("New employee KYC registration created: username=%s, role=%s, kyc=PENDING", username, user_role)
                messages.success(request, "KYC Submitted! Your account status is 'Pending' Admin verification. Once approved, you can log in with your credentials.")
                return redirect('login')
        except Exception as exc:
            logger.exception("Error creating user during signup: %s", exc)
            try:
                from .schema_guard import ensure_runtime_schema_integrity
                ensure_runtime_schema_integrity(force=True)
            except Exception:
                pass
            messages.error(request, f"Registration failed due to server error: {exc}")
            return redirect('signup')

    return render(request, 'signup.html')

@login_required(login_url='/login/')
@role_required('AD')
def user_management_view(request):
    from apps.accounts.models import Shift

    redirect_url = request.path or 'user_management'

    if request.method == 'POST':
        try:
            from .schema_guard import ensure_runtime_schema_integrity
            ensure_runtime_schema_integrity(force=False)
        except Exception as sg_err:
            logger.warning("Schema guard notice in user_management: %s", sg_err)

        action = request.POST.get('action')

        if action == 'approve_kyc':
            user_id = request.POST.get('user_id')
            if user_id:
                try:
                    with transaction.atomic():
                        u = User.objects.filter(id=int(user_id)).first()
                        if not u:
                            messages.error(request, f"Employee #{user_id} not found.")
                            return redirect(redirect_url)
                        u.kyc_status = User.KYCStatus.APPROVED
                        u.is_active = True
                        u.rejection_reason = None
                        u.kyc_reviewed_by = request.user
                        u.kyc_reviewed_at = timezone.now()

                        # Dynamic allocation synchronization:
                        if u.role == 'EM':
                            if not u.supervisor:
                                sup = User.objects.filter(role='SU', is_active=True).first()
                                if sup:
                                    u.supervisor = sup
                            if not u.shift:
                                u.shift = Shift.objects.first()
                            if not u.machine:
                                u.machine = Machine.objects.first()

                        u.save()
                        cache.clear()
                        logger.info("KYC Approved by Admin %s for employee %s", request.user.username, u.username)
                        messages.success(request, f"KYC Approved! Employee {u.username} has been verified and granted active access.")
                except Exception as exc:
                    logger.exception("Error approving KYC for user_id %s: %s", user_id, exc)
                    messages.error(request, f"Error saving KYC approval: {exc}")
            return redirect(redirect_url)

        elif action == 'reject_kyc':
            user_id = request.POST.get('user_id')
            rejection_reason = (request.POST.get('rejection_reason') or '').strip()

            # MANDATORY REJECTION REASON CHECK
            if not rejection_reason:
                messages.error(request, "Rejection reason is mandatory when rejecting employee KYC verification.")
                return redirect(redirect_url)

            if user_id:
                try:
                    with transaction.atomic():
                        u = User.objects.filter(id=int(user_id)).first()
                        if not u:
                            messages.error(request, f"Employee #{user_id} not found.")
                            return redirect(redirect_url)
                        u.kyc_status = User.KYCStatus.REJECTED
                        u.is_active = False
                        u.rejection_reason = rejection_reason
                        u.kyc_reviewed_by = request.user
                        u.kyc_reviewed_at = timezone.now()
                        u.save()
                        cache.clear()
                        logger.warning("KYC Rejected by Admin %s for employee %s. Reason: %s", request.user.username, u.username, rejection_reason)
                        messages.success(request, f"KYC Rejected for {u.username}. Rejection reason securely stored.")
                except Exception as exc:
                    logger.exception("Error rejecting KYC for user_id %s: %s", user_id, exc)
                    messages.error(request, f"Error saving KYC rejection: {exc}")
            return redirect(redirect_url)

        elif action == 'create_user':
            username = (request.POST.get('username') or '').strip()
            password = request.POST.get('password') or ''
            role = (request.POST.get('role') or 'EM').strip()
            email = (request.POST.get('email') or '').strip()
            full_name = (request.POST.get('full_name') or '').strip()
            phone = (request.POST.get('phone') or '').strip()
            shift_id = (request.POST.get('shift_id') or '').strip()
            machine_id = (request.POST.get('machine_id') or '').strip()
            supervisor_id = (request.POST.get('supervisor_id') or '').strip()
            initial_status = (request.POST.get('kyc_status') or 'PENDING').strip().upper()

            if not username or not password:
                messages.error(request, "Username and temporary password are required.")
                return redirect(redirect_url)

            if User.objects.filter(username=username).exists():
                messages.error(request, f"User '{username}' already exists.")
                return redirect(redirect_url)

            try:
                with transaction.atomic():
                    new_user = User.objects.create_user(
                        username=username,
                        password=password,
                        email=email,
                        role=role
                    )
                    if full_name:
                        new_user.first_name = full_name
                    if phone:
                        new_user.phone = phone
                    if shift_id and shift_id.isdigit():
                        try:
                            new_user.shift = Shift.objects.get(id=int(shift_id))
                        except Shift.DoesNotExist:
                            pass
                    if machine_id and machine_id.isdigit():
                        try:
                            new_user.machine = Machine.objects.get(id=int(machine_id))
                        except Machine.DoesNotExist:
                            pass
                    if supervisor_id and supervisor_id.isdigit():
                        try:
                            new_user.supervisor = User.objects.get(id=int(supervisor_id))
                        except User.DoesNotExist:
                            pass
                    elif role == 'EM' and not new_user.supervisor:
                        new_user.supervisor = User.objects.filter(role='SU', is_active=True).first()

                    if initial_status == 'APPROVED':
                        new_user.kyc_status = User.KYCStatus.APPROVED
                        new_user.is_active = True
                        new_user.kyc_reviewed_by = request.user
                        new_user.kyc_reviewed_at = timezone.now()
                    else:
                        new_user.kyc_status = User.KYCStatus.PENDING
                        new_user.is_active = False

                    new_user.save()
                    cache.clear()
                    logger.info("Admin %s created user %s with KYC status %s", request.user.username, username, new_user.kyc_status)
                    messages.success(request, f"User {username} successfully registered with KYC status '{new_user.get_kyc_status_display()}'!")
            except Exception as exc:
                logger.exception("Failed to create user in user_management_view: %s", exc)
                try:
                    from .schema_guard import ensure_runtime_schema_integrity
                    ensure_runtime_schema_integrity(force=True)
                except Exception:
                    pass
                messages.error(request, f"Database error creating user: {exc}")
            return redirect(redirect_url)

        elif action == 'edit_user':
            user_id = request.POST.get('user_id')
            role = (request.POST.get('role') or '').strip()
            shift_id = (request.POST.get('shift_id') or '').strip()
            machine_id = (request.POST.get('machine_id') or '').strip()
            supervisor_id = (request.POST.get('supervisor_id') or '').strip()
            phone = (request.POST.get('phone') or '').strip()

            if user_id:
                try:
                    with transaction.atomic():
                        u = User.objects.filter(id=int(user_id)).first()
                        if not u:
                            messages.error(request, f"Employee #{user_id} not found.")
                            return redirect(redirect_url)
                        if role:
                            u.role = role
                        if shift_id and shift_id.isdigit():
                            try:
                                u.shift = Shift.objects.get(id=int(shift_id))
                            except Shift.DoesNotExist:
                                u.shift = None
                        elif not shift_id:
                            u.shift = None

                        if machine_id and machine_id.isdigit():
                            try:
                                u.machine = Machine.objects.get(id=int(machine_id))
                            except Machine.DoesNotExist:
                                u.machine = None
                        elif not machine_id:
                            u.machine = None

                        if supervisor_id and supervisor_id.isdigit():
                            try:
                                u.supervisor = User.objects.get(id=int(supervisor_id))
                            except User.DoesNotExist:
                                u.supervisor = None
                        elif 'supervisor_id' in request.POST and not supervisor_id:
                            u.supervisor = None

                        if phone:
                            u.phone = phone
                        u.save()
                        cache.clear()
                        logger.info("Admin %s updated user %s", request.user.username, u.username)
                        messages.success(request, f"Updated profile & assignments for {u.username}!")
                except Exception as exc:
                    logger.exception("Failed to edit user %s: %s", user_id, exc)
                    messages.error(request, f"Failed to update user: {exc}")
            return redirect(redirect_url)

    all_users = list(User.objects.select_related('shift', 'machine', 'supervisor', 'kyc_reviewed_by').order_by('-date_joined'))
    total_count = len(all_users)
    pending_count = sum(1 for u in all_users if u.kyc_status == User.KYCStatus.PENDING)
    approved_count = sum(1 for u in all_users if u.kyc_status == User.KYCStatus.APPROVED)
    rejected_count = sum(1 for u in all_users if u.kyc_status == User.KYCStatus.REJECTED)

    context = {
        'all_users': all_users,
        'total_count': total_count,
        'pending_count': pending_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'roles': User.Role.choices,
        'shifts': list(Shift.objects.all()),
        'machines': list(Machine.objects.all()),
        'supervisors': list(User.objects.filter(role='SU', is_active=True)),
    }
    return render(request, 'workmanagement.html', context)


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
        
    today = timezone.localdate()
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
            target_date = timezone.localdate()
    else:
        target_date = timezone.localdate()
        
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

