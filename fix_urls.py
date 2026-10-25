data = open('apps/production/views.py', encoding='utf-8').read()
data = data.replace("return redirect('production_dashboard')", "return redirect('production_manager_dashboard')")
open('apps/production/views.py', 'w', encoding='utf-8').write(data)
