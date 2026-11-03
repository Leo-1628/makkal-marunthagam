from django.shortcuts import render, redirect
from django.db.models import Q
from django.contrib import messages
from .models import Medicine
import csv
import io

# ========== BRAND → PMBI SALT MAPPING - MAKKAL MARUNTHAGAM ==========
# When doctor writes Brand, we find PMBI with same salt
BRAND_TO_PMHI = {
    'brilinta': 'ticagrelor',
    'brilinta 90': 'ticagrelor 90',
    'brilinta 90 mg': 'ticagrelor 90',
    'ecosprin': 'aspirin',
    'ecosprin gold': 'atorvastatin aspirin clopidogrel',
    'clopitab': 'clopidogrel',
    'deplatt': 'clopidogrel',
    'plavix': 'clopidogrel',
    'rozavel': 'rosuvastatin',
    'rosevas': 'rosuvastatin',
    'crestor': 'rosuvastatin',
    'rosuvas': 'rosuvastatin',
    'thyronorm': 'thyroxine',
    'thyrox': 'thyroxine',
    'telma': 'telmisartan',
    'telma h': 'telmisartan hydrochlorothiazide',
    'telma am': 'telmisartan amlodipine',
    'amlong': 'amlodipine',
    'amlodac': 'amlodipine',
    'glycomet': 'metformin',
    'glycomet gp': 'glimepiride metformin',
    'janumet': 'sitagliptin metformin',
    'januvia': 'sitagliptin',
    'istamet': 'sitagliptin metformin',
    'montair': 'montelukast levocetirizine',
    'montek': 'montelukast levocetirizine',
    'atorva': 'atorvastatin',
    'lipitor': 'atorvastatin',
    'atorlip': 'atorvastatin',
    'pan 40': 'pantoprazole',
    'pan d': 'pantoprazole domperidone',
    'razo': 'rabeprazole',
    'crocin': 'paracetamol',
    'dolo': 'paracetamol',
    'calpol': 'paracetamol',
    'augmentin': 'amoxycillin clavulanate',
    'clavam': 'amoxycillin clavulanate',
    'azithral': 'azithromycin',
    'azee': 'azithromycin',
    'allegra': 'fexofenadine',
    'cetiriz': 'cetirizine',
    'cetzine': 'cetirizine',
    'ascoril': 'guaifenesin terbutaline bromhexine',
    'benadryl': 'diphenhydramine',
}

def get_pmbi_salt_from_brand(query):
    """Convert brand name to generic salt for PMBI search"""
    q_lower = query.lower().strip()
    # Direct match first
    if q_lower in BRAND_TO_PMHI:
        return BRAND_TO_PMHI[q_lower]
    # Partial match
    for brand, salt in BRAND_TO_PMHI.items():
        if brand in q_lower:
            return salt
    return None

def dashboard(request):
    query = request.GET.get('q', '').strip()
    results = []
    pmbi_suggestion = None
    savings_info = None

    if query:
        # 1. Normal search
        base_query = (
            Q(brand_name__icontains=query) |
            Q(combination__icontains=query) |
            Q(drug_code__icontains=query) |
            Q(manufacturer__icontains=query)
        )
        
        # 2. BRAND → PMBI Logic - If user searches Brilinta, also search Ticagrelor
        salt = get_pmbi_salt_from_brand(query)
        if salt:
            # Add salt search to get PMBI product
            base_query |= Q(combination__icontains=salt) | Q(brand_name__icontains=salt)
            pmbi_suggestion = salt
        
        results = Medicine.objects.filter(base_query).distinct().order_by('brand_name')[:50]
        
        # 3. If results found, calculate savings info for first result
        if results and pmbi_suggestion:
            savings_info = f"Brand '{query}' → PMBI same salt '{pmbi_suggestion.title()}' found!"

    return render(request, 'pharmacy/dashboard.html', {
        'results': results, 
        'query': query,
        'pmbi_suggestion': pmbi_suggestion,
        'savings_info': savings_info,
        'total_count': Medicine.objects.count()
    })

def upload_csv(request):
    if request.method == 'POST':
        csv_file = request.FILES.get('file')
        if not csv_file:
            messages.error(request, "Please select a CSV file")
            return redirect('upload_csv')
        
        if not csv_file.name.endswith('.csv'):
            messages.error(request, "File must be CSV format")
            return redirect('upload_csv')
        
        try:
            data_set = csv_file.read().decode('UTF-8')
            io_string = io.StringIO(data_set)
            reader = csv.DictReader(io_string)
            
            count = 0
            updated = 0
            for row in reader:
                if not row.get('brand_name'):
                    continue
                
                obj, created = Medicine.objects.update_or_create(
                    brand_name=row['brand_name'].strip(),
                    defaults={
                        'combination': row.get('combination', '').strip(),
                        'drug_code': row.get('drug_code', '').strip(),
                        'manufacturer': row.get('manufacturer', '').strip(),
                    }
                )
                if created:
                    count += 1
                else:
                    updated += 1
            
            messages.success(request, f"Uploaded: {count} new, {updated} updated. Total: {Medicine.objects.count()} medicines!")
            return redirect('dashboard')
        
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
            return redirect('upload_csv')

    return render(request, 'pharmacy/upload.html')