from django.shortcuts import render, redirect
from django.db.models import Sum
from django.contrib.auth.decorators import login_required
from apps.accounts.decorators import role_required
from .models import WarehouseStock, InwardShipment
from apps.logistics.models import Dispatch
from apps.production.models import ProductionLog, Bonus
from django.core.cache import cache
from django.contrib import messages
import logging

logger = logging.getLogger(__name__)

@login_required(login_url='/login/')
@role_required('LO', 'PM', 'AD')
def inventory_dashboard_view(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        
        try:
            # FR-7.1: Inward logistics
            if action == 'inward':
                material_name = (request.POST.get('material') or '').strip()
                qty_raw = (request.POST.get('quantity') or '0').strip()
                cost_raw = (request.POST.get('cost') or '0').strip()
                qty = max(0.0, float(qty_raw or 0))
                cost = max(0.0, float(cost_raw or 0))

                if not material_name:
                    messages.error(request, "Material name is required for inward logistics.")
                elif qty <= 0:
                    messages.error(request, "Inward quantity must be greater than zero.")
                else:
                    stock = WarehouseStock.objects.filter(material=material_name).first()
                    if not stock:
                        stock = WarehouseStock.objects.create(
                            material=material_name,
                            quantity=0,
                            reorder_level=5000,
                            unit='kg'
                        )
                    stock.quantity += qty
                    stock.save()
                    
                    InwardShipment.objects.create(
                        warehouse_stock=stock, supplier="Domestic Supplier", 
                        material=material_name, quantity=qty, cost=cost
                    )
                    messages.success(request, f"Inward shipment of {qty:.1f} kg {material_name} recorded.")
                    
            # FR-7.2: Outward logistics
            elif action == 'outward':
                customer = (request.POST.get('customer') or '').strip()
                qty_raw = (request.POST.get('quantity') or '0').strip()
                transport = (request.POST.get('transport_id') or 'TR-DEFAULT').strip()
                cost_raw = (request.POST.get('cost') or '0').strip()
                qty = max(0.0, float(qty_raw or 0))
                cost = max(0.0, float(cost_raw or 0))

                if not customer:
                    messages.error(request, "Customer / Destination name is required.")
                elif qty <= 0:
                    messages.error(request, "Dispatch quantity must be greater than zero.")
                else:
                    Dispatch.objects.create(
                        customer=customer, quantity=qty, transport_id=transport, 
                        transporter='Logistics Partner', cost=cost
                    )
                    messages.success(request, f"Dispatch of {qty:.1f} units to {customer} recorded.")
        except ValueError as ve:
            logger.warning("Numeric parse error in inventory action: %s", ve)
            messages.error(request, "Invalid numeric input for quantity or cost.")
        except Exception as exc:
            logger.exception("Error processing inventory action: %s", exc)
            messages.error(request, f"Failed to record inventory movement: {exc}")

        cache.delete('inventory_dashboard_stats')
        return redirect('inventory_dashboard')

    cache_key = 'inventory_dashboard_stats'
    cached_context = cache.get(cache_key)
    if cached_context is not None:
        return render(request, 'inventory.html', cached_context)

    # Fetch Data
    stock_items = list(WarehouseStock.objects.all().order_by('material'))
    recent_dispatches = list(Dispatch.objects.all().order_by('-created_at')[:5])
    
    # FR-7.3: P&L Calculation with full null-safety
    total_prod_vol = float(ProductionLog.objects.aggregate(t=Sum('output_kg'))['t'] or 0.0)
    total_material_cost = float(InwardShipment.objects.aggregate(t=Sum('cost'))['t'] or 0.0)
    total_dispatch_cost = float(Dispatch.objects.aggregate(t=Sum('cost'))['t'] or 0.0)
    total_bonuses = float(Bonus.objects.filter(status='P').aggregate(t=Sum('amount'))['t'] or 0.0)
    
    # Base salaries for operational demonstration
    total_salaries = 50000.0 
    
    total_revenue = round(total_prod_vol * 15.5, 2)
    total_expenses = round(total_material_cost + total_dispatch_cost + total_bonuses + total_salaries, 2)
    profit = round(total_revenue - total_expenses, 2)
    
    context = {
        'stock_items': stock_items,
        'recent_dispatches': recent_dispatches,
        'revenue': total_revenue,
        'expenses': total_expenses,
        'profit': profit,
        'profit_margin': round((profit/total_revenue)*100, 1) if total_revenue > 0 else 0.0,
        'costs': {
            'material': total_material_cost,
            'logistics': total_dispatch_cost,
            'payroll': total_salaries + total_bonuses
        }
    }
    
    cache.set(cache_key, context, timeout=60)
    return render(request, 'inventory.html', context)

