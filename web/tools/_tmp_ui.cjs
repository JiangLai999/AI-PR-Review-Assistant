
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
  await p.goto('http://127.0.0.1:8787/#/overview', { waitUntil: 'networkidle' });
  await p.waitForTimeout(2200);
  const top = await p.evaluate(() => {
    const sb = document.querySelector('.workspace-sidebar');
    const c  = document.querySelector('.main > .container');
    const sbcs = getComputedStyle(sb);
    return {
      sidebar: { pos: sbcs.position, w: Math.round(sb.getBoundingClientRect().width), h: Math.round(sb.getBoundingClientRect().height) },
      container: { w: Math.round(c.getBoundingClientRect().width) },
      docH: document.documentElement.scrollHeight,
      overflowX: document.documentElement.scrollWidth > innerWidth,
    };
  });
  await p.evaluate(() => window.scrollTo(0, 1600));
  await p.waitForTimeout(500);
  const scrolled = await p.evaluate(() => {
    const sb = document.querySelector('.workspace-sidebar');
    const r = sb.getBoundingClientRect();
    return { top: Math.round(r.top), bottom: Math.round(r.bottom), navVisible: r.top === 0 };
  });
  console.log(JSON.stringify({ top, scrolled }, null, 1));
  await b.close();
})();
