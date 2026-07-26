(() => {
  const stylesheet = document.createElement('link');
  stylesheet.rel = 'stylesheet';
  stylesheet.href = 'portfolio-nav.css?v=20260726-2';
  document.head.appendChild(stylesheet);

  const page = window.location.pathname.split('/').pop() || 'index.html';
  const projectActive = ['trading.html', 'analysis.html', 'method.html'].includes(page);
  const aboutActive = page === 'about.html';
  const nav = document.querySelector('nav');
  if (!nav) return;

  nav.outerHTML = `
    <nav class="portfolio-global-nav">
      <div class="portfolio-nav-inner">
        <a class="portfolio-brand" href="index.html"><span>◆</span> PD's Lab</a>
        <div class="portfolio-nav-links">
          <a class="portfolio-nav-link" href="index.html">Home</a>
          <div class="portfolio-project-nav">
            <button class="portfolio-project-button ${projectActive ? 'is-active' : ''}" type="button">Projects ▾</button>
            <div class="portfolio-project-menu">
              <a href="index.html#adeval">
                <span class="portfolio-project-index">01</span>
                <span><strong>AdEval Causal</strong><small>Featured · Causal measurement</small></span>
              </a>
              <a href="trading.html">
                <span class="portfolio-project-index">02</span>
                <span><strong>AI Trading Arena</strong><small>Applied AI engineering</small></span>
              </a>
            </div>
          </div>
          <a class="portfolio-nav-link ${aboutActive ? 'is-active' : ''}" href="about.html">About</a>
          <a class="portfolio-nav-link portfolio-hide-mobile" href="https://github.com/dpfai" target="_blank" rel="noopener">GitHub ↗</a>
        </div>
      </div>
    </nav>`;

})();
