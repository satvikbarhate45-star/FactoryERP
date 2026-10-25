from django.shortcuts import render, redirect
from django.db.models import Sum
from django.contrib.auth.decorators import login_required
from apps.accounts.decorators import role_required
from .models import WarehouseStock, InwardShipment
from apps.logistics.models import Dispatch
from apps.production.models import ProductionLog, Bonus
from django.core.cache import cache

@login_required(login_url='/login/')
@role_required('LO', 'PM', 'AD')
def inventory_dashboard_view(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        
        # FR-7.1: Inward logistics
        if action == 'inward':
            material_name = request.POST.get('material')
            qty = float(request.POST.get('quantity', 0))
            cost = float(request.POST.get('cost', 0))
            
            stock, created = WarehouseStock.objects.get_or_create(
                material=material_name,
                defaults={'quantity': 0, 'reorder_level': 5000, 'unit': 'kg'}
            )
            stock.quantity += qty
            stock.save()
            
            InwardShipment.objects.create(
                warehouse_stock=stock, supplier="Domestic Supplier", 
                material=material_name, quantity=qty, cost=cost
            )
            
        # FR-7.2: Outward logistics
        elif action == 'outward':
            customer = request.POST.get('customer')
            qty = float(request.POST.get('quantity', 0))
            transport = request.POST.get('transport_id')
            cost = float(request.POST.get('cost', 0))
            
            Dispatch.objects.create(
                customer=customer, quantity=qty, transport_id=transport, 
                transporter='Logistics Partner', cost=cost
            )
            
        cache.delete('inventory_dashboard_stats')
        return redirect('inventory_dashboard')

    cache_key = 'inventory_dashboard_stats'
    cached_context = cache.get(cache_key)
    if cached_context is not None:
        return render(request, 'inventory.html', cached_context)

    # Fetch Data
    stock_items = list(WarehouseStock.objects.all().order_by('material'))
    recent_dispatches = list(Dispatch.objects.all().order_by('-created_at')[:5])
    
    # FR-7.3: P&L Calculation
    total_prod_vol = ProductionLog.objects.aggregate(t=Sum('output_kg'))['t'] or 0
    total_material_cost = InwardShipment.objects.aggregate(t=Sum('cost'))['t'] or 0
    total_dispatch_cost = Dispatch.objects.aggregate(t=Sum('cost'))['t'] or 0
    total_bonuses = Bonus.objects.filter(status='P').aggregate(t=Sum('amount'))['t'] or 0
    
    # Mock base salaries for demonstration
    total_salaries = 50000 
    
    total_revenue = float(total_prod_vol) * 15.5 # Mock sale price per kg
    total_expenses = float(total_material_cost) + float(total_dispatch_cost) + float(total_bonuses) + total_salaries
    profit = total_revenue - total_expenses
    
    context = {
        'stock_items': stock_items,
        'recent_dispatches': recent_dispatches,
        'revenue': total_revenue,
        'expenses': total_expenses,
        'profit': profit,
        'profit_margin': round((profit/total_revenue)*100, 1) if total_revenue > 0 else 0,
        'costs': {
            'material': float(total_material_cost),
            'logistics': float(total_dispatch_cost),
            'payroll': total_salaries + float(total_bonuses)
        }
    }
    
    cache.set(cache_key, context, timeout=60)
    return render(request, 'inventory.html', context)

