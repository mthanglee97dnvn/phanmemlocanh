import { webkit } from 'playwright';
const b = await webkit.launch();
for (const [port, name] of [[8801, 'old'], [8802, 'new']]) {
  const p = await b.newPage({ viewport: { width: 1400, height: 860 } });
  await p.goto(`http://127.0.0.1:${port}/`); await p.waitForTimeout(4000);
  await p.screenshot({ path: `../../shots/webkit-${name}-1-loc-anh.png` });
  await p.click('#tLayout'); await p.waitForTimeout(1500); await p.screenshot({ path: `../../shots/webkit-${name}-2-dan-trang.png` });
  await p.click('#tFilter'); await p.waitForTimeout(1500); await p.screenshot({ path: `../../shots/webkit-${name}-3-ve-loc-anh.png` });
  await p.close();
}
await b.close();
