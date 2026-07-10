// AI Trading Arena - Trading Page JS

async function loadData() {
  const data = await loadArenaData(['signals', 'equity_curve', 'holdings', 'health']);
  return { signals: data.signals, equity: data.equity_curve, holdings: data.holdings, health: data.health };
}

let equityChart = null;
let currentRange = 'all';
let selectedSignalDate = null;

function renderEquityChart(equityData, range) {
  const ctx = document.getElementById('equityChart');
  if (!ctx || !equityData.length || typeof Chart === 'undefined') return;
  
  const filtered = filterByRange(equityData, range);
  
  const bySource = {};
  filtered.forEach(d => { if (!bySource[d.source]) bySource[d.source] = []; bySource[d.source].push(d); });
  const allDates = [...new Set(filtered.map(d => d.date))].sort();
  const datasets = Object.entries(bySource).map(([source, rows]) => {
    const meta = STRATEGY_META[source] || { color: '#888', name: source };
    const dateMap = {};
    rows.forEach(r => { dateMap[r.date] = r.total_value; });
    return {
      label: meta.name, data: allDates.map(d => dateMap[d] ?? null),
      borderColor: meta.color, backgroundColor: meta.color + '20',
      borderWidth: 2, pointRadius: 3, pointHoverRadius: 6, tension: 0.3, spanGaps: true,
    };
  });
  
  if (equityChart) equityChart.destroy();
  equityChart = new Chart(ctx, {
    type: 'line',
    data: { labels: allDates, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: true, position: 'top', labels: { color: '#a0aec0', font: { size: 11 } } },
        tooltip: { backgroundColor: '#16213e', borderColor: '#233', borderWidth: 1,
          callbacks: { label: (c) => `${c.dataset.label}: ${fmtMoney(c.parsed.y)}` } },
      },
      scales: {
        x: { grid: { color: 'rgba(35,51,51,0.5)' }, ticks: { color: '#a0aec0', font: { size: 11 } } },
        y: { grid: { color: 'rgba(35,51,51,0.5)' }, ticks: { color: '#a0aec0', font: { size: 11 }, callback: (v) => '$' + (v/1000).toFixed(1) + 'k' } },
      },
    },
  });
}

function renderHoldings(holdings) {
  const tbody = document.getElementById('holdingsBody');
  if (!tbody) return;
  if (!holdings.length) { tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#8892b0">No holdings data.</td></tr>'; return; }
  const latestDate = [...new Set(holdings.map(h => h.date))].sort().pop();
  const sorted = holdings
    .filter(h => h.date === latestDate)
    .sort((a, b) => a.source.localeCompare(b.source) || b.value - a.value || a.ticker.localeCompare(b.ticker));
  tbody.innerHTML = sorted.map(h => {
    const meta = STRATEGY_META[h.source] || { name: h.source, color: '#888' };
    const plColor = h.profit_loss >= 0 ? '#4ecdc4' : '#ffa502';
    return `<tr>
      <td style="color:${meta.color}">${meta.name}</td>
      <td>${h.ticker}</td>
      <td>${h.shares?.toFixed(4) || '—'}</td>
      <td>${fmtMoney(h.cost_price)}</td>
      <td>${fmtMoney(h.current_price)}</td>
      <td>${fmtMoney(h.value)}</td>
      <td style="color:${plColor}">${fmtMoney(h.profit_loss)}</td>
      <td style="color:${plColor}">${fmtPct(h.return_pct)}</td>
    </tr>`;
  }).join('');
}

function setupSignalDateFilter(signals) {
  const select = document.getElementById('signalDateFilter');
  if (!select) return;
  const dates = signalDates(signals);
  selectedSignalDate = dates[0] || null;
  select.innerHTML = dates.map(date => `<option value="${date}">${date}</option>`).join('');
  select.disabled = dates.length === 0;
  select.addEventListener('change', () => {
    selectedSignalDate = select.value;
    renderSignals(signals, selectedSignalDate);
  });
}

function renderSignals(signals, date) {
  const tbody = document.getElementById('signalsBody');
  const metaEl = document.getElementById('signalsMeta');
  if (!tbody) return;
  if (!signals.length) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#8892b0">No signals yet.</td></tr>';
    if (metaEl) metaEl.textContent = 'No signal records available.';
    return;
  }
  const activeDate = date || signalDates(signals)[0];
  const sorted = signals
    .filter(s => s.date === activeDate)
    .sort((a, b) => a.source.localeCompare(b.source) || a.ticker.localeCompare(b.ticker));
  if (metaEl) metaEl.textContent = activeDate ? `Showing ${sorted.length} signals for ${activeDate}.` : '';
  if (!sorted.length) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#8892b0">No signals for this date.</td></tr>';
    return;
  }
  tbody.innerHTML = sorted.map(s => {
    const meta = STRATEGY_META[s.source] || { name: s.source, color: '#888' };
    const badgeClass = s.action === 'buy' ? 'badge-buy' : s.action === 'sell' ? 'badge-sell' : 'badge-hold';
    return `<tr>
      <td>${s.date}</td>
      <td style="color:${meta.color}">${meta.name}</td>
      <td><span class="badge ${badgeClass}">${s.action.toUpperCase()}</span></td>
      <td>${s.ticker}</td>
      <td>${fmtMoney(s.price)}</td>
      <td>${s.shares?.toFixed(4) || '—'}</td>
      <td>${fmtMoney(s.amount)}</td>
      <td style="font-size:11px;color:#8892b0;max-width:240px;overflow:hidden;text-overflow:ellipsis">${(s.reason || '').substring(0, 90)}</td>
    </tr>`;
  }).join('');
}

document.addEventListener('DOMContentLoaded', async function() {
  const data = await loadData();
  renderDataHealth({ equity: data.equity, holdings: data.holdings, signals: data.signals, health: data.health });
  renderEquityChart(data.equity, currentRange);
  renderHoldings(data.holdings);
  setupSignalDateFilter(data.signals);
  renderSignals(data.signals, selectedSignalDate);
  
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentRange = btn.dataset.range;
      renderEquityChart(data.equity, currentRange);
    });
  });
});
