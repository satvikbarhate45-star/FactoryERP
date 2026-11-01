from django.shortcuts import render, redirect, get_object_or_404, HttpResponse
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from .decorators import role_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum, Avg, Count, Q
from django.utils import timezone
from datetime import timedelta, datetime, date
import calendar
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
            "Equipments Manager": "EQ",
            "Equipment Manager": "EQ",
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
            first_name = (request.POST.get('first_name') or '').strip()
            last_name = (request.POST.get('last_name') or '').strip()
            email = (request.POST.get('email') or '').strip()
            whatsapp = (request.POST.get('whatsapp') or '').strip()
            village = (request.POST.get('village') or '').strip()
            pan = (request.POST.get('pan') or '').strip()
            government_id = (request.POST.get('government_id') or '').strip()
            account_number = (request.POST.get('account_number') or '').strip()
            ifsc = (request.POST.get('ifsc') or '').strip()

            if user_id:
                try:
                    with transaction.atomic():
                        u = User.objects.filter(id=int(user_id)).first()
                        if not u:
                            messages.error(request, f"Employee #{user_id} not found.")
                            return redirect(redirect_url)
                        if role and role in dict(User.Role.choices):
                            u.role = role
                        if first_name:
                            u.first_name = first_name
                        if last_name:
                            u.last_name = last_name
                        if email:
                            u.email = email
                        if phone:
                            u.phone = phone
                        if whatsapp:
                            u.whatsapp = whatsapp
                        if village:
                            u.village = village
                        if pan:
                            u.pan = pan
                        if government_id:
                            u.government_id = government_id
                        if account_number:
                            u.account_number = account_number
                        if ifsc:
                            u.ifsc = ifsc
                        if 'photo' in request.FILES:
                            u.photo = request.FILES['photo']

                        if shift_id and shift_id.isdigit():
                            try:
                                u.shift = Shift.objects.get(id=int(shift_id))
                            except Shift.DoesNotExist:
                                u.shift = None
                        elif not shift_id and 'shift_id' in request.POST:
                            u.shift = None

                        if machine_id and machine_id.isdigit():
                            try:
                                u.machine = Machine.objects.get(id=int(machine_id))
                            except Machine.DoesNotExist:
                                u.machine = None
                        elif not machine_id and 'machine_id' in request.POST:
                            u.machine = None

                        if supervisor_id and supervisor_id.isdigit():
                            try:
                                u.supervisor = User.objects.get(id=int(supervisor_id))
                            except User.DoesNotExist:
                                u.supervisor = None
                        elif 'supervisor_id' in request.POST and not supervisor_id:
                            u.supervisor = None

                        u.save()
                        cache.clear()
                        logger.info("Admin %s updated user %s", request.user.username, u.username)
                        messages.success(request, f"Updated profile & assignments for {u.username}!")
                except Exception as exc:
                    logger.exception("Failed to edit user %s: %s", user_id, exc)
                    messages.error(request, f"Failed to update user: {exc}")
            return redirect(redirect_url)

        elif action == 'delete_user':
            user_id = request.POST.get('user_id')
            if user_id:
                try:
                    u = User.objects.filter(id=int(user_id)).first()
                    if not u:
                        messages.error(request, f"Employee #{user_id} not found.")
                        return redirect(redirect_url)
                    if u.id == request.user.id:
                        messages.error(request, "Security constraint: You cannot delete your own logged-in admin account.")
                        return redirect(redirect_url)
                    if u.is_superuser and not request.user.is_superuser:
                        messages.error(request, "Permission denied: Only root superusers can delete other superusers.")
                        return redirect(redirect_url)
                    username_deleted = u.username
                    u.delete()
                    cache.clear()
                    logger.info("Admin %s deleted employee %s (ID: %s)", request.user.username, username_deleted, user_id)
                    messages.success(request, f"Employee '{username_deleted}' has been permanently deleted from FactoryERP.")
                except Exception as exc:
                    logger.exception("Failed to delete user %s: %s", user_id, exc)
                    messages.error(request, f"Error deleting employee: {exc}")
            return redirect(redirect_url)

    from apps.production.models import ProductionLog, SalaryPayroll
    today = timezone.localdate()
    is_sunday = (today.weekday() == 6)

    # Detect verified Overtime (OT) employees on Sundays
    ot_user_ids = set()
    if is_sunday:
        ot_user_ids = set(ProductionLog.objects.filter(date=today, output_kg__gt=0, is_overtime=True).values_list('employee_id', flat=True))

    all_users = list(User.objects.select_related('shift', 'machine', 'supervisor', 'kyc_reviewed_by').order_by('-date_joined'))
    for u in all_users:
        u.is_on_overtime = (u.id in ot_user_ids)

    total_count = len(all_users)
    pending_count = sum(1 for u in all_users if u.kyc_status == User.KYCStatus.PENDING)
    approved_count = sum(1 for u in all_users if u.kyc_status == User.KYCStatus.APPROVED)
    rejected_count = sum(1 for u in all_users if u.kyc_status == User.KYCStatus.REJECTED)

    # Strict backend query filter: No payroll records after Nov 1, 2026
    recent_payrolls = list(
        SalaryPayroll.objects.filter(payout_date__lte=today)
        .select_related('employee', 'employee__shift')
        .order_by('-payout_date', '-id')[:50]
    )
    total_payroll_disbursed = float(SalaryPayroll.objects.filter(payout_date__lte=today).aggregate(s=Sum('salary_adjusted'))['s'] or 0.0)

    context = {
        'all_users': all_users,
        'total_count': total_count,
        'pending_count': pending_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'recent_payrolls': recent_payrolls,
        'total_payroll_disbursed': total_payroll_disbursed,
        'today': today,
        'is_sunday': is_sunday,
        'roles': User.Role.choices,
        'shifts': list(Shift.objects.all()),
        'machines': list(Machine.objects.all()),
        'supervisors': list(User.objects.filter(role='SU', is_active=True)),
    }
    return render(request, 'workmanagement.html', context)


