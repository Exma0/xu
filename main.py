from gevent import monkey; monkey.patch_all()
import sys
# Rekürsiyon limitini artırıyoruz
sys.setrecursionlimit(2000)

from flask import Flask, request, jsonify, render_template_string
import requests
import json
import gevent
from gevent.pool import Pool
import math
import statistics

app = Flask(__name__)

# --- AYARLAR VE SABİTLER ---
IDEAL_DATA_URL = "https://atayi.idealdata.com.tr:3000"
TRADINGVIEW_SCANNER_URL = "https://scanner.tradingview.com/turkey/scan?label-product=markets-screener"

HEADERS = {
    'Accept': 'application/json',
    'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
    'Content-Type': 'text/plain;charset=UTF-8',
    'Origin': 'https://tr.tradingview.com',
    'Referer': 'https://tr.tradingview.com/',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
}

# --- FRONTEND (HTML/CSS/JS) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BIST Pro Trend Analizi</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        html, body { height: 100%; background: #f1f3f5; font-family: 'Inter', sans-serif; color: #343a40; font-size: 12px; }
        .container { max-width: 98%; margin: 0 auto; height: 100%; display: flex; flex-direction: column; }
        
        /* Header */
        header { background: white; padding: 12px 0; border-bottom: 1px solid #dee2e6; }
        .header-content { padding: 0 15px; display: flex; justify-content: space-between; align-items: center; }
        .header-title { display: flex; align-items: center; gap: 8px; font-size: 18px; font-weight: 700; color: #212529; }
        .header-title i { color: #228be6; }
        
        .stats { display: flex; gap: 15px; margin-left: 20px; }
        .stat-item { background: #f8f9fa; padding: 4px 10px; border-radius: 4px; border: 1px solid #e9ecef; }
        .stat-label { font-size: 10px; color: #868e96; font-weight: 700; text-transform: uppercase; }
        .stat-val { font-size: 14px; font-weight: 700; }
        .stat-val.pos { color: #12b886; }
        .stat-val.neg { color: #fa5252; }

        .btn-group { display: flex; gap: 8px; }
        .btn { padding: 6px 12px; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; color: white; display: flex; align-items: center; gap: 5px; font-size: 11px; transition: 0.2s; }
        .btn-green { background: #12b886; } .btn-green:hover { background: #0ca678; }
        .btn-blue { background: #228be6; } .btn-blue:hover { background: #1c7ed6; }

        /* Main Content */
        main { flex: 1; padding: 10px; overflow: hidden; display: flex; flex-direction: column; }
        .table-container { background: white; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); flex: 1; overflow: auto; position: relative; }
        
        table { width: 100%; border-collapse: collapse; table-layout: fixed; }
        thead { position: sticky; top: 0; z-index: 10; background: #f8f9fa; box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
        
        th { padding: 10px 8px; text-align: right; font-size: 10px; font-weight: 700; color: #495057; text-transform: uppercase; border-bottom: 2px solid #dee2e6; cursor: pointer; user-select: none; }
        th:first-child, th:nth-child(2) { text-align: left; }
        th:hover { background: #e9ecef; color: #000; }
        
        td { padding: 6px 8px; border-bottom: 1px solid #f1f3f5; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        tr:hover { background: #f8f9fa; }
        
        .col-symbol { font-weight: 700; color: #228be6; cursor: pointer; }
        .col-symbol:hover { text-decoration: underline; }
        .col-pazar { color: #868e96; font-size: 10px; }
        
        /* Renkli Bloklar */
        .bg-sup { background-color: rgba(18, 184, 134, 0.04); }
        .bg-res { background-color: rgba(250, 82, 82, 0.04); }
        .border-l { border-left: 2px solid #dee2e6; }
        
        .val-up { color: #12b886; font-weight: 600; }
        .val-down { color: #fa5252; font-weight: 600; }
        .val-neu { color: #adb5bd; }

        .loading-overlay { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: #868e96; }
        
        /* Modal */
        .modal { display: none; position: fixed; z-index: 2000; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); backdrop-filter: blur(2px); }
        .modal.show { display: flex; }
        .modal-box { background: white; margin: auto; padding: 15px; border-radius: 8px; width: 95%; max-width: 1400px; max-height: 95vh; display: flex; flex-direction: column; }
        .modal-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid #dee2e6; }
        .chart-area { flex: 1; min-height: 600px; position: relative; }
        #chartCanvas { width: 100%; height: 100%; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="header-content">
                <div class="header-title">
                    <i class="fas fa-chart-area"></i> BIST Pro Analiz
                </div>
                <div class="stats">
                    <div class="stat-item"><span class="stat-label">HİSSE:</span> <span class="stat-val" id="countTotal">0</span></div>
                    <div class="stat-item"><span class="stat-label">POZİTİF:</span> <span class="stat-val pos" id="countUp">0</span></div>
                    <div class="stat-item"><span class="stat-label">NEGATİF:</span> <span class="stat-val neg" id="countDown">0</span></div>
                </div>
                <div class="btn-group">
                    <button class="btn btn-green" onclick="downloadTable()"><i class="fas fa-camera"></i> Tabloyu İndir</button>
                    <button class="btn btn-blue" onclick="copyTable()"><i class="fas fa-copy"></i> Sembolleri Kopyala</button>
                </div>
            </div>
        </header>

        <main>
            <div id="errorBox" style="background:#ffc9c9; color:#c92a2a; padding:10px; border-radius:4px; margin-bottom:10px; display:none;"></div>
            <div class="table-container">
                <table id="mainTable">
                    <thead>
                        <tr>
                            <th style="width: 80px;" onclick="sort(0)">HİSSE</th>
                            <th style="width: 100px;" onclick="sort(1)">PAZAR</th>
                            <th style="width: 80px;" onclick="sort(2)">FİYAT</th>
                            <th style="width: 70px;" onclick="sort(3)">DEĞ %</th>
                            
                            <th style="width: 90px;" class="bg-sup border-l" onclick="sort(4)">DESTEK UZAKLIK</th>
                            <th style="width: 90px;" class="bg-sup" onclick="sort(5)">MAX SARKMA</th>
                            
                            <th style="width: 90px;" class="bg-res border-l" onclick="sort(6)">DİRENÇ UZAKLIK</th>
                            <th style="width: 90px;" class="bg-res" onclick="sort(7)">MAX AŞIM</th>
                            
                            <th style="width: 80px;" class="border-l" onclick="sort(8)">ZİRVE %</th>
                            <th style="width: 100px;" onclick="sort(9)">HACİM</th>
                            <th style="width: 90px;" onclick="sort(10)">PD</th>
                        </tr>
                    </thead>
                    <tbody id="tableBody">
                        <tr><td colspan="11"><div class="loading-overlay"><i class="fas fa-spinner fa-spin fa-2x"></i><br>Veriler Analiz Ediliyor...</div></td></tr>
                    </tbody>
                </table>
            </div>
        </main>
    </div>

    <div id="chartModal" class="modal">
        <div class="modal-box">
            <div class="modal-head">
                <h3 id="modalTitle" style="margin:0;">Teknik Grafik</h3>
                <div>
                    <button class="btn btn-blue" onclick="downloadChart()" style="display:inline-flex;">HD İndir</button>
                    <button style="background:none; border:none; font-size:20px; cursor:pointer; margin-left:10px;" onclick="closeModal()">&times;</button>
                </div>
            </div>
            <div class="chart-area">
                <div id="chartCanvas"></div>
            </div>
        </div>
    </div>

    <script>
        // Global State
        let stocksData = [];
        let caches = { market: {}, sup: {}, dip: {}, res: {}, brk: {} };
        let sortCol = 9; // Hacim default
        let sortAsc = false;

        // API Endpoints
        const API = { SCAN: '/api/scanner', BATCH: '/api/batch', CHART: '/api/chart' };

        // Helpers
        const fmtNum = n => {
            if(n>=1e9) return (n/1e9).toFixed(1)+' Mr';
            if(n>=1e6) return (n/1e6).toFixed(1)+' Mn';
            if(n>=1e3) return (n/1e3).toFixed(0)+' B';
            return n.toFixed(0);
        };
        
        const getPazar = (specs) => {
            if(!specs || !specs.length) return '-';
            let s = specs[0].toLowerCase();
            if(s.includes('yildiz') || s.includes('stars')) return 'YILDIZ';
            if(s.includes('ana') || s.includes('main')) return 'ANA';
            if(s.includes('alt') || s.includes('sub')) return 'ALT';
            if(s.includes('watchlist')) return 'YAKIN İZLEME';
            return 'DİĞER';
        };

        // Core Logic
        async function init() {
            try {
                let res = await fetch(API.SCAN);
                let json = await res.json();
                if(!json.data) throw new Error("Veri yok");
                
                // Filtreleme: PD < 100 Milyar ve PD > 0
                stocksData = json.data.filter(x => {
                   let pd = parseFloat(x.d[15]||0);
                   return pd > 0; // Tüm hisseleri getir
                });

                renderTable();
                updateStats();

                // Batch Loading
                let symbols = stocksData.map(x => x.d[0]);
                for(let i=0; i<symbols.length; i+=40) {
                    let chunk = symbols.slice(i, i+40).join(',');
                    loadBatch(chunk);
                    await new Promise(r => setTimeout(r, 50)); // Rate limit koruması
                }
            } catch(e) {
                document.getElementById('errorBox').style.display='block';
                document.getElementById('errorBox').innerText = e.message;
            }
        }

        async function loadBatch(syms) {
            try {
                let res = await fetch(API.BATCH + '?symbols=' + encodeURIComponent(syms));
                let data = await res.json();
                Object.assign(caches.market, data.market);
                Object.assign(caches.sup, data.sup);
                Object.assign(caches.dip, data.dip);
                Object.assign(caches.res, data.res);
                Object.assign(caches.brk, data.brk);
                renderTable(); // Her partide tabloyu güncelle
            } catch(e) { console.error(e); }
        }

        function sort(col) {
            if(sortCol === col) sortAsc = !sortAsc;
            else { sortCol = col; sortAsc = (col < 2); } // İsim/Pazar harici default azalan
            renderTable();
        }

        function renderTable() {
            let sorted = [...stocksData].sort((a,b) => {
                let vA, vB;
                let symA = a.d[0], symB = b.d[0];
                
                switch(sortCol) {
                    case 0: vA=symA; vB=symB; break;
                    case 1: vA=caches.market[symA]||getPazar(a.d[5]); vB=caches.market[symB]||getPazar(b.d[5]); break;
                    case 2: vA=parseFloat(a.d[6]||0); vB=parseFloat(b.d[6]||0); break;
                    case 3: vA=parseFloat(a.d[12]||0); vB=parseFloat(b.d[12]||0); break;
                    case 4: // Destek Uzaklık
                         let sA = caches.sup[symA], pA = parseFloat(a.d[6]);
                         vA = (sA && pA) ? ((pA-sA)/pA)*100 : -999;
                         let sB = caches.sup[symB], pB = parseFloat(b.d[6]);
                         vB = (sB && pB) ? ((pB-sB)/pB)*100 : -999;
                         break;
                    case 5: vA=caches.dip[symA]||0; vB=caches.dip[symB]||0; break;
                    case 6: // Direnç Uzaklık
                         let rA = caches.res[symA], prA = parseFloat(a.d[6]);
                         vA = (rA && prA) ? ((rA-prA)/prA)*100 : 999;
                         let rB = caches.res[symB], prB = parseFloat(b.d[6]);
                         vB = (rB && prB) ? ((rB-prB)/prB)*100 : 999;
                         break;
                    case 7: vA=caches.brk[symA]||0; vB=caches.brk[symB]||0; break;
                    case 8: // ATH
                         let athA = parseFloat(a.d[26]||0), curA = parseFloat(a.d[6]);
                         vA = athA ? ((athA-curA)/curA)*100 : 0;
                         let athB = parseFloat(b.d[26]||0), curB = parseFloat(b.d[6]);
                         vB = athB ? ((athB-curB)/curB)*100 : 0;
                         break;
                    case 9: // Hacim
                         vA = parseFloat(a.d[13]||0)*parseFloat(a.d[6]||0);
                         vB = parseFloat(b.d[13]||0)*parseFloat(b.d[6]||0);
                         break;
                    case 10: vA=parseFloat(a.d[15]||0); vB=parseFloat(b.d[15]||0); break;
                }
                
                if(typeof vA === 'string') return sortAsc ? vA.localeCompare(vB) : vB.localeCompare(vA);
                return sortAsc ? vA - vB : vB - vA;
            });

            let html = sorted.map(s => {
                let sym = s.d[0];
                let price = parseFloat(s.d[6]||0);
                let chg = parseFloat(s.d[12]||0);
                let vol = parseFloat(s.d[13]||0) * price;
                let pd = parseFloat(s.d[15]||0);
                let ath = parseFloat(s.d[26]||0);
                let athDiff = ath ? (((ath-price)/price)*100).toFixed(0) : '-';
                let pazar = caches.market[sym] || getPazar(s.d[5]);

                // Trend Verileri
                let supVal = caches.sup[sym], dipVal = caches.dip[sym];
                let supDist = (supVal && price) ? (((price-supVal)/price)*100).toFixed(1) : '-';
                let dipTxt = dipVal !== undefined ? dipVal.toFixed(1) : '-';
                
                let resVal = caches.res[sym], brkVal = caches.brk[sym];
                let resDist = (resVal && price) ? (((resVal-price)/price)*100).toFixed(1) : '-';
                let brkTxt = brkVal !== undefined ? brkVal.toFixed(1) : '-';

                // Renkler
                let cChg = chg>0?'val-up':(chg<0?'val-down':'val-neu');
                let cSup = (supDist !== '-' && parseFloat(supDist) < 2) ? 'val-down' : 'val-up'; // Desteğe %2 yaklaştıysa kırmızı
                let cRes = (resDist !== '-' && parseFloat(resDist) < 2) ? 'val-up' : 'val-down'; // Dirence %2 yaklaştıysa yeşil

                return `<tr>
                    <td class="col-symbol" onclick="openChart('${sym}')">${sym}</td>
                    <td class="col-pazar">${pazar}</td>
                    <td style="text-align:right; font-weight:600;">${price.toFixed(2)}</td>
                    <td style="text-align:right;" class="${cChg}">${chg}%</td>
                    
                    <td style="text-align:right;" class="bg-sup border-l"><span class="${cSup}">${supDist}%</span></td>
                    <td style="text-align:right;" class="bg-sup">${dipTxt}%</td>
                    
                    <td style="text-align:right;" class="bg-res border-l"><span class="${cRes}">${resDist}%</span></td>
                    <td style="text-align:right;" class="bg-res">${brkTxt}%</td>
                    
                    <td style="text-align:right;" class="border-l val-neu">${athDiff}%</td>
                    <td style="text-align:right;">${fmtNum(vol)}</td>
                    <td style="text-align:right; color:#868e96;">${fmtNum(pd)}</td>
                </tr>`;
            }).join('');
            
            document.getElementById('tableBody').innerHTML = html;
        }

        function updateStats() {
            document.getElementById('countTotal').innerText = stocksData.length;
            document.getElementById('countUp').innerText = stocksData.filter(x=>x.d[12]>0).length;
            document.getElementById('countDown').innerText = stocksData.filter(x=>x.d[12]<0).length;
        }

        // --- Chart & Modal ---
        async function openChart(sym) {
            document.getElementById('chartModal').classList.add('show');
            document.getElementById('modalTitle').innerText = sym + ' Teknik Analiz';
            document.getElementById('chartCanvas').innerHTML = '<div class="loading-overlay"><i class="fas fa-circle-notch fa-spin fa-3x"></i></div>';
            
            try {
                let res = await fetch(API.CHART + '?s=' + sym);
                let data = await res.json();
                drawChart(sym, data);
            } catch(e) {
                document.getElementById('chartCanvas').innerHTML = '<div class="loading-overlay">Grafik yüklenemedi</div>';
            }
        }

        function drawChart(sym, raw) {
            if(!raw || raw.length < 50) return;
            
            let dates = raw.map(x => new Date(x.t*1000).toISOString().split('T')[0]);
            let o = raw.map(x=>x.o), h = raw.map(x=>x.h), l = raw.map(x=>x.l), c = raw.map(x=>x.c);

            // Lines (Backend'den hesaplanan verileri görselleştirmek için tekrar JS'de basit çizim)
            // Not: Gerçek linear regression çizgisini backend'den array olarak da isteyebiliriz ama
            // basitlik adına burada sadece mumları ve varsa backend hesap değerlerini çizdireceğiz.
            
            let trace = {
                x: dates, open: o, high: h, low: l, close: c,
                type: 'candlestick', name: sym,
                increasing: {line: {color: '#12b886'}}, decreasing: {line: {color: '#fa5252'}}
            };
            
            let layout = {
                dragmode: 'zoom', showlegend: false,
                xaxis: {rangeslider: {visible: false}},
                yaxis: {autorange: true},
                margin: {t:20,b:40,l:40,r:40},
                height: 600
            };
            
            Plotly.newPlot('chartCanvas', [trace], layout);
        }

        function closeModal() { document.getElementById('chartModal').classList.remove('show'); }
        function downloadTable() { 
            html2canvas(document.querySelector('.table-container')).then(c => {
                let a = document.createElement('a'); a.download='analiz.png'; a.href=c.toDataURL(); a.click();
            }); 
        }
        function copyTable() {
            navigator.clipboard.writeText(stocksData.map(x=>x.d[0]).join(','));
        }
        function downloadChart() {
             Plotly.downloadImage('chartCanvas', {format:'png', width:1920, height:1080, filename:'grafik'});
        }

        init();
    </script>
</body>
</html>
"""

# --- BACKEND LOGIC (Python) ---

def get_data_from_ideal(url):
    try:
        r = requests.get(url, verify=False, timeout=8)
        if r.status_code == 200:
            # iDeal data genellikle iso-8859-9 (Turkish) gelir
            return json.loads(r.content.decode('iso-8859-9'))
    except: return None

# --- GELİŞMİŞ TREND ALGORİTMASI (Linear Regression & Pivots) ---
def calc_trend_advanced(candles):
    # candles format: [{'o':..., 'h':..., 'l':..., 'c':...}, ...] or list of lists
    # Veriyi normalize et
    highs = []
    lows = []
    closes = []
    
    # Veri formatını güvenli hale getir
    if not candles: return None
    
    for c in candles:
        if isinstance(c, dict):
            highs.append(float(c.get('fYuksek', c.get('h', 0))))
            lows.append(float(c.get('fDusuk', c.get('l', 0))))
            closes.append(float(c.get('fKapanis', c.get('c', 0))))
        elif isinstance(c, list) and len(c) >= 5: # [date, o, h, l, c]
            highs.append(float(c[2]))
            lows.append(float(c[3]))
            closes.append(float(c[4]))
            
    n = len(closes)
    if n < 60: return None # Yetersiz veri

    # 1. DESTEK ANALİZİ (Linear Regression on Local Minima)
    # Yerel dipleri bul (Window = 5)
    local_min_indices = []
    for i in range(2, n-2):
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            local_min_indices.append(i)
    
    # Eğer yeterince dip yoksa en düşüğü al
    if len(local_min_indices) < 2:
        support_val = min(lows)
        support_slope = 0
    else:
        # Basit Lineer Regresyon: y = mx + c
        # X: indices, Y: prices
        sum_x = sum(local_min_indices)
        sum_y = sum([lows[i] for i in local_min_indices])
        sum_xy = sum([i * lows[i] for i in local_min_indices])
        sum_xx = sum([i*i for i in local_min_indices])
        count = len(local_min_indices)
        
        try:
            slope = (count * sum_xy - sum_x * sum_y) / (count * sum_xx - sum_x * sum_x)
        except: slope = 0 # Sıfıra bölme hatası olursa
        
        # Intercept (c) hesapla: Ortalama çizgiyi verir.
        # Ancak DESTEK çizgisi en alttan geçmeli.
        # Bu yüzden tüm dipler için (y - mx) hesaplayıp EN KÜÇÜĞÜNÜ (min_c) alıyoruz.
        min_intercept = float('inf')
        for i in range(n):
            # Sadece dipleri değil, tüm düşükleri kontrol et ki fiyat çizginin altına inmesin
            # Performans için sadece yerel dipleri kontrol edelim
            val = lows[i] - slope * i
            if val < min_intercept:
                min_intercept = val
        
        support_slope = slope
        current_support = support_slope * (n-1) + min_intercept

    # Destek Analizi: Max Sarkma
    max_dip = 0.0
    for i in range(n):
        line_val = support_slope * i + (current_support - support_slope*(n-1)) # Denklemi geri kur
        if line_val > 0:
            diff = lows[i] - line_val
            if diff < 0: # Çizginin altında
                pct = (diff / line_val) * 100
                if pct < max_dip: max_dip = pct

    # 2. DİRENÇ ANALİZİ (Linear Regression on Local Maxima)
    local_max_indices = []
    for i in range(2, n-2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            local_max_indices.append(i)
            
    if len(local_max_indices) < 2:
        res_val = max(highs)
        res_slope = 0
    else:
        sum_x = sum(local_max_indices)
        sum_y = sum([highs[i] for i in local_max_indices])
        sum_xy = sum([i * highs[i] for i in local_max_indices])
        sum_xx = sum([i*i for i in local_max_indices])
        count = len(local_max_indices)
        
        try:
            slope = (count * sum_xy - sum_x * sum_y) / (count * sum_xx - sum_x * sum_x)
        except: slope = 0
        
        # Intercept: Direnç çizgisi en üstten geçmeli -> Max Intercept
        max_intercept = float('-inf')
        for i in range(n):
            val = highs[i] - slope * i
            if val > max_intercept:
                max_intercept = val
                
        res_slope = slope
        current_resistance = res_slope * (n-1) + max_intercept

    # Direnç Analizi: Max Aşım (Breakout)
    max_breakout = 0.0
    for i in range(n):
        line_val = res_slope * i + (current_resistance - res_slope*(n-1))
        if line_val > 0:
            diff = highs[i] - line_val
            if diff > 0:
                pct = (diff / line_val) * 100
                if pct > max_breakout: max_breakout = pct

    return {
        'sup': current_support, 'dip': max_dip,
        'res': current_resistance, 'brk': max_breakout
    }

def process_symbol(sym):
    # Market Bilgisi
    mkt = None
    try:
        r = requests.get(f"{IDEAL_DATA_URL}/cmd=SirketProfil?symbol={sym}?lang=tr", verify=False, timeout=5)
        if r.status_code==200: mkt = json.loads(r.content.decode('iso-8859-9')).get('Piyasa')
    except: pass

    # Grafik Verisi
    chart = []
    try:
        r = requests.get(f"{IDEAL_DATA_URL}/cmd=CHART2?symbol={sym}?periyot=G?bar=400?lang=tr", verify=False, timeout=8) # Son 400 bar yeterli
        if r.status_code==200: chart = json.loads(r.content.decode('iso-8859-9'))
    except: pass

    trend = calc_trend_advanced(chart)
    
    return sym, mkt, trend

# --- ROUTES ---
@app.route('/')
def home(): return render_template_string(HTML_TEMPLATE)

@app.route('/api/scanner', methods=['GET', 'POST'])
def scanner():
    # TradingView Scanner Payload
    payload = {
        "columns": ["name","description","logoid","update_mode","type","typespecs","close","pricescale","minmov","fractional","minmove2","currency","change","volume","relative_volume_10d_calc","market_cap_basic","fundamental_currency_code","price_earnings_ttm","earnings_per_share_diluted_ttm","earnings_per_share_diluted_yoy_growth_ttm","dividends_yield_current","sector.tr","market","sector","AnalystRating","AnalystRating.tr","High.All","Low.All","RSI"],
        "ignore_unknown_fields": False, "options": {"lang": "tr"}, "range": [0, 9999], 
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"}, 
        "preset": "all_stocks", "filter": [{"left": "market", "operation": "equal", "right": "turkey"}]
    }
    try:
        r = requests.post(TRADINGVIEW_SCANNER_URL, headers=HEADERS, json=payload, timeout=30)
        return jsonify(r.json())
    except Exception as e: return jsonify({'error': str(e)})

@app.route('/api/chart')
def chart():
    s = request.args.get('s')
    # Grafik için temiz format döndür
    try:
        r = requests.get(f"{IDEAL_DATA_URL}/cmd=CHART2?symbol={s}?periyot=G?bar=500?lang=tr", verify=False, timeout=10)
        raw = json.loads(r.content.decode('iso-8859-9'))
        # Frontend için minimize et: [time, open, high, low, close]
        clean = []
        if isinstance(raw, list):
            for x in raw:
                # ideal data formatı bazen değişebilir, kontrol et
                # Genelde: {'Date':..., 'fAcilis':...} veya list
                if isinstance(x, dict):
                    # Tarih parse (YYYY-MM-DD HH:MM:SS) -> timestamp
                    # Basitlik için sadece kapanışları alıyoruz gibi görünüyor ama mum grafiği için OHLC lazım
                    clean.append({
                        't': int(time.mktime(time.strptime(x['Date'].split('.')[0], "%Y-%m-%d %H:%M:%S"))), 
                        'o': x['fAcilis'], 'h': x['fYuksek'], 'l': x['fDusuk'], 'c': x['fKapanis']
                    })
        return jsonify(clean)
    except: return jsonify([])

@app.route('/api/batch')
def batch():
    syms = request.args.get('symbols', '').split(',')
    syms = [s for s in syms if s]
    
    out = {'market':{}, 'sup':{}, 'dip':{}, 'res':{}, 'brk':{}}
    
    pool = Pool(15) # Concurrent workers
    jobs = [pool.spawn(process_symbol, s) for s in syms]
    gevent.joinall(jobs)
    
    for j in jobs:
        try:
            if j.value:
                s, m, t = j.value
                if m: out['market'][s] = m
                if t:
                    out['sup'][s] = t['sup']
                    out['dip'][s] = t['dip']
                    out['res'][s] = t['res']
                    out['brk'][s] = t['brk']
        except: pass
        
    return jsonify(out)

if __name__ == '__main__':
    requests.packages.urllib3.disable_warnings()
    from gevent.pywsgi import WSGIServer
    print("Sunucu 8080 portunda başlatılıyor...")
    http_server = WSGIServer(('0.0.0.0', 8080), app)
    http_server.serve_forever()
