const ASSET_VERSION = '20260710-01';
const withVersion = (path) => `${path}?v=${ASSET_VERSION}`;
const RANGE_DAYS = { all: null, '7': 7, '30': 30, '90': 90, '180': 180, '365': 365 };
const STRATEGY_META = {
  ai_analyst:       { name: 'AI Analyst',       color: '#ff6b6b', desc: 'LLM-based market analysis & trading' },
  quant_learning:   { name: 'Quant AI',          color: '#4ecdc4', desc: 'ML multi-signal voting system' },
  etf_aggressive:   { name: 'DCA Aggressive',    color: '#a78bfa', desc: '42.5/42.5/15 VOO/VGT/SMH' },
  etf_balanced:     { name: 'DCA Balanced',      color: '#c4b5fd', desc: '50/40/10 VOO/VGT/SMH' },
  etf_conservative: { name: 'DCA Conservative',  color: '#ddd6fe', desc: '60/35/5 VOO/VGT/SMH' },
  spy:              { name: 'S&P 500',           color: '#fbbf24', desc: 'Buy-and-hold benchmark' },
};

function fmtMoney(v) {
  if (v == null || isNaN(v)) return '-';
  return '$' + Number(v).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

function fmtPct(v) {
  if (v == null || isNaN(v)) return '-';
  const sign = v >= 0 ? '+' : '';
  return sign + (v * 100).toFixed(2) + '%';
}

function latestBySource(rows) {
  const bySource = {};
  rows.forEach(row => {
    if (!bySource[row.source] || row.date > bySource[row.source].date) bySource[row.source] = row;
  });
  return bySource;
}

function latestDate(rows) {
  const dates = rows.map(row => row.date).filter(Boolean).sort();
  return dates.length ? dates[dates.length - 1] : null;
}

function signalDates(signals) {
  return [...new Set(signals.map(s => s.date).filter(Boolean))].sort((a, b) => b.localeCompare(a));
}

function filterByRange(equityData, range) {
  if (range === 'all' || !RANGE_DAYS[range]) return equityData;
  const dates = equityData.map(d => d.date).sort();
  if (!dates.length) return equityData;
  const end = new Date(`${dates[dates.length - 1]}T00:00:00`);
  const cutoff = new Date(end);
  cutoff.setDate(cutoff.getDate() - RANGE_DAYS[range]);
  return equityData.filter(d => new Date(`${d.date}T00:00:00`) >= cutoff);
}

async function fetchJson(path) {
  const response = await fetch(withVersion(path));
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json();
}

async function loadArenaData(files = ['strategies', 'signals', 'equity_curve', 'holdings']) {
  const entries = await Promise.all(files.map(async name => [name, await fetchJson(`data/${name}.json`)]));
  return Object.fromEntries(entries);
}

function computeDataHealth(data) {
  const equity = data.equity_curve || data.equity || [];
  const holdings = data.holdings || [];
  const signals = data.signals || [];
  const health = data.health || {};
  const latestHoldings = holdings.filter(row => row.date === latestDate(holdings));
  return {
    marketDate: health.latest_market_date || latestDate(equity),
    aiAnalysisDate: health.latest_ai_analysis_date || '-',
    signalDate: health.latest_signal_date || latestDate(signals),
    carriedCount: health.carried_forward_prices ?? holdings.filter(row => row.price_status === 'carried_forward').length,
    latestCarriedCount: health.latest_carried_forward_prices ?? latestHoldings.filter(row => row.price_status === 'carried_forward').length,
    sources: health.source_count || Object.keys(latestBySource(equity)).length,
  };
}

function renderDataHealth(data, targetId = 'dataHealth') {
  const el = document.getElementById(targetId);
  if (!el) return;
  const health = computeDataHealth(data);
  const carriedLabel = health.latestCarriedCount
    ? `${health.latestCarriedCount} carried-forward prices today`
    : 'All latest prices actual';
  el.innerHTML = `
    <div class="data-health-item"><span>Latest market data</span><strong>${health.marketDate || '-'}</strong></div>
    <div class="data-health-item"><span>Latest AI analysis</span><strong>${health.aiAnalysisDate || '-'}</strong></div>
    <div class="data-health-item"><span>Sources</span><strong>${health.sources}/6</strong></div>
    <div class="data-health-item"><span>Price status</span><strong>${carriedLabel}</strong></div>`;
}