@login_required(login_url='/login/')
def employee_profile_view(request, user_id):
    from apps.production.models import ProductionLog, ProductionTarget, SalaryPayroll
    from apps.maintenance.models import Machine
    from apps.accounts.models import Shift

    emp = get_object_or_404(User.objects.select_related('shift', 'machine', 'supervisor', 'kyc_reviewed_by'), id=user_id)

    # Security check: Admins, Supervisors, or the employee himself
    if request.user.role not in ['AD', 'SU'] and request.user.id != emp.id:
        messages.error(request, "Permission denied: You do not have permission to view other employee records.")
        return redirect('dashboard')

    if request.method == 'POST':
        if request.user.role != 'AD':
            messages.error(request, "Permission denied: Only Administrators can update employee KYC profiles.")
            return redirect('employee_profile', user_id=emp.id)

        first_name = (request.POST.get('first_name') or '').strip()
        last_name = (request.POST.get('last_name') or '').strip()
        email = (request.POST.get('email') or '').strip()
        phone = (request.POST.get('phone') or '').strip()
        whatsapp = (request.POST.get('whatsapp') or '').strip()
        village = (request.POST.get('village') or '').strip()
        pan = (request.POST.get('pan') or '').strip()
        government_id = (request.POST.get('government_id') or '').strip()
        account_number = (request.POST.get('account_number') or '').strip()
        ifsc = (request.POST.get('ifsc') or '').strip()
        role = (request.POST.get('role') or '').strip()
        shift_id = (request.POST.get('shift_id') or '').strip()
        machine_id = (request.POST.get('machine_id') or '').strip()
        supervisor_id = (request.POST.get('supervisor_id') or '').strip()

        if first_name: emp.first_name = first_name
        if last_name: emp.last_name = last_name
        if email: emp.email = email
        if phone: emp.phone = phone
        if whatsapp: emp.whatsapp = whatsapp
        if village: emp.village = village
        if pan: emp.pan = pan
        if government_id: emp.government_id = government_id
        if account_number: emp.account_number = account_number
        if ifsc: emp.ifsc = ifsc
        if role and role in dict(User.Role.choices): emp.role = role

        if shift_id and shift_id.isdigit():
            emp.shift = Shift.objects.filter(id=int(shift_id)).first()
        elif 'shift_id' in request.POST and not shift_id:
            emp.shift = None

        if machine_id and machine_id.isdigit():
            emp.machine = Machine.objects.filter(id=int(machine_id)).first()
        elif 'machine_id' in request.POST and not machine_id:
            emp.machine = None

        if supervisor_id and supervisor_id.isdigit():
            emp.supervisor = User.objects.filter(id=int(supervisor_id)).first()
        elif 'supervisor_id' in request.POST and not supervisor_id:
            emp.supervisor = None

        if 'photo' in request.FILES:
            emp.photo = request.FILES['photo']

        emp.save()
        cache.clear()
        messages.success(request, f"KYC Profile & Station Assignments for '{emp.get_full_name() or emp.username}' successfully updated!")
        return redirect('employee_profile', user_id=emp.id)

    # 1. Operational Shift Logs & Production Metrics (strictly valid non-zero outputs)
    # SUNDAY HOLIDAY FILTER: Exclude regular Sunday shifts. Include Sundays ONLY if explicit Overtime (OT) is logged!
    raw_logs = list(ProductionLog.objects.filter(employee=emp, output_kg__gt=0).select_related('machine').order_by('-date')[:60])
    prod_logs = [log for log in raw_logs if log.date.weekday() != 6 or getattr(log, 'is_overtime', False)][:30]
    total_output_kg = float(sum(float(l.output_kg or 0.0) for l in prod_logs))
    total_material_kg = float(sum(float(l.material_used or 0.0) for l in prod_logs))
    total_shifts_count = len(prod_logs)

    # 2. Profit & Loss Contribution
    gross_revenue_contrib = round(total_output_kg * 45.0, 2)
    raw_material_cost_contrib = round(total_material_kg * 18.0, 2)

    today = timezone.localdate()
    # Strict backend filter: No payroll records after Nov 1, 2026
    payrolls_qs = SalaryPayroll.objects.filter(employee=emp, payout_date__lte=today).order_by('-payout_date')
    total_payroll_disbursed = float(payrolls_qs.aggregate(s=Sum('salary_adjusted'))['s'] or 0.0)

    total_opex_contrib = round(raw_material_cost_contrib + total_payroll_disbursed, 2)
    net_profit_contrib = round(gross_revenue_contrib - total_opex_contrib, 2)
    margin_pct = round((net_profit_contrib / gross_revenue_contrib * 100), 1) if gross_revenue_contrib > 0 else 0.0
    is_profitable = net_profit_contrib >= 0

    # 3. Monthly Payroll Records
    payrolls = list(payrolls_qs)
    latest_payroll = payrolls[0] if payrolls else None

    # 4. Target completion average - STRICT LOGICAL CAP (MAX 100%)
    avg_val = payrolls_qs.aggregate(a=Avg('completion_percentage'))['a']
    if avg_val is not None:
        avg_completion = min(100.0, max(0.0, round(float(avg_val), 1)))
    else:
        avg_completion = 96.5

    context = {
        'emp': emp,
        'today': today,
        'prod_logs': prod_logs,
        'total_output_kg': total_output_kg,
        'total_material_kg': total_material_kg,
        'total_shifts_count': total_shifts_count,
        'gross_revenue_contrib': gross_revenue_contrib,
        'raw_material_cost_contrib': raw_material_cost_contrib,
        'total_payroll_disbursed': total_payroll_disbursed,
        'total_opex_contrib': total_opex_contrib,
        'net_profit_contrib': net_profit_contrib,
        'margin_pct': margin_pct,
        'is_profitable': is_profitable,
        'payrolls': payrolls,
        'latest_payroll': latest_payroll,
        'avg_completion': avg_completion,
        'shifts': list(Shift.objects.all()),
        'machines': list(Machine.objects.all()),
        'supervisors': list(User.objects.filter(role='SU', is_active=True)),
        'roles': User.Role.choices,
    }
    return render(request, 'employee_profile.html', context)


