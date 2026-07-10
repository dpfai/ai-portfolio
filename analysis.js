async function loadData() {
  const data = await loadArenaData(['equity_curve', 'holdings', 'signals', 'health']);
  return { equity: data.equity_curve, holdings: data.holdings, signals: data.signals, health: data.health };
}

function renderPerformance(equity) {
  const el = document.getElementById('performanceGrid');
  const latest = latestBySource(equity);
  const rows = Object.entries(latest).sort((a, b) => b[1].total_value - a[1].total_value);
  el.innerHTML = rows.map(([source, row]) => {
    const meta = STRATEGY_META[source] || { name: source, color: '#888' };
    const color = row.return_pct >= 0 ? '#4ecdc4' : '#ffa502';
    return `<div class="card p-5">
      <div class="flex items-center gap-2 mb-4"><span class="w-3 h-3 rounded-full" style="background:${meta.color}"></span><h2 class="font-semibold">${meta.name}</h2></div>
      <div class="metric"><span>Total Value</span><strong>${fmtMoney(row.total_value)}</strong></div>
      <div class="metric"><span>Stock/ETF Value</span><strong>${fmtMoney(row.positions_value)}</strong></div>
      <div class="metric"><span>Cash</span><strong>${fmtMoney(row.cash)}</strong></div>
      <div class="metric"><span>Return</span><strong style="color:${color}">${fmtPct(row.return_pct)}</strong></div>
      <p class="text-xs text-[var(--muted)] mt-3">Latest data: ${row.date}</p>
    </div>`;
  }).join('');
}

function renderHoldings(holdings) {
  const body = document.getElementById('holdingsSummary');
  if (!holdings.length) { body.innerHTML = '<tr><td colspan="5">No holdings data.</td></tr>'; return; }
  const latestDate = [...new Set(holdings.map(h => h.date))].sort().pop();
  const latest = holdings.filter(h => h.date === latestDate).sort((a, b) => b.value - a.value).slice(0, 20);
  body.innerHTML = latest.map(h => {
    const meta = STRATEGY_META[h.source] || { name: h.source, color: '#888' };
    const color = h.return_pct >= 0 ? '#4ecdc4' : '#ffa502';
    return `<tr>
      <td>${h.date}</td>
      <td style="color:${meta.color}">${meta.name}</td>
      <td>${h.ticker}</td>
      <td>${fmtMoney(h.value)}</td>
      <td style="color:${color}">${fmtPct(h.return_pct)}</td>
    </tr>`;
  }).join('');
}

function renderActivitySummary(signals) {
  const body = document.getElementById('activitySummary');
  if (!body) return;
  if (!signals.length) { body.innerHTML = '<tr><td colspan="6">No signals yet.</td></tr>'; return; }
  const bySource = {};
  signals.forEach(signal => {
    if (!bySource[signal.source]) bySource[signal.source] = { total: 0, buys: 0, sells: 0, latest: null };
    const row = bySource[signal.source];
    row.total += 1;
    if (signal.action === 'buy') row.buys += 1;
    if (signal.action === 'sell') row.sells += 1;
    if (!row.latest || signal.date > row.latest.date) row.latest = signal;
  });
  body.innerHTML = Object.entries(bySource).sort((a, b) => a[0].localeCompare(b[0])).map(([source, row]) => {
    const meta = STRATEGY_META[source] || { name: source, color: '#888' };
    const latest = row.latest || {};
    const badge = latest.action === 'buy' ? 'badge-buy' : latest.action === 'sell' ? 'badge-sell' : 'badge-hold';
    return `<tr>
      <td style="color:${meta.color}">${meta.name}</td>
      <td>${row.total}</td>
      <td>${row.buys}</td>
      <td>${row.sells}</td>
      <td>${latest.date || '-'} ${latest.action ? `<span class="badge ${badge} ml-2">${latest.action.toUpperCase()}</span>` : ''}</td>
      <td>${latest.ticker || '-'}</td>
    </tr>`;
  }).join('');
}

document.addEventListener('DOMContentLoaded', async () => {
  try {
    const data = await loadData();
    renderDataHealth({ equity: data.equity, holdings: data.holdings, signals: data.signals, health: data.health });
    renderPerformance(data.equity);
    renderHoldings(data.holdings);
    renderActivitySummary(data.signals);
  } catch (err) {
    console.error(err);
    document.getElementById('performanceGrid').innerHTML = '<p class="text-[var(--muted)]">Analysis data failed to load.</p>';
  }
});
