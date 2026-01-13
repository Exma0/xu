from gevent import monkey; monkey.patch_all()
import sys
# Rekürsiyon limitini artırıyoruz (Garanti olsun diye)
sys.setrecursionlimit(2000)

from flask import Flask, request, jsonify, render_template_string
import requests
import json
import gevent
from gevent.pool import Pool
import time

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
    <title>Borsa İstanbul Analiz Paneli (Gevent)</title>
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
                    <span>Hisse Senetleri</span>
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
                            <th style="text-align: right;" onclick="sortStocks(6)">Al (%)</th>
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
        let marketCache = {};
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
            const typespec = typespecs[0] || '';
            if (typespec.includes('st_yildiz') || typespec.toLowerCase().includes('stars')) return 'Yıldız Pazar';
            if (typespec.includes('st_ana') || typespec.toLowerCase().includes('main')) return 'Ana Pazar';
            if (typespec.includes('st_alt') || typespec.toLowerCase().includes('sub')) return 'Alt Pazar';
            if (typespec.toLowerCase().includes('watchlist')) return 'Yakın İzleme';
            return typespec || 'Bilinmiyor';
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
                        valueA = supA && pA > 0 ? ((pA - supA) / pA) * 100 : -999;
                        const supB = supportCache[b.d[0]];
                        const pB = parseFloat(b.d[6] || 0);
                        valueB = supB && pB > 0 ? ((pB - supB) / pB) * 100 : -999;
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
                        return marketCap > 0 && marketCap <= 1000000000;
                    }).sort((a, b) => parseFloat(a.d[15] || 0) - parseFloat(b.d[15] || 0));

                    displayStocks(allStocks);
                    updateStats();

                    const symbols = allStocks.map(s => s.d[0]);
                    const batchSize = 50; 

                    for (let i = 0; i < symbols.length; i += batchSize) {
                        const batch = symbols.slice(i, i + batchSize);
                        fetchBatchWithRetry(batch.join(','));
                        await new Promise(resolve => setTimeout(resolve, 100)); 
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
                if (result.markets) Object.assign(marketCache, result.markets);
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
                const marketFromApi = marketCache[symbol];
                const pazar = marketFromApi || getPazarFromTypespecs(typespecs);
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
                const supportDist = supportLevel && price > 0 ? (((price - supportLevel) / price) * 100).toFixed(2) : '-';
                
                const supportColor = supportDist > 0 ? '#10b981' : (supportDist < 0 ? '#ef4444' : '#666');

                return `<tr>
                    <td class="symbol" onclick="showChartModal('${symbol}')">${symbol}</td>
                    <td class="pazar">${pazar || 'Bilinmiyor'}</td>
                    <td style="text-align: right; font-weight: 600;">${price.toFixed(2)}₺</td>
                    <td style="text-align: right;" class="change ${changeClass}">${changeSign}${change}%</td>
                    <td style="text-align: right; color: #666;">${athDiffPercent}%</td>
                    <td style="text-align: right; color: ${supportColor}; font-weight: 600;">${supportDist}%</td>
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
                    <p>${symbol} için veriler alınıyor</p>
                </div>
            `;

            try {
                const response = await fetch(API.CHART + '?symbol=' + encodeURIComponent(symbol));
                const data = await response.json();

                if (data && Array.isArray(data) && data.length > 0) {
                    drawCandlestickChart(data, symbol);
                } else if (data && typeof data === 'object' && !Array.isArray(data)) {
                    drawCandlestickChart([data], symbol);
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

        // --- TEKNİK ANALİZ VE GRAFİK ÇİZİM FONKSİYONLARI ---
        
        function calculateMainTrendLines(highs, lows, dates) {
            const n = highs.length;
            if (n < 2) return {};

            // 1. Mutlak Zirve
            let absoluteMaxVal = -Infinity, absoluteMaxIdx = 0;
            for(let i = 0; i < n; i++) {
                if(highs[i] > absoluteMaxVal) { absoluteMaxVal = highs[i]; absoluteMaxIdx = i; }
            }
            let secondMaxVal = -Infinity, secondMaxIdx = n - 1;
            const searchStart = absoluteMaxIdx + Math.floor(n * 0.1);
            for(let i = searchStart; i < n; i++) {
                if(highs[i] > secondMaxVal) { secondMaxVal = highs[i]; secondMaxIdx = i; }
            }
            const absoluteSlope = (highs[secondMaxIdx] - highs[absoluteMaxIdx]) / (secondMaxIdx - absoluteMaxIdx);

            // 2. Ana Direnç
            let maxVal_r = -Infinity, maxIdx_r = 0;
            for(let i = 0; i < n * 0.3; i++) { if(highs[i] > maxVal_r) { maxVal_r = highs[i]; maxIdx_r = i; } }
            let lastMaxVal_r = -Infinity, lastMaxIdx_r = n - 1;
            for(let i = n - 1; i > n * 0.7; i--) { if(highs[i] > lastMaxVal_r) { lastMaxVal_r = highs[i]; lastMaxIdx_r = i; } }
            const resistanceSlope = (highs[lastMaxIdx_r] - highs[maxIdx_r]) / (lastMaxIdx_r - maxIdx_r);

            // 3. Ana Destek
            let minVal = Infinity, minIdx = 0;
            for(let i = 0; i < n * 0.3; i++) { if(lows[i] < minVal) { minVal = lows[i]; minIdx = i; } }
            let lastMinVal = Infinity, lastMinIdx = n - 1;
            for(let i = n - 1; i > n * 0.7; i--) { if(lows[i] < lastMinVal) { lastMinVal = lows[i]; lastMinIdx = i; } }
            const supportSlope = (lows[lastMinIdx] - lows[minIdx]) / (lastMinIdx - minIdx);

            const projectionDays = 30;
            const extendedDates = [...dates];
            const lastDate = new Date(dates[dates.length - 1]);
            for (let i = 1; i <= projectionDays; i++) {
                const nextDate = new Date(lastDate);
                nextDate.setDate(lastDate.getDate() + i);
                extendedDates.push(nextDate.toISOString().split('T')[0]);
            }

            const absoluteLine = [], resistanceLine = [], supportLine = [], midTrendLine = [];
            for (let i = 0; i < extendedDates.length; i++) {
                const absVal = highs[absoluteMaxIdx] + absoluteSlope * (i - absoluteMaxIdx);
                const resVal = highs[maxIdx_r] + resistanceSlope * (i - maxIdx_r);
                const supVal = lows[minIdx] + supportSlope * (i - minIdx);
                absoluteLine.push(absVal);
                resistanceLine.push(resVal);
                supportLine.push(supVal);
                midTrendLine.push((resVal + supVal) / 2);
            }

            return {
                absolutePeak: { x: extendedDates, y: absoluteLine, type: 'scatter', mode: 'lines', name: 'Zirve Trendi', line: { color: '#3b82f6', width: 2, dash: 'dot' } },
                resistance: { x: extendedDates, y: resistanceLine, type: 'scatter', mode: 'lines', name: 'Ana Direnç', line: { color: '#ef4444', width: 2 } },
                support: { x: extendedDates, y: supportLine, type: 'scatter', mode: 'lines', name: 'Ana Destek', line: { color: '#10b981', width: 2 } },
                midTrend: { x: extendedDates, y: midTrendLine, type: 'scatter', mode: 'lines', name: 'Trend Merkezi', line: { color: '#f59e0b', width: 2, dash: 'dash' } }
            };
        }

        function calculateCupPattern(highs, lows, dates) {
            const n = highs.length;
            if (n < 60) return null;
            let leftPeakVal = -Infinity, leftPeakIdx = 0;
            for (let i = 0; i < n - 20; i++) { if (highs[i] > leftPeakVal) { leftPeakVal = highs[i]; leftPeakIdx = i; } }
            let bottomVal = Infinity, bottomIdx = leftPeakIdx;
            for (let i = leftPeakIdx; i < n; i++) { if (lows[i] < bottomVal) { bottomVal = lows[i]; bottomIdx = i; } }
            let rightPeakVal = -Infinity, rightPeakIdx = n - 1;
            for (let i = bottomIdx; i < n; i++) { if (highs[i] > rightPeakVal) { rightPeakVal = highs[i]; rightPeakIdx = i; } }
            
            const cupDepth = leftPeakVal - bottomVal;
            if (cupDepth <= 0 || (bottomIdx - leftPeakIdx) < 10 || (rightPeakIdx - bottomIdx) < 10) return null;
            const targetVal = leftPeakVal + cupDepth;

            const extendedDates = [...dates];
            const projectionDays = 90;
            const lastDate = new Date(dates[dates.length - 1]);
            for (let i = 1; i <= projectionDays; i++) {
                const nextDate = new Date(lastDate);
                nextDate.setDate(lastDate.getDate() + i);
                extendedDates.push(nextDate.toISOString().split('T')[0]);
            }

            return {
                cup: { x: [dates[leftPeakIdx], dates[bottomIdx], dates[rightPeakIdx]], y: [leftPeakVal, bottomVal, highs[rightPeakIdx]], type: 'scatter', mode: 'lines', name: 'Çanak', line: { color: '#a855f7', width: 4, shape: 'spline' } },
                target: { x: [dates[leftPeakIdx], extendedDates[extendedDates.length - 1]], y: [targetVal, targetVal], type: 'scatter', mode: 'lines', name: `Katlama: ${targetVal.toFixed(2)}₺`, line: { color: '#ec4899', width: 2, dash: 'dashdot' } },
                base: { x: [dates[leftPeakIdx], dates[rightPeakIdx]], y: [leftPeakVal, leftPeakVal], type: 'scatter', mode: 'lines', name: 'Boyun Hattı', line: { color: '#6366f1', width: 1, dash: 'dot' } }
            };
        }

        function drawCandlestickChart(data, symbol) {
            const dates = [], opens = [], highs = [], lows = [], closes = [];
            if (Array.isArray(data)) {
                data.forEach(item => {
                    let dateStr = '', open=0, high=0, low=0, close=0;
                    if (item && typeof item === 'object') {
                        dateStr = item.Date || item.tarih || '';
                        if (dateStr && dateStr.includes('.')) {
                            const parts = dateStr.split(' ')[0].split('.');
                            if (parts.length === 3) dateStr = `${parts[0]}-${parts[1]}-${parts[2]}`;
                        }
                        open = parseFloat(item.fAcilis || item.Open || item.open || 0);
                        high = parseFloat(item.fYuksek || item.High || item.high || 0);
                        low = parseFloat(item.fDusuk || item.Low || item.low || 0);
                        close = parseFloat(item.fKapanis || item.Close || item.close || 0);
                    } else if (Array.isArray(item) && item.length >= 5) {
                        dateStr = new Date(item[0] * 1000).toISOString().split('T')[0];
                        open = parseFloat(item[1]); high = parseFloat(item[2]); low = parseFloat(item[3]); close = parseFloat(item[4]);
                    }
                    if (dateStr && !isNaN(close) && close > 0) {
                        dates.push(dateStr); opens.push(open>0?open:close); highs.push(high>0?high:Math.max(open,close)); lows.push(low>0?low:Math.min(open,close)); closes.push(close);
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

            const allTraces = [trace1, mainTrends.absolutePeak, mainTrends.resistance, mainTrends.support, mainTrends.midTrend, traceLastPrice];
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
        # Timeout'u biraz artırdık ve verify=True bıraktık (TradingView için SSL gerekli)
        response = requests.post(TRADINGVIEW_SCANNER_URL, headers=HEADERS, json=post_data, timeout=45)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Scanner Error: {e}")
    return None

def fetch_market_info(symbol):
    if not symbol: return None
    url = f"{IDEAL_DATA_URL}/cmd=SirketProfil?symbol={symbol}?lang=tr"
    try:
        response = requests.get(url, verify=False, timeout=8)
        if response.status_code == 200:
            content = response.content.decode('iso-8859-9')
            data = json.loads(content)
            if isinstance(data, dict):
                return data.get('Piyasa')
    except:
        pass
    return None

def fetch_chart_data(symbol):
    if not symbol: return []
    url = f"{IDEAL_DATA_URL}/cmd=CHART2?symbol={symbol}?periyot=G?bar=999999?lang=tr"
    try:
        response = requests.get(url, verify=False, timeout=10)
        if response.status_code == 200:
            content = response.content.decode('iso-8859-9')
            data = json.loads(content)
            if isinstance(data, list) or isinstance(data, dict):
                return data
    except:
        pass
    return []

def calculate_trend_levels(raw_data):
    lows = []
    
    if isinstance(raw_data, list):
        for item in raw_data:
            l = 0
            if isinstance(item, list) and len(item) > 3:
                l = float(item[3])
            elif isinstance(item, dict):
                l = float(item.get('fDusuk') or item.get('Low') or item.get('low') or 0)
            if l > 0: lows.append(l)
    
    if len(lows) < 50: return None
    
    n = len(lows)
    min_idx1, min_val1 = 0, lows[0]
    limit_low = int(n * 0.3)
    for i in range(limit_low):
        if lows[i] < min_val1: min_val1, min_idx1 = lows[i], i
        
    min_idx2, min_val2 = n - 1, lows[n - 1]
    limit_high = int(n * 0.7)
    for i in range(n - 1, limit_high, -1):
        if lows[i] < min_val2: min_val2, min_idx2 = lows[i], i
        
    support_slope = (lows[min_idx2] - lows[min_idx1]) / (min_idx2 - min_idx1) if min_idx2 != min_idx1 else 0
    current_support = lows[min_idx1] + support_slope * (n - 1 - min_idx1)
    
    return {'currentSupport': current_support}

def process_batch_symbol(symbol):
    market_info = fetch_market_info(symbol)
    chart_data = fetch_chart_data(symbol)
    support_val = None
    if chart_data and len(chart_data) >= 50:
        trend_data = calculate_trend_levels(chart_data)
        if trend_data and trend_data['currentSupport'] > 0:
            support_val = round(trend_data['currentSupport'], 2)
    return symbol, market_info, support_val

# --- ROTAS ---

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/scanner')
def api_scanner():
    data = fetch_stock_scanner_data()
    return jsonify(data if data else {'error': 'Data fetch failed'})

@app.route('/api/market')
def api_market():
    symbol = request.args.get('symbol', '')
    data = fetch_market_info(symbol)
    return jsonify(data)

@app.route('/api/chart')
def api_chart():
    symbol = request.args.get('symbol', '')
    data = fetch_chart_data(symbol)
    return jsonify(data)

@app.route('/api/batch-all')
def api_batch_all():
    symbols_param = request.args.get('symbols', '')
    if not symbols_param:
        return jsonify({'markets': {}, 'supports': {}})
        
    symbols = [s for s in symbols_param.split(',') if s]
    markets = {}
    supports = {}
    
    # Gevent Pool kullanımı (ThreadPoolExecutor yerine)
    pool = Pool(10)
    jobs = [pool.spawn(process_batch_symbol, sym) for sym in symbols]
    gevent.joinall(jobs)

    for job in jobs:
        try:
            if job.value:
                sym, mkt, sup = job.value
                if mkt: markets[sym] = mkt
                if sup: supports[sym] = sup
        except: pass
                
    return jsonify({'markets': markets, 'supports': supports})

if __name__ == '__main__':
    # SSL uyarısını gizle
    requests.packages.urllib3.disable_warnings()
    from gevent.pywsgi import WSGIServer
    http_server = WSGIServer(('0.0.0.0', 8080), app)
    http_server.serve_forever()