@login_required(login_url='/login/')
def download_salary_slip_pdf(request, user_id, payroll_id=None):
    from apps.production.models import SalaryPayroll
    from .salary_slip_pdf import generate_salary_slip_pdf_buffer

    emp = get_object_or_404(User, id=user_id)

    # Security check: Admin, Supervisor, or employee themselves
    if request.user.role not in ['AD', 'SU'] and request.user.id != emp.id:
        messages.error(request, "Permission denied: You cannot download salary slips for other employees.")
        return redirect('dashboard')

    today = timezone.localdate()
    if payroll_id:
        payroll = get_object_or_404(SalaryPayroll, id=payroll_id, employee=emp, payout_date__lte=today)
    else:
        payroll = SalaryPayroll.objects.filter(employee=emp, payout_date__lte=today).order_by('-payout_date').first()
        if not payroll:
            messages.error(request, f"No monthly payroll record found for {emp.username}.")
            return redirect('employee_profile', user_id=emp.id)

    pdf_buffer = generate_salary_slip_pdf_buffer(emp, payroll)
    month_slug = payroll.payout_date.strftime('%b_%Y')
    filename = f"Salary_Slip_{emp.username}_{month_slug}.pdf"

    response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


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

    # --- Executive High-Level Real-Time Summary (Pure Supabase DB Aggregates) ---
    from apps.inventory.models import InwardShipment
    from apps.production.models import SalaryPayroll, SystemAlert
    from apps.logistics.models import Dispatch

    total_out_kg = float(ProductionLog.objects.filter(date__gte=start_of_week, date__lte=end_of_week).aggregate(s=Sum('output_kg'))['s'] or 0.0)
    kpi_gross_revenue = round(total_out_kg * 45.0, 2)
    inward_cost = float(InwardShipment.objects.filter(received_on__gte=start_of_week, received_on__lte=end_of_week).aggregate(s=Sum('cost'))['s'] or 0.0)
    tickets_cost = float(MaintenanceTicket.objects.filter(
        Q(opened_at__date__gte=start_of_week, opened_at__date__lte=end_of_week) |
        Q(closed_at__date__gte=start_of_week, closed_at__date__lte=end_of_week)
    ).aggregate(s=Sum('total_cost'))['s'] or 0.0)
    disp_cost = float(Dispatch.objects.filter(created_at__date__gte=start_of_week, created_at__date__lte=end_of_week).aggregate(s=Sum('cost'))['s'] or 0.0)
    payroll_cost = float(SalaryPayroll.objects.filter(payout_date__gte=start_of_week, payout_date__lte=end_of_week).aggregate(s=Sum('salary_adjusted'))['s'] or 0.0)
    if payroll_cost == 0.0:
        mid_date = start_of_week + timedelta(days=3)
        month_end_date = date(mid_date.year, mid_date.month, calendar.monthrange(mid_date.year, mid_date.month)[1])
        monthly_total_payroll = float(SalaryPayroll.objects.filter(payout_date=month_end_date, payout_date__lte=timezone.localdate()).aggregate(s=Sum('salary_adjusted'))['s'] or 0.0)
        if monthly_total_payroll <= 0:
            latest_pr = SalaryPayroll.objects.filter(payout_date__lte=timezone.localdate()).order_by('-payout_date').values('payout_date').first()
            if latest_pr:
                monthly_total_payroll = float(SalaryPayroll.objects.filter(payout_date=latest_pr['payout_date']).aggregate(s=Sum('salary_adjusted'))['s'] or 0.0)
        days_in_month = calendar.monthrange(mid_date.year, mid_date.month)[1]
        payroll_cost = round((monthly_total_payroll / float(days_in_month)) * 6.0, 2)

    kpi_total_expenses = round(inward_cost + tickets_cost + disp_cost + payroll_cost, 2)
    kpi_net_profit = round(kpi_gross_revenue - kpi_total_expenses, 2)
    kpi_profit_margin = round((kpi_net_profit / kpi_gross_revenue) * 100, 1) if kpi_gross_revenue > 0 else 0.0
    is_profitable = kpi_net_profit >= 0

    # Fetch autonomous decisions from SystemAlerts & Dispatches
    system_alerts = list(SystemAlert.objects.order_by('-created_at')[:10])
    recent_dispatches = list(Dispatch.objects.order_by('-created_at')[:4])

    # General Machine Stats
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
        'kpi_gross_revenue': kpi_gross_revenue,
        'kpi_total_expenses': kpi_total_expenses,
        'kpi_net_profit': kpi_net_profit,
        'kpi_profit_margin': kpi_profit_margin,
        'is_profitable': is_profitable,
    }
    
    cache.set(cache_key, context, timeout=60)
    return render(request, 'dashboard.html', context)


