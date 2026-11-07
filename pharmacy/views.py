from django.shortcuts import render, redirect
from django.db.models import Q
from django.contrib import messages
from .models import Medicine
import csv
import io
import re

# ========== BRAND → PMBI SALT MAPPING - MAKKAL MARUNTHAGAM ==========
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
    'crocin 650': 'paracetamol 650',
    'dolo': 'paracetamol',
    'dolo 650': 'paracetamol 650',
    'dolo 500': 'paracetamol 500',
    'dolo 650 mg': 'paracetamol 650',
    'calpol': 'paracetamol',
    'calpol 650': 'paracetamol 650',
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
    q_lower = query.lower().strip()
    for brand in sorted(BRAND_TO_PMHI.keys(), key=len, reverse=True):
        if brand in q_lower:
            return BRAND_TO_PMHI[brand]
    return None

def extract_strength(query):
    m = re.search(r'(\d+)', query)
    return m.group(1) if m else None

def extract_mrp(text):
    if not text:
        return None
    m = re.search(r'MRP\s*Rs\.?\s*([\d,]+\.?\d*)', text, re.IGNORECASE)
    if m:
        try: return float(m.group(1).replace(',', ''))
        except: return None
    m = re.search(r'Rs\.?\s*([\d,]+\.?\d*)', text)
    if m:
        try: return float(m.group(1).replace(',', ''))
        except: return None
    return None

def is_pmbi_row(m):
    code = (m.drug_code or '').lower()
    manu = (m.manufacturer or '').lower()
    combo = (m.combination or '').lower()
    if 'pmbi' in code:
        return True
    if 'pmbi' in manu or 'pmbi' in combo:
        return True
    return False

# ===== Extra salt iruka? Dolo 650-ku Caffeine koodadhu! =====
EXTRA_WORDS = ['caffeine', 'chlorpheniramine', 'phenylephrine', 'dextromethorphan', 'codeine', 'tramadol', 'ibuprofen', 'diclofenac', 'aceclofenac']

def is_exact_single_salt(m, salt, strength):
    """Dolo 650 -> Paracetamol 650 ONLY. 'and Caffeine' irundha reject."""
    name = (m.brand_name or '').lower()
    combo = (m.combination or '').lower()
    text = name + ' ' + combo
    salt_word = salt.split()[0]  # paracetamol
    if salt_word not in text:
        return False
    if strength and strength not in text:
        return False
    # Single salt request-na 'and' irukura combo-va reject pannu
    if len(salt.strip().split()) <= 2:
        if ' and ' in name or ' and ' in combo:
            return False
        for extra in EXTRA_WORDS:
            if extra in text and extra not in salt.lower():
                return False
    return True

def home(request):
    return render(request, 'pharmacy/home.html', {'total_count': Medicine.objects.count()})

def dashboard(request):
    query = request.GET.get('q', '').strip()
    results = []
    best_match = None
    brand_match = None
    alternatives = []
    pmbi_suggestion = None
    savings_info = None
    brand_mrp = None
    pmbi_mrp = None
    savings_amount = None
    savings_percent = None

    if query:
        salt = get_pmbi_salt_from_brand(query)
        pmbi_suggestion = salt if salt else query
        strength = extract_strength(query)

        brand_word = re.sub(r'\d+', '', query).strip()
        brand_candidates = list(Medicine.objects.filter(Q(brand_name__icontains=brand_word)).exclude(drug_code__icontains='PMBI').distinct()[:20])
        if brand_candidates and strength:
            exact_brand = [m for m in brand_candidates if strength in (m.combination or '') or strength in (m.brand_name or '')]
            if exact_brand:
                brand_candidates = exact_brand
        if brand_candidates:
            brand_match = brand_candidates[0]
            brand_mrp = extract_mrp(brand_match.combination)

        # ===== FIX 1: Token-wise search - phrase-a thedaathe =====
        # "paracetamol 650" -> ["paracetamol", "650"] rendu thaniya thedu
        # Appadi-na "Paracetamol Tablets IP 650 mg" um kedaikum
        tokens = [t for t in re.split(r'[^a-z0-9]+', pmbi_suggestion.lower()) if t]
        token_q = Q()
        for tok in tokens:
            token_q &= (Q(brand_name__icontains=tok) | Q(combination__icontains=tok))

        all_results = list(Medicine.objects.filter(token_q | Q(drug_code__icontains=query)).distinct()[:200])

        pmbi_only = [m for m in all_results if is_pmbi_row(m)]
        search_pool = pmbi_only if pmbi_only else all_results

        if strength:
            exact = [m for m in search_pool if strength in (m.combination or '')]
            if exact:
                search_pool = exact

        # ===== FIX 2: Exact Single Salt First - Caffeine-a thallu =====
        # Dolo 650 -> Paracetamol 650 ONLY
        exact_pool = [m for m in search_pool if is_exact_single_salt(m, pmbi_suggestion, strength)]
        if exact_pool:
            search_pool = exact_pool

        def sort_key(m):
            combo = (m.combination or '').lower()
            name = (m.brand_name or '').lower()
            text = combo + ' ' + name
            has_and = 1 if ' and ' in text else 0
            has_caffeine = 1 if 'caffeine' in text else 0
            has_plus = 1 if '+' in text else 0
            return (has_and, has_caffeine, has_plus, len(m.combination or ''), len(m.brand_name or ''))

        search_pool.sort(key=sort_key)

        if search_pool:
            best_match = search_pool[0]
            alternatives = search_pool[1:4]
            results = search_pool
            pmbi_mrp = extract_mrp(best_match.combination)
            savings_info = f"Brand '{query}' -> PMBI same salt '{pmbi_suggestion.title()}' found!"
            if brand_mrp and pmbi_mrp and brand_mrp > pmbi_mrp:
                savings_amount = round(brand_mrp - pmbi_mrp, 2)
                savings_percent = round((savings_amount / brand_mrp) * 100)

    return render(request, 'pharmacy/search.html', {
        'results': results,
        'best_match': best_match,
        'brand_match': brand_match,
        'alternatives': alternatives,
        'query': query,
        'pmbi_suggestion': pmbi_suggestion,
        'savings_info': savings_info,
        'brand_mrp': brand_mrp,
        'pmbi_mrp': pmbi_mrp,
        'savings_amount': savings_amount,
        'savings_percent': savings_percent,
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
                if created: count += 1
                else: updated += 1
            messages.success(request, f"Uploaded: {count} new, {updated} updated. Total: {Medicine.objects.count()} medicines!")
            return redirect('dashboard')
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
            return redirect('upload_csv')
    return render(request, 'pharmacy/upload.html')