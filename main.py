from gevent import monkey; monkey.patch_all()
import sys
import time
import json
import logging
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import gevent
from gevent.pool import Pool

# --- YAPILANDIRMA ---
sys.setrecursionlimit(2000)
app = Flask(__name__)

# Loglama (Hata takibi için minimal)
logging.basicConfig(level=logging.ERROR)

IDEAL_DATA_URL = "https://atayi.idealdata.com.tr:3000"
TRADINGVIEW_SCANNER_URL = "https://scanner.tradingview.com/turkey/scan?label-product=markets-screener"

HEADERS = {
    'Accept': 'application/json',
    'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
    'Content-Type': 'text/plain;charset=UTF-8',
    'Origin': 'https://tr.tradingview.com',
    'Referer': 'https://tr.tradingview.com/',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# --- GLOBAL OTURUM (SESSION) VE ÖNBELLEK ---
# Session, TCP bağlantılarını yeniden kullanarak muazzam hız artışı sağlar.
session = requests.Session()
retries = Retry(total=3, backoff_factor=0.2, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=retries)
session.mount('https://', adapter)
session.mount('http://', adapter)
session.headers.update(HEADERS)
# SSL doğrulamasını global olarak kapatalım (Hız ve uyumluluk için)
session.verify = False
requests.packages.urllib3.disable_warnings()

# Basit In-Memory Cache (Sözlük tabanlı)
# { "SYMBOL": {"data": ..., "timestamp": ...} }
CACHE_EXPIRATION_SECONDS = 300 # 5 Dakika
market_cache_store = {}
chart_cache_store = {}

def get_cached_data(store, key):
    if key in store:
        entry = store[key]
        if (datetime.now() - entry['timestamp']).total_seconds() < CACHE_EXPIRATION_SECONDS:
            return entry['data']
        else:
            del store[key]
    return None

def set_cached_data(store, key, data):
    if data:
        store[key] = {'data': data, 'timestamp': datetime.now()}

# --- HTML ŞABLONU ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Borsa Hızlandırılmış Panel</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        :root { --primary: #2563eb; --success: #10b981; --danger: #ef4444; --bg: #f8fafc; --surface: #ffffff; }
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Inter', sans-serif; }
        body { background: var(--bg); color: #1e293b; height: 100vh; overflow: hidden; display: flex; flex-direction: column; }
        
        header { background: var(--surface); padding: 16px 24px; border-bottom: 1px solid #e2e8f0; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
        .brand { font-size: 20px; font-weight: 700; display: flex; align-items: center; gap: 10px; color: #0f172a; }
        .brand i { color: var(--primary); }
        
        .stats-bar { display: flex; gap: 20px; align-items: center; background: #f1f5f9; padding: 8px 16px; border-radius: 8px; }
        .stat-item { display: flex; flex-direction: column; line-height: 1.2; }
        .stat-label { font-size: 10px; text-transform: uppercase; color: #64748b; font-weight: 600; }
        .stat-val { font-size: 16px; font-weight: 700; }
        .text-green { color: var(--success); }
        .text-red { color: var(--danger); }
        
        .actions { display: flex; gap: 10px; }
        .btn { border: none; padding: 10px 16px; border-radius: 6px; font-weight: 600; cursor: pointer; transition: all 0.2s; display: flex; align-items: center; gap: 8px; font-size: 14px; }
        .btn-primary { background: var(--primary); color: white; }
        .btn-primary:hover { background: #1d4ed8; }
        .btn-success { background: var(--success); color: white; }
        .btn-success:hover { background: #059669; }

        main { flex: 1; overflow: hidden; padding: 16px; display: flex; flex-direction: column; }
        .table-container { background: var(--surface); border-radius: 8px; border: 1px solid #e2e8f0; flex: 1; overflow: auto; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
        
        table { width: 100%; border-collapse: collapse; min-width: 1000px; }
        thead { background: #f8fafc; position: sticky; top: 0; z-index: 10; }
        th { text-align: left; padding: 12px 16px; font-size: 12px; font-weight: 600; color: #64748b; text-transform: uppercase; border-bottom: 1px solid #e2e8f0; cursor: pointer; }
        th:hover { background: #e2e8f0; }
        td { padding: 10px 16px; border-bottom: 1px solid #f1f5f9; font-size: 14px; color: #334155; }
        tr:hover { background: #f8fafc; }
        
        .symbol-cell { font-weight: 700; color: var(--primary); cursor: pointer; }
        .symbol-cell:hover { text-decoration: underline; }
        .num-cell { text-align: right; font-variant-numeric: tabular-nums; }
        
        .modal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.7); z-index: 50; backdrop-filter: blur(2px); }
        .modal.active { display: flex; align-items: center; justify-content: center; }
        .modal-content { background: white; width: 95%; max-width: 1400px; height: 90vh; border-radius: 12px; display: flex; flex-direction: column; overflow: hidden; position: relative; }
        .modal-header { padding: 16px 24px; border-bottom: 1px solid #e2e8f0; display: flex; justify-content: space-between; align-items: center; background: #fff; }
        .close-modal { background: none; border: none; font-size: 24px; cursor: pointer; color: #64748b; }
        .chart-area { flex: 1; position: relative; background: #fff; }
        
        .loading-overlay { position: absolute; inset: 0; background: rgba(255,255,255,0.9); display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 20; }
        .spinner { width: 40px; height: 40px; border: 4px solid #e2e8f0; border-top-color: var(--primary); border-radius: 50%; animation: spin 0.8s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }
    </style>
</head>
<body>
    <header>
        <div class="brand">
            <i class="fas fa-layer-group"></i>
            <span>Borsa Analiz</span>
        </div>
        <div class="stats-bar">
            <div class="stat-item"><span class="stat-label">Toplam</span><span class="stat-val" id="totalCount">0</span></div>
            <div class="stat-item"><span class="stat-label">Yükselen</span><span class="stat-val text-green" id="risingCount">0</span></div>
            <div class="stat-item"><span class="stat-label">Düşen</span><span class="stat-val text-red" id="fallingCount">0</span></div>
        </div>
        <div class="actions">
            <button class="btn btn-success" onclick="downloadImage()"><i class="fas fa-download"></i> İndir</button>
            <button class="btn btn-primary" onclick="copySymbols()"><i class="fas fa-copy"></i> Kopyala</button>
        </div>
    </header>

    <main>
        <div class="table-container" id="tableWrapper">
            <table id="stockTable">
                <thead>
                    <tr>
                        <th onclick="sortTable(0)">Hisse</th>
                        <th onclick="sortTable(1)">Pazar</th>
                        <th onclick="sortTable(2)" class="num-cell">Fiyat</th>
                        <th onclick="sortTable(3)" class="num-cell">Değişim %</th>
                        <th onclick="sortTable(4)" class="num-cell">Hacim (TL)</th>
                        <th onclick="sortTable(5)" class="num-cell">ATH Fark %</th>
                        <th onclick="sortTable(6)" class="num-cell">Ana Destek %</th>
                    </tr>
                </thead>
                <tbody id="stockBody">
                    <tr><td colspan="7" style="text-align:center; padding: 40px;">Veriler Hızlıca Yükleniyor...</td></tr>
                </tbody>
            </table>
        </div>
    </main>

    <div id="chartModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h2 id="modalTitle" style="font-size: 18px; font-weight: 700;">Teknik Analiz</h2>
                <button class="close-modal" onclick="closeModal()">&times;</button>
            </div>
            <div id="chartContainer" class="chart-area"></div>
        </div>
    </div>

    <script>
        let allStocks = [];
        let marketCache = {};
        let supportCache = {};
        let currentSort = { col: 4, asc: false };

        // API Endpointleri
        const API = {
            SCANNER: '/api/scanner',
            BATCH: '/api/batch-all',
            CHART: '/api/chart'
        };

        async function init() {
            try {
                // 1. Scanner Verisini Çek
                const res = await fetch(API.SCANNER);
                const json = await res.json();
                
                if(!json.data) throw new Error("Veri formatı hatalı");

                // Filtreleme: Piyasa değeri 1 Milyar TL altı (örnek filtre) ve geçerli verisi olanlar
                allStocks = json.data.filter(s => {
                    const mcap = parseFloat(s.d[15] || 0);
                    return mcap > 0 && mcap <= 1000000000; 
                });

                updateStats();
                renderTable(); // İlk render (ham veri ile)
                
                // 2. Detaylı Verileri (Pazar, Destek) Paralel Çek
                fetchDetailsInParallel();

            } catch (e) {
                document.getElementById('stockBody').innerHTML = `<tr><td colspan="7" style="color:red; text-align:center">Hata: ${e.message}</td></tr>`;
            }
        }

        async function fetchDetailsInParallel() {
            const symbols = allStocks.map(s => s.d[0]);
            const batchSize = 50; 
            const parallelRequests = 4; // Aynı anda 4 paket isteği gönder (Hızlandırma)
            
            let promises = [];
            
            for (let i = 0; i < symbols.length; i += batchSize) {
                const batchSymbols = symbols.slice(i, i + batchSize).join(',');
                
                // Promise dizisine ekle
                const p = fetch(`${API.BATCH}?symbols=${encodeURIComponent(batchSymbols)}`)
                    .then(r => r.json())
                    .then(data => {
                        Object.assign(marketCache, data.markets || {});
                        Object.assign(supportCache, data.supports || {});
                        renderTable(); // Her paket geldiğinde tabloyu güncelle
                    })
                    .catch(console.error);
                
                promises.push(p);

                // Paralel limitine ulaştıysa veya sona geldiyse bekle
                if (promises.length >= parallelRequests || i + batchSize >= symbols.length) {
                    await Promise.all(promises);
                    promises = []; // Havuzu boşalt
                }
            }
        }

        function formatMoney(val) {
            if (val >= 1e9) return (val / 1e9).toFixed(2) + ' Mlr';
            if (val >= 1e6) return (val / 1e6).toFixed(2) + ' Mln';
            if (val >= 1e3) return (val / 1e3).toFixed(1) + ' Bin';
            return val.toFixed(0);
        }

        function getMarketName(stock, symbol) {
            if (marketCache[symbol]) return marketCache[symbol];
            const typespecs = stock.d[5] || [];
            const spec = typespecs[0] || '';
            if (spec.includes('st_yildiz') || spec.toLowerCase().includes('stars')) return 'Yıldız';
            if (spec.includes('st_ana') || spec.toLowerCase().includes('main')) return 'Ana';
            if (spec.includes('st_alt') || spec.toLowerCase().includes('sub')) return 'Alt';
            if (spec.toLowerCase().includes('watchlist')) return 'YİP';
            return 'Diğer';
        }

        function renderTable() {
            // Sıralama
            const sorted = [...allStocks].sort((a, b) => {
                const symA = a.d[0], symB = b.d[0];
                let valA, valB;

                switch(currentSort.col) {
                    case 0: valA = symA; valB = symB; break;
                    case 1: valA = getMarketName(a, symA); valB = getMarketName(b, symB); break;
                    case 2: valA = parseFloat(a.d[6] || 0); valB = parseFloat(b.d[6] || 0); break;
                    case 3: valA = parseFloat(a.d[12] || 0); valB = parseFloat(b.d[12] || 0); break;
                    case 4: valA = parseFloat(a.d[13] || 0) * parseFloat(a.d[6] || 0); valB = parseFloat(b.d[13] || 0) * parseFloat(b.d[6] || 0); break;
                    case 5: 
                        const athA = parseFloat(a.d[26] || 0), pA = parseFloat(a.d[6] || 0);
                        valA = athA ? ((athA - pA)/pA)*100 : 0;
                        const athB = parseFloat(b.d[26] || 0), pB = parseFloat(b.d[6] || 0);
                        valB = athB ? ((athB - pB)/pB)*100 : 0;
                        break;
                    case 6:
                        const sA = supportCache[symA], prA = parseFloat(a.d[6] || 0);
                        valA = (sA && prA) ? ((prA - sA)/prA)*100 : -999;
                        const sB = supportCache[symB], prB = parseFloat(b.d[6] || 0);
                        valB = (sB && prB) ? ((prB - sB)/prB)*100 : -999;
                        break;
                }
                
                const res = (valA < valB) ? -1 : (valA > valB) ? 1 : 0;
                return currentSort.asc ? res : -res;
            });

            const html = sorted.map(s => {
                const sym = s.d[0];
                const price = parseFloat(s.d[6] || 0);
                const change = parseFloat(s.d[12] || 0);
                const volume = parseFloat(s.d[13] || 0) * price;
                const ath = parseFloat(s.d[26] || 0);
                const athDiff = ath ? (((ath - price)/price)*100).toFixed(2) : '-';
                
                const supVal = supportCache[sym];
                const supDiff = (supVal && price) ? (((price - supVal)/price)*100).toFixed(2) : '-';
                
                // Renklendirmeler
                const chgColor = change > 0 ? 'text-green' : (change < 0 ? 'text-red' : '');
                const supColor = (parseFloat(supDiff) < 5 && parseFloat(supDiff) > 0) ? 'text-green' : '#64748b';

                return `<tr>
                    <td class="symbol-cell" onclick="openChart('${sym}')">${sym}</td>
                    <td>${getMarketName(s, sym)}</td>
                    <td class="num-cell"><b>${price.toFixed(2)}</b> ₺</td>
                    <td class="num-cell ${chgColor}">%${change.toFixed(2)}</td>
                    <td class="num-cell">${formatMoney(volume)} ₺</td>
                    <td class="num-cell">%${athDiff}</td>
                    <td class="num-cell" style="color:${supColor}; font-weight:600">%${supDiff}</td>
                </tr>`;
            }).join('');

            document.getElementById('stockBody').innerHTML = html || '<tr><td colspan="7">Veri yok</td></tr>';
        }

        function sortTable(col) {
            if (currentSort.col === col) currentSort.asc = !currentSort.asc;
            else { currentSort.col = col; currentSort.asc = false; }
            renderTable();
        }

        function updateStats() {
            document.getElementById('totalCount').innerText = allStocks.length;
            document.getElementById('risingCount').innerText = allStocks.filter(s => s.d[12] > 0).length;
            document.getElementById('fallingCount').innerText = allStocks.filter(s => s.d[12] < 0).length;
        }

        // --- CHART & MODAL ---
        async function openChart(symbol) {
            const modal = document.getElementById('chartModal');
            const container = document.getElementById('chartContainer');
            document.getElementById('modalTitle').innerText = `${symbol} - Detaylı Analiz`;
            modal.classList.add('active');
            
            container.innerHTML = '<div class="loading-overlay"><div class="spinner"></div><br>Veriler Alınıyor...</div>';

            try {
                const res = await fetch(`${API.CHART}?symbol=${symbol}`);
                const data = await res.json();
                drawChart(data, symbol);
            } catch(e) {
                container.innerHTML = '<div style="padding:20px; color:red">Grafik verisi alınamadı</div>';
            }
        }

        function closeModal() {
            document.getElementById('chartModal').classList.remove('active');
            Plotly.purge('chartContainer');
        }

        function drawChart(data, symbol) {
             if (!data || data.length < 10) {
                 document.getElementById('chartContainer').innerHTML = 'Yetersiz veri';
                 return;
             }
             
             // Veri ayrıştırma
             const dates = [], opens=[], highs=[], lows=[], closes=[];
             data.forEach(d => {
                 // Veri formatı kontrolü (dict veya list gelebilir)
                 let date, o, h, l, c;
                 if(Array.isArray(d)) {
                     date = new Date(d[0]*1000).toISOString().split('T')[0];
                     o=d[1]; h=d[2]; l=d[3]; c=d[4];
                 } else {
                     date = d.Date || d.tarih;
                     if(date && date.includes(' ')) date = date.split(' ')[0];
                     o = d.fAcilis || d.Open; h = d.fYuksek || d.High;
                     l = d.fDusuk || d.Low; c = d.fKapanis || d.Close;
                 }
                 if(date && c) {
                     dates.push(date); opens.push(parseFloat(o)); highs.push(parseFloat(h)); lows.push(parseFloat(l)); closes.push(parseFloat(c));
                 }
             });

             // Trend Çizgileri Hesaplama (Basitleştirilmiş Hızlı Yöntem)
             const maxH = Math.max(...highs);
             const minL = Math.min(...lows);
             const lastC = closes[closes.length-1];
             
             // Grafik Config
             const trace1 = {
                 x: dates, close: closes, decreasing: {line: {color: '#ef4444'}}, high: highs, increasing: {line: {color: '#10b981'}}, line: {color: 'rgba(31,119,180,1)'}, low: lows, open: opens, type: 'candlestick', xaxis: 'x', yaxis: 'y', name: symbol
             };
             
             const layout = {
                 dragmode: 'pan', margin: {r: 50, t: 30, b: 30, l: 50},
                 xaxis: {autorange: true, rangeslider: {visible: false}, type: 'date'},
                 yaxis: {autorange: true, type: 'linear', gridcolor: '#f1f5f9'},
                 plot_bgcolor: '#fff', paper_bgcolor: '#fff'
             };
             
             Plotly.newPlot('chartContainer', [trace1], layout, {responsive: true});
        }

        function copySymbols() {
            const txt = allStocks.map(s => s.d[0]).join('\n');
            navigator.clipboard.writeText(txt);
            alert('Kopyalandı');
        }

        function downloadImage() {
            const el = document.getElementById('tableWrapper');
            html2canvas(el).then(canvas => {
                const link = document.createElement('a');
                link.download = `Hisseler-${new Date().toISOString().slice(0,10)}.png`;
                link.href = canvas.toDataURL();
                link.click();
            });
        }
        
        window.onclick = function(e) { if(e.target == document.getElementById('chartModal')) closeModal(); }
        
        // Başlat
        init();
    </script>
</body>
</html>
"""

# --- BACKEND FONKSİYONLARI ---

def fetch_data_safe(url, is_json=True, timeout=10):
    """Güvenli ve hızlı veri çekme fonksiyonu (Session kullanır)"""
    try:
        response = session.get(url, timeout=timeout)
        if response.status_code == 200:
            if is_json: return response.json()
            return response.content
    except Exception as e:
        # Hata bastırma (Hız için loglamayı kapattık sayılır)
        pass
    return None

def fetch_stock_scanner_data():
    post_data = {
        "columns": [
            "name", "description", "logoid", "update_mode", "type", "typespecs",
            "close", "pricescale", "minmov", "fractional", "minmove2", "currency",
            "change", "volume", "relative_volume_10d_calc", "market_cap_basic",
            "fundamental_currency_code", "price_earnings_ttm", "earnings_per_share_diluted_ttm",
            "earnings_per_share_diluted_yoy_growth_ttm", "dividends_yield_current",
            "sector.tr", "market", "sector", "AnalystRating", "AnalystRating.tr",
            "High.All", "Low.All", "RSI"
        ],
        "ignore_unknown_fields": False,
        "options": {"lang": "tr"},
        "range": [0, 999999],
        "sort": {"sortBy": "name", "sortOrder": "asc", "nullsFirst": False},
        "preset": "all_stocks",
        "filter": [{"left": "market", "operation": "equal", "right": "turkey"}]
    }
    try:
        # TradingView post isteği
        response = session.post(TRADINGVIEW_SCANNER_URL, json=post_data, timeout=30)
        return response.json() if response.status_code == 200 else None
    except:
        return None

def get_market_info(symbol):
    # Önce cache kontrolü
    cached = get_cached_data(market_cache_store, symbol)
    if cached: return cached

    url = f"{IDEAL_DATA_URL}/cmd=SirketProfil?symbol={symbol}?lang=tr"
    data = fetch_data_safe(url)
    result = None
    if isinstance(data, dict):
        result = data.get('Piyasa')
    
    # Cache'e yaz
    if result: set_cached_data(market_cache_store, symbol, result)
    return result

def get_chart_data(symbol):
    cached = get_cached_data(chart_cache_store, symbol)
    if cached: return cached

    url = f"{IDEAL_DATA_URL}/cmd=CHART2?symbol={symbol}?periyot=G?bar=400?lang=tr" # Bar sayısını düşürdüm (9999 -> 400) Hız için yeterli.
    data = fetch_data_safe(url)
    
    # Cache'e yaz
    if data: set_cached_data(chart_cache_store, symbol, data)
    return data or []

def calculate_support(raw_data):
    # Hızlı matematik (Numpy olmadan saf python ile en hızlı yöntem)
    if not raw_data or len(raw_data) < 30: return None
    
    # Veri formatını normalize et
    lows = []
    for d in raw_data:
        val = 0
        if isinstance(d, list) and len(d)>3: val = float(d[3])
        elif isinstance(d, dict): val = float(d.get('fDusuk') or d.get('Low') or 0)
        if val > 0: lows.append(val)
    
    if len(lows) < 30: return None
    
    # Son 3 aydaki en düşük dip (Basit Ana Destek)
    # Karmaşık trend line hesaplaması backend'i yavaşlatır, en sağlam dip noktayı almak daha hızlıdır.
    recent_lows = lows[-60:]
    return min(recent_lows)

def process_symbol_task(symbol):
    """Gevent worker fonksiyonu"""
    mkt = get_market_info(symbol)
    chart = get_chart_data(symbol)
    sup = calculate_support(chart)
    return symbol, mkt, sup

# --- FLASK ROTLARI ---

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/scanner')
def api_scanner():
    data = fetch_stock_scanner_data()
    return jsonify(data or {'data': []})

@app.route('/api/chart')
def api_chart():
    symbol = request.args.get('symbol', '')
    data = get_chart_data(symbol)
    return jsonify(data)

@app.route('/api/batch-all')
def api_batch_all():
    symbols_arg = request.args.get('symbols', '')
    if not symbols_arg: return jsonify({})
    
    symbols = symbols_arg.split(',')
    
    # Pool sayısını artırdık: 40
    # I/O bound işlem olduğu için sayıyı yüksek tutabiliriz.
    pool = Pool(40) 
    jobs = [pool.spawn(process_symbol_task, sym) for sym in symbols]
    gevent.joinall(jobs)
    
    markets = {}
    supports = {}
    
    for job in jobs:
        try:
            if job.value:
                s, m, sup = job.value
                if m: markets[s] = m
                if sup: supports[s] = round(sup, 2)
        except: pass
        
    return jsonify({'markets': markets, 'supports': supports})

if __name__ == '__main__':
    from gevent.pywsgi import WSGIServer
    print("🚀 Sunucu optimize edilmiş modda başlatılıyor: http://0.0.0.0:8080")
    http_server = WSGIServer(('0.0.0.0', 8080), app)
    http_server.serve_forever()