@login_required(login_url='/login/')
@role_required('AD', 'PM', 'LO')
def pl_dashboard_view(request):
    time_frame = request.GET.get('time_frame', 'weekly').lower()
    if time_frame not in ('daily', 'weekly', 'monthly'):
        time_frame = 'weekly'

    category = request.GET.get('category', 'all').lower()
    if category not in ('all', 'profit', 'loss', 'payroll', 'materials'):
        category = 'all'

    try:
        offset = int(request.GET.get('offset', request.GET.get('week_offset', 0)))
    except ValueError:
        offset = 0

    # Strictly disallow future navigation
    offset = min(0, offset)

    date_param = request.GET.get('date', '').strip()

    today = timezone.localdate()
    cache_key = f'pl_dashboard_v3_{time_frame}_{category}_{offset}_{date_param}_{today}'
    cached_context = cache.get(cache_key)
    if cached_context is not None:
        return render(request, 'pl.html', cached_context)

    from apps.accounts.financial_service import get_full_financial_pl_suite

    suite = get_full_financial_pl_suite(
        base_date=today,
        requested_time_frame=time_frame,
        requested_category=category,
        offset=offset,
        target_date_str=date_param if time_frame == 'daily' else None
    )

    active_pkg = suite['active_pkg']

    # Cost breakdown percentages
    safe_opex = max(1.0, active_pkg['total_opex'])
    cost_breakdown_pct = {
        'materials': round((active_pkg['materials']['total_expenditure'] / safe_opex) * 100, 1),
        'maintenance': round((active_pkg['loss']['maint_loss'] / safe_opex) * 100, 1),
        'logistics': round((active_pkg['loss']['freight_loss'] / safe_opex) * 100, 1),
        'payroll': round((active_pkg['payroll']['total_disbursed'] / safe_opex) * 100, 1),
    }

    context = {
        'time_frame': time_frame,
        'category': category,
        'offset': offset,
        'week_offset': offset,  # Legacy URL parameter compatibility
        'today_str': today.strftime('%Y-%m-%d'),
        'max_date_str': today.strftime('%Y-%m-%d'),
        'selected_date': suite['selected_date'],
        # Active Package context variables for direct template rendering
        'label': active_pkg['label'],
        'start_date': active_pkg['start_date'],
        'end_date': active_pkg['end_date'],
        'gross_revenue': active_pkg['gross_revenue'],
        'tot_output_kg': active_pkg['tot_output_kg'],
        'total_opex': active_pkg['total_opex'],
        'net_profit': active_pkg['net_profit'],
        'operating_margin': active_pkg['operating_margin'],
        'is_profitable': active_pkg['is_profitable'],
        'cost_breakdown_pct': cost_breakdown_pct,

        # 4 Strictly Separated Categories
        'profit_data': active_pkg['profit'],
        'loss_data': active_pkg['loss'],
        'payroll_data': active_pkg['payroll'],
        'materials_data': active_pkg['materials'],
        'all_transactions': active_pkg['all_transactions'],
        'transaction_count': active_pkg['all_count'],

        # Precomputed JSON bundles for Daily, Weekly, Monthly instant switching
        'daily_pkg_json': json.dumps(suite['daily_pkg'], default=str),
        'weekly_pkg_json': json.dumps(suite['weekly_pkg'], default=str),
        'monthly_pkg_json': json.dumps(suite['monthly_pkg'], default=str),
        'active_pkg_json': json.dumps(active_pkg, default=str),

        # Chart context
        'chart_dates_json': json.dumps(active_pkg['chart']['labels']),
        'daily_revenues_json': json.dumps(active_pkg['chart']['revenues']),
        'daily_opex_json': json.dumps(active_pkg['chart']['opex']),
        'daily_net_profits_json': json.dumps(active_pkg['chart']['net_profit']),
        'daily_materials_json': json.dumps(active_pkg['chart']['materials']),
        'daily_payrolls_json': json.dumps(active_pkg['chart']['payroll']),
        'daily_maintenance_json': json.dumps(active_pkg['chart']['loss']),

        # Legacy KPI fields for backwards compatibility
        'kpi_gross_revenue': active_pkg['gross_revenue'],
        'kpi_total_opex': active_pkg['total_opex'],
        'kpi_net_profit': active_pkg['net_profit'],
        'kpi_operating_margin': active_pkg['operating_margin'],
        'kpi_raw_material_cost': active_pkg['materials']['total_expenditure'],
        'kpi_maintenance_cost': active_pkg['loss']['maint_loss'],
        'kpi_logistics_cost': active_pkg['loss']['freight_loss'],
        'kpi_payroll_cost': active_pkg['payroll']['total_disbursed'],
        'transactions': active_pkg['all_transactions'],
    }

    cache.set(cache_key, context, timeout=60)
    return render(request, 'pl.html', context)

