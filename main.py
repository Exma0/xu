from gevent import monkey; monkey.patch_all()
import sys
# Rekürsiyon limitini artırıyoruz
sys.setrecursionlimit(2000)

from flask import Flask, request, jsonify, render_template_string
import requests
import json
import gevent
from gevent.pool import Pool
import urllib3
import time
from datetime import datetime

# --- SSL UYARILARINI KAPATMA ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# --- AYARLAR VE SABİTLER ---
# IdealData yerine Yahoo Finance kullanacağız (Daha stabil)
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{}.IS?range=1y&interval=1d"
TRADINGVIEW_SCANNER_URL = "https://scanner.tradingview.com/turkey/scan?label-product=markets-screener"

# Yahoo Finance headers (User-Agent önemli)
HEADERS_YAHOO = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

HEADERS_TV = {
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
    <title>Borsa İstanbul Analiz Paneli (Yahoo API)</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        html, body { height: 100%; background: #f8f9fa; font-family: 'Inter', sans-serif; color: #333; }
        .container { max-width: 1400px; margin: 0 auto; height: 100%; display: flex; flex-direction: column; }
        header { background: white; padding: 24px 0; border-bottom: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
        .header-content { padding: 0 24px; display: flex; justify-content: space-between; align-items: center; }
        .header-title { display: flex; align-items: center; gap: 12px; font-size: 24px; font-weight: 700; }
        .header-title i { color: #0066cc; }
        .stats { display: flex; gap: 24px; flex: 1; margin-left: 40px; }
        .stat { display: flex; flex-direction: column; }
        .stat-label { font-size: 12px; color: #666; text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px; }
        .stat-value { font-size: 20px; font-weight: 700; margin-top: 4px; }
        .stat-value.positive { color: #10b981; }
        .stat-value.negative { color: #ef4444; }
        main { flex: 1; padding: 24px; overflow: auto; }
        .table-wrapper { background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); overflow: hidden; }
        table { width: 100%; border-collapse: collapse; }
        thead { background: #f3f4f6; }
        th { padding: 16px; text-align: left; font-size: 13px; font-weight: 600; color: #666; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid #e5e7eb; cursor: pointer; user-select: none; }
        th:hover { background: #e5e7eb; }
        td { padding: 14px 16px; border-bottom: 1px solid #f0f0f0; font-size: 14px; }
        tr:hover { background: #f9fafb; }
        .symbol { font-weight: 600; color: #0066cc; cursor: pointer; }
        .symbol:hover { text-decoration: underline; }
        .pazar { color: #555; font-size: 13px; font-weight: 500; }
        .change { font-weight: 600; text-align: right; }
        .change.up { color: #10b981; }
        .change.down { color: #ef4444; }
        .no-data { text-align: center; padding: 60px 20px; color: #999; }
        .error-message { background: #fef2f2; color: #991b1b; padding: 12px 16px; border-radius: 6px; margin-bottom: 16px; display: none; }
        .error-message.show { display: block; }
        .download-btn { background: #10b981; color: white; border: none; padding: 10px 16px; border-radius: 6px; cursor: pointer; font-weight: 600; display: flex; align-items: center; gap: 8px; margin-left: 8px; }
        .download-btn:hover { background: #059669; }
        .download-btn:disabled { background: #ccc; cursor: not-allowed; }
        .download-btn:nth-child(2) { background: #3b82f6; }
        .download-btn:nth-child(2):hover { background: #2563eb; }
        .modal { display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; background-color: rgba(0,0,0,0.6); }
        .modal.show { display: flex; }
        .modal-content { background-color: white; margin: auto; padding: 20px; border-radius: 8px; width: 95%; max-width: 1200px; max-height: 90vh; overflow-y: auto; position: relative; }
        .modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; border-bottom: 1px solid #e5e7eb; padding-bottom: 15px; }
        .modal-title { font-size: 20px; font-weight: 700; color: #333; }
        .close-btn { background: none; border: none; font-size: 28px; cursor: pointer; color: #999; }
        .close-btn:hover { color: #333; }
        .chart-container { position: relative; height: 1440px; margin-top: 20px; }
        #chartCanvas { height: 100%; width: 100%; }
        .loading { text-align: center; padding: 50px; color: #666; }
        .loading i { font-size: 48px; margin-bottom: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="header-content">
                <div class="header-title">
                    <i class="fas fa-chart-line"></i>
                    <span>Borsa Analiz</span>
                </div>
                <div class="stats">
                    <div class="stat">
                        <div class="stat-label">Toplam</div>
                        <div class="stat-value" id="totalCount">0</div>
                    </div>
                    <div class="stat">
                        <div class="stat-label">Yükselen</div>
                        <div class="stat-value positive" id="risingCount">0</div>
                    </div>
                    <div class="stat">
                        <div class="stat-label">Düşen</div>
                        <div class="stat-value negative" id="fallingCount">0</div>
                    </div>
                </div>
                <button class="download-btn" onclick="downloadTableAsImage()">
                    <i class="fas fa-download"></i> İndir
                </button>
                <button class="download-btn" onclick="copyStocksToClipboard()">
                    <i class="fas fa-copy"></i> Kopyala
                </button>
            </div>
        </header>

        <main>
            <div class="error-message" id="errorMessage"></div>
            <div class="table-wrapper">
                <table id="stockTable">
                    <thead>
                        <tr>
                            <th onclick="sortStocks(0)">Hisse Adı</th>
                            <th>Pazar</th>
                            <th style="text-align: right;" onclick="sortStocks(1)">Fiyat (₺)</th>
                            <th style="text-align: right;" onclick="sortStocks(2)">Değişim %</th>
                            <th style="text-align: right;" onclick="sortStocks(3)">ATH Farkı (%)</th>
                            <th style="text-align: right;" onclick="sortStocks(6)">Destek Uzaklık (%)</th>
                            <th style="text-align: right;" onclick="sortStocks(4)">Hacim (₺)</th>
                            <th style="text-align: right;" onclick="sortStocks(5)">Piyasa Değeri</th>
                        </tr>
                    </thead>
                    <tbody id="stockBody">
                        <tr>
                            <td colspan="8" class="no-data">
                                <i class="fas fa-spinner fa-spin" style="font-size: 24px;"></i><br><br>
                                Veriler yükleniyor...
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </main>
    </div>

    <div id="chartModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <div class="modal-title" id="chartTitle">Hisse Detayı</div>
                <div style="display: flex; gap: 8px;">
                    <button class="download-btn" style="background: #3b82f6; margin-left: 0;" onclick="download2KChart()">
                        <i class="fas fa-download"></i> 2K İndir
                    </button>
                    <button class="close-btn" onclick="closeChartModal()">&times;</button>
                </div>
            </div>
            <div class="chart-container">
                <div id="chartCanvas">
                    <div class="loading">
                        <i class="fas fa-spinner fa-spin"></i>
                        <h3>Grafik yükleniyor...</h3>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let allStocks = [];
        let supportCache = {};
        let currentSortColumn = 5;
        let sortAscending = true;

        const API = {
            SCANNER: '/api/scanner',
            BATCH: '/api/batch-all',
            CHART: '/api/chart'
        };

        function getPazarFromTypespecs(typespecs) {
            if (!typespecs || !Array.isArray(typespecs) || typespecs.length === 0) return 'Bilinmiyor';
            // Typespecs dizisindeki verileri kontrol et
            const joined = typespecs.join(' ').toLowerCase();
            
            if (joined.includes('st_yildiz') || joined.includes('stars')) return 'Yıldız Pazar';
            if (joined.includes('st_ana') || joined.includes('main')) return 'Ana Pazar';
            if (joined.includes('st_alt') || joined.includes('sub')) return 'Alt Pazar';
            if (joined.includes('watchlist')) return 'Yakın İzleme';
            
            return 'Diğer';
        }

        function formatLargeNumber(num) {
            if (num >= 1000000000) return (num / 1000000000).toFixed(2) + ' Mlr';
            if (num >= 1000000) return (num / 1000000).toFixed(2) + ' Mly';
            if (num >= 1000) return (num / 1000).toFixed(1) + ' Bin';
            return num.toFixed(0);
        }

        function sortStocks(columnIndex) {
            if (currentSortColumn === columnIndex) {
                sortAscending = !sortAscending;
            } else {
                currentSortColumn = columnIndex;
                sortAscending = (columnIndex === 0);
            }

            const sorted = [...allStocks].sort((a, b) => {
                let valueA, valueB;
                switch(columnIndex) {
                    case 0: valueA = (a.d[0] || '').toLowerCase(); valueB = (b.d[0] || '').toLowerCase(); return sortAscending ? valueA.localeCompare(valueB) : valueB.localeCompare(valueA);
                    case 1: valueA = parseFloat(a.d[6] || 0); valueB = parseFloat(b.d[6] || 0); break;
                    case 2: valueA = parseFloat(a.d[12] || 0); valueB = parseFloat(b.d[12] || 0); break;
                    case 3:
                        const priceA = parseFloat(a.d[6] || 0); const athA = parseFloat(a.d[26] || 0);
                        valueA = athA > 0 ? (((athA - priceA) / priceA) * 100) : 0;
                        const priceB = parseFloat(b.d[6] || 0); const athB = parseFloat(b.d[26] || 0);
                        valueB = athB > 0 ? (((athB - priceB) / priceB) * 100) : 0;
                        break;
                    case 4: 
                        valueA = parseFloat(a.d[13] || 0) * parseFloat(a.d[6] || 0); 
                        valueB = parseFloat(b.d[13] || 0) * parseFloat(b.d[6] || 0); 
                        break;
                    case 5: valueA = parseFloat(a.d[15] || 0); valueB = parseFloat(b.d[15] || 0); break;
                    case 6: 
                        const supA = supportCache[a.d[0]];
                        const pA = parseFloat(a.d[6] || 0);
                        valueA = supA !== undefined ? ((pA - supA) / pA) * 100 : -999;
                        const supB = supportCache[b.d[0]];
                        const pB = parseFloat(b.d[6] || 0);
                        valueB = supB !== undefined ? ((pB - supB) / pB) * 100 : -999;
                        break;
                }
                if (columnIndex !== 0) return sortAscending ? valueA - valueB : valueB - valueA;
                return 0;
            });

            allStocks = sorted;
            displayStocks(sorted);
        }

        async function loadStocks(retryCount = 3) {
            try {
                const response = await fetch(API.SCANNER);
                const data = await response.json();

                if (data.data && Array.isArray(data.data)) {
                    allStocks = data.data.filter(stock => {
                        const marketCap = parseFloat(stock.d[15] || 0);
                        return marketCap > 0;
                    }).sort((a, b) => parseFloat(a.d[15] || 0) - parseFloat(b.d[15] || 0));

                    displayStocks(allStocks);
                    updateStats();

                    const symbols = allStocks.map(s => s.d[0]);
                    const batchSize = 25; // Yahoo'ya çok yüklenmemek için batch boyutunu düşürdük

                    for (let i = 0; i < symbols.length; i += batchSize) {
                        const batch = symbols.slice(i, i + batchSize);
                        fetchBatchWithRetry(batch.join(','));
                        await new Promise(resolve => setTimeout(resolve, 500)); 
                    }
                } else if (retryCount > 0) {
                    setTimeout(() => loadStocks(retryCount - 1), 2000);
                } else {
                    showError('Veri yüklenemedi');
                }
            } catch (error) {
                if (retryCount > 0) {
                    setTimeout(() => loadStocks(retryCount - 1), 2000);
                } else {
                    showError('Bağlantı hatası: ' + error.message);
                }
            }
        }

        async function fetchBatchWithRetry(batchString, retryCount = 2) {
            try {
                const resp = await fetch(API.BATCH + '?symbols=' + encodeURIComponent(batchString));
                const result = await resp.json();
                if (result.supports) Object.assign(supportCache, result.supports);
                sortStocks(currentSortColumn);
            } catch (err) {
                if (retryCount > 0) {
                    setTimeout(() => fetchBatchWithRetry(batchString, retryCount - 1), 1000);
                }
            }
        }

        function displayStocks(stocks) {
            const tbody = document.getElementById('stockBody');
            if (!stocks || stocks.length === 0) {
                tbody.innerHTML = '<tr><td colspan="8" class="no-data">Veri bulunamadı</td></tr>';
                return;
            }
            tbody.innerHTML = stocks.map(stock => {
                const symbol = stock.d[0] || '';
                const typespecs = stock.d[5] || [];
                const pazar = getPazarFromTypespecs(typespecs);
                const price = parseFloat(stock.d[6] || 0);
                const change = parseFloat(stock.d[12] || 0).toFixed(2);

                const volume = parseFloat(stock.d[13] || 0);
                const volumeTL = volume * price;

                const marketCap = parseFloat(stock.d[15] || 0);
                const ath = parseFloat(stock.d[26] || 0);
                const athDiffPercent = ath > 0 ? (((ath - price) / price) * 100).toFixed(2) : '0.00';
                const marketCapText = formatLargeNumber(marketCap);
                const changeClass = change > 0 ? 'up' : change < 0 ? 'down' : '';
                const changeSign = change > 0 ? '+' : '';

                const supportLevel = supportCache[symbol];
                let supportDistStr = '-';
                let supportColor = '#666';

                if (supportLevel !== undefined && price > 0) {
                    const supportDist = ((price - supportLevel) / price) * 100;
                    supportDistStr = supportDist.toFixed(2) + '%';
                    supportColor = supportDist > 0 && supportDist < 5 ? '#eab308' : (supportDist > 0 ? '#10b981' : '#ef4444');
                }

                return `<tr>
                    <td class="symbol" onclick="showChartModal('${symbol}')">${symbol}</td>
                    <td class="pazar">${pazar}</td>
                    <td style="text-align: right; font-weight: 600;">${price.toFixed(2)}₺</td>
                    <td style="text-align: right;" class="change ${changeClass}">${changeSign}${change}%</td>
                    <td style="text-align: right; color: #666;">${athDiffPercent}%</td>
                    <td style="text-align: right; color: ${supportColor}; font-weight: 600;">${supportDistStr}</td>
                    <td style="text-align: right;">${formatLargeNumber(volumeTL)} ₺</td>
                    <td style="text-align: right; color: #666;">${marketCapText}</td>
                </tr>`;
            }).join('');
        }

        function updateStats() {
            document.getElementById('totalCount').textContent = allStocks.length;
            const rising = allStocks.filter(s => parseFloat(s.d[12] || 0) > 0).length;
            const falling = allStocks.filter(s => parseFloat(s.d[12] || 0) < 0).length;
            document.getElementById('risingCount').textContent = rising;
            document.getElementById('fallingCount').textContent = falling;
        }

        function showError(message) {
            const errorEl = document.getElementById('errorMessage');
            errorEl.textContent = message;
            errorEl.classList.add('show');
        }

        function downloadTableAsImage() {
            const btn = event.target.closest('button');
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> İndiriliyor...';
            html2canvas(document.querySelector('.table-wrapper')).then(canvas => {
                const link = document.createElement('a');
                link.download = 'hisse-senetleri-' + new Date().toISOString().slice(0,10) + '.png';
                link.href = canvas.toDataURL();
                link.click();
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-download"></i> İndir';
            });
        }

        function copyStocksToClipboard() {
            const text = allStocks.map(s => s.d[0]).join('\\n');
            navigator.clipboard.writeText(text).then(() => {
                const btn = event.target.closest('button');
                const originalHTML = btn.innerHTML;
                btn.innerHTML = '<i class="fas fa-check"></i> Kopyalandı!';
                setTimeout(() => btn.innerHTML = originalHTML, 2000);
            });
        }

        async function showChartModal(symbol) {
            const modal = document.getElementById('chartModal');
            const title = document.getElementById('chartTitle');
            title.textContent = symbol + ' - Teknik Analiz Grafiği';
            modal.classList.add('show');

            document.getElementById('chartCanvas').innerHTML = `
                <div class="loading">
                    <i class="fas fa-spinner fa-spin"></i>
                    <h3>Grafik yükleniyor...</h3>
                    <p>${symbol} için Yahoo Finance verileri alınıyor</p>
                </div>
            `;

            try {
                const response = await fetch(API.CHART + '?symbol=' + encodeURIComponent(symbol));
                const data = await response.json();

                if (data && Array.isArray(data) && data.length > 0) {
                    drawCandlestickChart(data, symbol);
                } else {
                    showChartError(symbol, "Grafik verisi bulunamadı");
                }
            } catch (error) {
                showChartError(symbol, error.message);
            }
        }

        function showChartError(symbol, message) {
            document.getElementById('chartCanvas').innerHTML = `
                <div class="loading">
                    <i class="fas fa-exclamation-triangle" style="color: #ef4444;"></i>
                    <h3>Hata</h3>
                    <p>${message}</p>
                    <p>Hisse: ${symbol}</p>
                    <button onclick="showChartModal('${symbol}')" style="margin-top: 20px; padding: 10px 20px; background: #3b82f6; color: white; border: none; border-radius: 5px; cursor: pointer;">
                        Tekrar Dene
                    </button>
                </div>
            `;
        }

        function closeChartModal() {
            document.getElementById('chartModal').classList.remove('show');
            Plotly.purge('chartCanvas');
        }

        function download2KChart() {
            const btn = event.target.closest('button');
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 2K İndiriliyor...';
            const title = document.getElementById('chartTitle').textContent;
            const filename = title.split(' - ')[0] + '-grafik-2k-' + new Date().toISOString().slice(0,10) + '.png';
            Plotly.downloadImage('chartCanvas', {format: 'png', width: 2560, height: 1440}, filename);
            setTimeout(() => {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-download"></i> 2K İndir';
            }, 1500);
        }

        // --- GELİŞMİŞ TEKNİK ANALİZ FONKSİYONLARI ---
        function findPivotPoints(highs, lows, period = 5) {
            let pivotHighs = [];
            let pivotLows = [];
            const n = highs.length;
            for (let i = period; i < n - period; i++) {
                let isPivotLow = true;
                for (let j = 1; j <= period; j++) {
                    if (lows[i] > lows[i - j] || lows[i] > lows[i + j]) {
                        isPivotLow = false;
                        break;
                    }
                }
                if (isPivotLow) pivotLows.push({ index: i, value: lows[i] });
                let isPivotHigh = true;
                for (let j = 1; j <= period; j++) {
                    if (highs[i] < highs[i - j] || highs[i] < highs[i + j]) {
                        isPivotHigh = false;
                        break;
                    }
                }
                if (isPivotHigh) pivotHighs.push({ index: i, value: highs[i] });
            }
            return { pivotHighs, pivotLows };
        }

        function calculateMainTrendLines(highs, lows, dates) {
            const n = highs.length;
            if (n < 50) return {};
            const pivots = findPivotPoints(highs, lows, 5);
            const pLows = pivots.pivotLows;
            let bestSupport = null;
            let maxScore = -Infinity;
            const midPoint = Math.floor(n / 2);
            const leftPivots = pLows.filter(p => p.index < midPoint);
            const rightPivots = pLows.filter(p => p.index > midPoint);

            if (leftPivots.length > 0 && rightPivots.length > 0) {
                for (let lPivot of leftPivots) {
                    for (let rPivot of rightPivots) {
                        if (rPivot.index - lPivot.index < 20) continue;
                        const slope = (rPivot.value - lPivot.value) / (rPivot.index - lPivot.index);
                        const startVal = lPivot.value;
                        let valid = true;
                        for (let k = lPivot.index + 1; k < rPivot.index; k++) {
                            const lineVal = startVal + slope * (k - lPivot.index);
                            if (lows[k] < lineVal * 0.99) { valid = false; break; }
                        }
                        if (valid) {
                            let touches = 0;
                            for (let p of pLows) {
                                const lineVal = startVal + slope * (p.index - lPivot.index);
                                if (Math.abs(p.value - lineVal) / p.value < 0.015) touches++;
                            }
                            const score = touches * (rPivot.index - lPivot.index);
                            if (score > maxScore) {
                                maxScore = score;
                                bestSupport = { startIdx: lPivot.index, startVal: lPivot.value, slope: slope };
                            }
                        }
                    }
                }
            }

            const projectionDays = 30;
            const extendedDates = [...dates];
            const lastDate = new Date(dates[dates.length - 1]);
            for (let i = 1; i <= projectionDays; i++) {
                const nextDate = new Date(lastDate);
                nextDate.setDate(lastDate.getDate() + i);
                extendedDates.push(nextDate.toISOString().split('T')[0]);
            }

            let supportLine = [];
            if (bestSupport) {
                for (let i = 0; i < extendedDates.length; i++) {
                    if (i < bestSupport.startIdx) { supportLine.push(null); } 
                    else { supportLine.push(bestSupport.startVal + bestSupport.slope * (i - bestSupport.startIdx)); }
                }
            }

            return {
                support: { 
                    x: extendedDates, y: supportLine, type: 'scatter', mode: 'lines', 
                    name: 'Ana Destek (Güçlü)', line: { color: '#10b981', width: 2 } 
                }
            };
        }

        function calculateCupPattern(highs, lows, dates) {
            const n = highs.length;
            if (n < 60) return null;
            let leftPeakVal = -Infinity, leftPeakIdx = 0;
            for (let i = 0; i < n - 40; i++) { if (highs[i] > leftPeakVal) { leftPeakVal = highs[i]; leftPeakIdx = i; } }
            let bottomVal = Infinity, bottomIdx = leftPeakIdx;
            for (let i = leftPeakIdx; i < n - 10; i++) { if (lows[i] < bottomVal) { bottomVal = lows[i]; bottomIdx = i; } }
            let rightPeakVal = -Infinity, rightPeakIdx = n - 1;
            for (let i = bottomIdx; i < n; i++) { if (highs[i] > rightPeakVal) { rightPeakVal = highs[i]; rightPeakIdx = i; } }
            
            if ((bottomIdx - leftPeakIdx) < 15 || (rightPeakIdx - bottomIdx) < 10) return null;
            const peakDiffRatio = Math.abs(leftPeakVal - rightPeakVal) / leftPeakVal;
            if (peakDiffRatio > 0.15) return null; 
            const cupDepth = leftPeakVal - bottomVal;
            const depthPercent = cupDepth / leftPeakVal;
            if (depthPercent < 0.10 || depthPercent > 0.60) return null;
            const targetVal = rightPeakVal + cupDepth;

            const extendedDates = [...dates];
            const projectionDays = 60;
            const lastDate = new Date(dates[dates.length - 1]);
            for (let i = 1; i <= projectionDays; i++) {
                const nextDate = new Date(lastDate);
                nextDate.setDate(lastDate.getDate() + i);
                extendedDates.push(nextDate.toISOString().split('T')[0]);
            }

            return {
                cup: { x: [dates[leftPeakIdx], dates[bottomIdx], dates[rightPeakIdx]], y: [leftPeakVal, bottomVal, rightPeakVal], type: 'scatter', mode: 'lines', name: 'Fincan Formasyonu', line: { color: '#a855f7', width: 3, shape: 'spline' } },
                target: { x: [dates[rightPeakIdx], extendedDates[extendedDates.length - 1]], y: [targetVal, targetVal], type: 'scatter', mode: 'lines', name: `Hedef: ${targetVal.toFixed(2)}₺`, line: { color: '#ec4899', width: 2, dash: 'dashdot' } },
                base: { x: [dates[leftPeakIdx], dates[rightPeakIdx]], y: [leftPeakVal, rightPeakVal], type: 'scatter', mode: 'lines', name: 'Boyun Hattı', line: { color: '#6366f1', width: 1, dash: 'dot' } }
            };
        }

        function drawCandlestickChart(data, symbol) {
            const dates = [], opens = [], highs = [], lows = [], closes = [];
            
            // Veri Yahoo formatından geldiğinde (Timestamp, Open, High, Low, Close)
            if (Array.isArray(data)) {
                data.forEach(item => {
                    if (Array.isArray(item) && item.length >= 5) {
                        // Timestamp to ISO String
                        const dateStr = new Date(item[0]).toISOString().split('T')[0];
                        const open = parseFloat(item[1]);
                        const high = parseFloat(item[2]);
                        const low = parseFloat(item[3]);
                        const close = parseFloat(item[4]);
                        
                        if (close > 0) {
                            dates.push(dateStr);
                            opens.push(open);
                            highs.push(high);
                            lows.push(low);
                            closes.push(close);
                        }
                    }
                });
            }

            if (dates.length < 5) {
                document.getElementById('chartCanvas').innerHTML = `<div class="loading"><h3>Yeterli veri yok</h3></div>`;
                return;
            }

            const trace1 = {
                x: dates, open: opens, high: highs, low: lows, close: closes,
                type: 'candlestick', name: symbol,
                increasing: { line: {color: '#10b981', width: 2}, fillcolor: 'rgba(16, 185, 129, 0.7)' },
                decreasing: { line: {color: '#ef4444', width: 2}, fillcolor: 'rgba(239, 68, 68, 0.7)' }
            };

            const mainTrends = calculateMainTrendLines(highs, lows, dates);
            const cupPattern = calculateCupPattern(highs, lows, dates);
            
            const lastPrice = closes[closes.length - 1];
            const traceLastPrice = {
                x: [dates[dates.length - 1], dates[dates.length - 1]],
                y: [Math.min(...lows) * 0.95, Math.max(...highs) * 1.05],
                type: 'scatter', mode: 'lines', name: `Son: ${lastPrice.toFixed(2)}₺`,
                line: { color: '#6b7280', width: 1, dash: 'dot' }
            };

            const allTraces = [trace1, traceLastPrice];
            if (mainTrends && mainTrends.support) allTraces.push(mainTrends.support);
            if (cupPattern) { allTraces.push(cupPattern.cup); allTraces.push(cupPattern.target); allTraces.push(cupPattern.base); }

            const layout = {
                title: { text: `${symbol} - Fiyat Grafiği` },
                xaxis: { title: 'Tarih', type: 'category', rangeslider: { visible: true, thickness: 0.05 }, showgrid: false },
                yaxis: { title: 'Fiyat (₺)', tickprefix: '₺', showgrid: false },
                height: 800, margin: {l: 50, r: 50, t: 50, b: 50},
                plot_bgcolor: '#ffffff', paper_bgcolor: '#ffffff', hovermode: 'x unified'
            };
            Plotly.newPlot('chartCanvas', allTraces, layout, { responsive: true });
        }

        window.onclick = function(event) {
            const modal = document.getElementById('chartModal');
            if (event.target === modal) closeChartModal();
        }

        loadStocks();
    </script>
</body>
</html>
"""

# --- BACKEND FONKSİYONLARI ---

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
        response = requests.post(TRADINGVIEW_SCANNER_URL, headers=HEADERS_TV, json=post_data, timeout=45)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Scanner Error: {e}")
    return None

def fetch_chart_data(symbol):
    """
    Yahoo Finance'den grafik verilerini çeker.
    Format: [[timestamp, open, high, low, close], ...]
    """
    if not symbol: return []
    
    # TradingView sembolü "THYAO" -> Yahoo sembolü "THYAO.IS"
    y_symbol = f"{symbol}.IS"
    
    try:
        url = YAHOO_CHART_URL.format(y_symbol)
        response = requests.get(url, headers=HEADERS_YAHOO, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            result = data.get('chart', {}).get('result', [])
            
            if not result: return []
            
            quote = result[0].get('indicators', {}).get('quote', [{}])[0]
            timestamps = result[0].get('timestamp', [])
            
            opens = quote.get('open', [])
            highs = quote.get('high', [])
            lows = quote.get('low', [])
            closes = quote.get('close', [])
            
            formatted_data = []
            
            for i in range(len(timestamps)):
                if opens[i] is None or closes[i] is None: continue # Eksik veriyi atla
                
                # JavaScript milisaniye beklediği için 1000 ile çarpıyoruz
                ts = timestamps[i] * 1000 
                formatted_data.append([
                    ts,
                    opens[i],
                    highs[i],
                    lows[i],
                    closes[i]
                ])
                
            return formatted_data
            
    except Exception as e:
        print(f"Chart Error {symbol}: {e}")
    
    return []

# BACKEND: Destek Seviyesi Hesaplama
def calculate_trend_levels(raw_data):
    lows = []
    
    # Yahoo verisinden Low'ları al (Index 3 -> Low)
    if isinstance(raw_data, list):
        for item in raw_data:
            if len(item) >= 4:
                lows.append(item[3])
    
    if len(lows) < 50: return None
    
    n = len(lows)
    # 1. En düşük dip (Global Low)
    min_val = min(lows)
    min_idx = lows.index(min_val)
    
    if min_idx > n * 0.9:
        sub_lows = lows[:int(n*0.9)]
        if sub_lows:
            min_val = min(sub_lows)
            min_idx = sub_lows.index(min_val)

    # 2. Basit Trend Hesabı
    last_quarter_idx_start = int(n * 0.75)
    if last_quarter_idx_start <= min_idx: 
        last_quarter_idx_start = min_idx + 10
        
    if last_quarter_idx_start < n:
        min_val2 = min(lows[last_quarter_idx_start:])
        try:
            min_idx2 = lows.index(min_val2, last_quarter_idx_start)
            
            if min_idx2 > min_idx:
                slope = (min_val2 - min_val) / (min_idx2 - min_idx)
                current_support = min_val + slope * (n - 1 - min_idx)
                return {'currentSupport': current_support}
        except:
            pass
            
    return {'currentSupport': min_val}

def process_batch_symbol(symbol):
    # Sadece grafik verisini alıyoruz, piyasa bilgisi zaten TV scanner'dan geliyor
    chart_data = fetch_chart_data(symbol)
    support_val = None
    if chart_data and len(chart_data) >= 50:
        trend_data = calculate_trend_levels(chart_data)
        if trend_data and trend_data['currentSupport'] > 0:
            support_val = round(trend_data['currentSupport'], 2)
    return symbol, None, support_val

# --- ROTAS ---

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/scanner')
def api_scanner():
    data = fetch_stock_scanner_data()
    return jsonify(data if data else {'error': 'Data fetch failed'})

@app.route('/api/chart')
def api_chart():
    symbol = request.args.get('symbol', '')
    data = fetch_chart_data(symbol)
    return jsonify(data)

@app.route('/api/batch-all')
def api_batch_all():
    symbols_param = request.args.get('symbols', '')
    if not symbols_param:
        return jsonify({'supports': {}})
        
    symbols = [s for s in symbols_param.split(',') if s]
    supports = {}
    
    # Pool boyutunu Yahoo'ya çok yüklenmemek için biraz sınırlı tutuyoruz
    pool = Pool(8)
    jobs = [pool.spawn(process_batch_symbol, sym) for sym in symbols]
    gevent.joinall(jobs)

    for job in jobs:
        try:
            if job.value:
                sym, _, sup = job.value
                if sup: supports[sym] = sup
        except: pass
                
    return jsonify({'supports': supports})

if __name__ == '__main__':
    from gevent.pywsgi import WSGIServer
    print("Sunucu 8080 portunda başlatılıyor...")
    http_server = WSGIServer(('0.0.0.0', 8080), app)
    http_server.serve_forever()