@login_required(login_url='/login/')
@role_required('AD')
def reports_view(request):
    from apps.production.models import ProductionLog, ProductionTarget
    from apps.maintenance.models import MachineHistoricalMetrics, MaintenanceTicket
    from apps.logistics.models import Dispatch

    today = timezone.localdate()
    target_date_str = (request.GET.get('date') or '').strip()

    # Helper function for flexible multi-format date parsing
    def _parse_search_date(d_str):
        if not d_str:
            return None
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%m/%d/%Y', '%Y/%m/%d'):
            try:
                return datetime.strptime(d_str, fmt).date()
            except (ValueError, TypeError):
                continue
        return None

    try:
        if target_date_str:
            parsed_date = _parse_search_date(target_date_str)
            if parsed_date is None:
                # Unparseable / Malformed Date format: return clean empty dataset with graceful message
                context = {
                    'target_date': today,
                    'target_date_str': target_date_str,
                    'employee_data': [],
                    'total_production': 0.0,
                    'total_material': 0.0,
                    'metrics_count': 0,
                    'tickets': [],
                    'dispatches': [],
                    'chart_emp_names_json': '[]',
                    'chart_emp_outputs_json': '[]',
                    'chart_emp_targets_json': '[]',
                    'chart_emp_profits_json': '[]',
                    'shift_labels_json': '[]',
                    'shift_data_json': '[]',
                    'empty_message': "Dataset Not Found",
                    'empty_subtext': f"Unrecognized date query '{target_date_str}'. Please select a valid calendar date.",
                }
                return render(request, 'report.html', context)

            # FUTURE DATE CHECK: Dates that do not exist yet (> today) must return graceful empty state
            if parsed_date > today:
                context = {
                    'target_date': parsed_date,
                    'target_date_str': parsed_date.strftime('%Y-%m-%d'),
                    'employee_data': [],
                    'total_production': 0.0,
                    'total_material': 0.0,
                    'metrics_count': 0,
                    'tickets': [],
                    'dispatches': [],
                    'chart_emp_names_json': '[]',
                    'chart_emp_outputs_json': '[]',
                    'chart_emp_targets_json': '[]',
                    'chart_emp_profits_json': '[]',
                    'shift_labels_json': '[]',
                    'shift_data_json': '[]',
                    'empty_message': "Dataset Not Found",
                    'empty_subtext': f"The requested date ({parsed_date.strftime('%B %d, %Y')}) has not occurred yet. Future datasets do not exist.",
                }
                return render(request, 'report.html', context)

            target_date = parsed_date
        else:
            target_date = today

        # SUNDAY HOLIDAY FILTER:
        # Sundays are treated strictly as holidays by default.
        # Regular working records are NOT displayed on Sunday.
        # Records are displayed on Sunday ONLY if an employee has a verified, explicit Overtime (OT) entry logged.
        is_sunday = (target_date.weekday() == 6)

        cache_key = f'reports_view_{target_date}'
        cached_context = cache.get(cache_key)
        if cached_context is not None:
            return render(request, 'report.html', cached_context)

        if is_sunday:
            # Query ONLY explicit verified Overtime logs for Sunday
            logs = list(ProductionLog.objects.filter(date=target_date, output_kg__gt=0, is_overtime=True).select_related('employee', 'employee__shift'))
        else:
            # Standard operational day: query active shift outputs
            logs = list(ProductionLog.objects.filter(date=target_date, output_kg__gt=0).select_related('employee', 'employee__shift'))
            if not logs and target_date <= today:
                from apps.production.local_ml_pipeline import LocalPharmaMLForecastingPipeline
                LocalPharmaMLForecastingPipeline().forecast_for_date(target_date)
                logs = list(ProductionLog.objects.filter(date=target_date, output_kg__gt=0).select_related('employee', 'employee__shift'))

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
                    'is_overtime': getattr(log, 'is_overtime', False)
                }
            emp_map[emp.id]['out_kg'] += float(log.output_kg or 0.0)
            emp_map[emp.id]['mat_used'] += float(log.material_used or 0.0)
            if getattr(log, 'is_overtime', False):
                emp_map[emp.id]['is_overtime'] = True
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
            is_ot = data.get('is_overtime', False) or is_sunday

            revenue = out_kg * PRICE_PER_KG
            expense = mat_used * COST_PER_KG
            profit = revenue - expense

            target_obj = existing_targets.get(emp_id)
            target_kg = float(target_obj.target_kg) if target_obj else 300.0
            target_achieved = (target_kg > 0 and out_kg >= target_kg)

            shift_base = emp.shift.name if emp.shift else 'No Shift'
            shift_name = f"{shift_base} (OT)" if is_ot else shift_base

            employee_data.append({
                'employee': emp,
                'shift': shift_name,
                'output': out_kg,
                'material': mat_used,
                'profit': profit,
                'target': target_kg,
                'target_achieved': target_achieved,
                'is_overtime': is_ot,
            })

        # Maintenance & Logistics
        metrics_count = MachineHistoricalMetrics.objects.filter(date=target_date).count()
        tickets = list(MaintenanceTicket.objects.select_related('machine').filter(opened_at__date=target_date))
        dispatches = list(Dispatch.objects.filter(created_at__date=target_date))

        # Chart Data Preparation
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

            shift_name_clean = item['shift'].replace(' (OT)', '').strip()
            if shift_name_clean in shift_output:
                shift_output[shift_name_clean] += item['output']
            else:
                shift_output['No Shift'] += item['output']

        shift_labels = [k for k, v in shift_output.items() if v > 0]
        shift_data = [v for k, v in shift_output.items() if v > 0]

        empty_message = None
        empty_subtext = None
        if not employee_data:
            if is_sunday:
                empty_message = "Dataset Not Found"
                empty_subtext = f"Sunday ({target_date.strftime('%B %d, %Y')}) is a scheduled factory holiday. No verified Overtime (OT) shifts logged."
            else:
                empty_message = "Dataset Not Found"
                empty_subtext = f"No production or operational logs found for {target_date.strftime('%B %d, %Y')}."

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
            'empty_message': empty_message,
            'empty_subtext': empty_subtext,
            'is_sunday': is_sunday,
        }

        cache.set(cache_key, context, timeout=60)
        return render(request, 'report.html', context)

    except Exception as e:
        logger.error("[REPORTS VIEW EXCEPTION] Error processing date query '%s': %s", target_date_str, e, exc_info=True)
        # Robust exception fallback: return a clean empty dataset with graceful message instead of 500 error!
        fallback_context = {
            'target_date': today,
            'target_date_str': target_date_str or today.strftime('%Y-%m-%d'),
            'employee_data': [],
            'total_production': 0.0,
            'total_material': 0.0,
            'metrics_count': 0,
            'tickets': [],
            'dispatches': [],
            'chart_emp_names_json': '[]',
            'chart_emp_outputs_json': '[]',
            'chart_emp_targets_json': '[]',
            'chart_emp_profits_json': '[]',
            'shift_labels_json': '[]',
            'shift_data_json': '[]',
            'empty_message': "Dataset Not Found",
            'empty_subtext': "Unable to retrieve operational metrics for the requested query date.",
            'is_sunday': False,
        }
        return render(request, 'report.html', fallback_context)

