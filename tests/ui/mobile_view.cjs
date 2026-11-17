// Trang điện thoại — Xem từng tấm (node tests/ui/mobile_view.cjs)
const assert=require('assert'),fs=require('fs'),path=require('path'),vm=require('vm'),{open,photo}=require('./mlib.cjs');
// --- toán zoom (hàm thuần trích từ mobile.html) ---
const src=fs.readFileSync(path.join(__dirname,'../../app/photosift/web/mobile.html'),'utf8');
const grab=n=>{const m=src.match(new RegExp('^function '+n+'\\([\\s\\S]*?^\\}','m')); if(!m) throw new Error('thiếu '+n); return m[0];};
const ctx={Math};vm.createContext(ctx);vm.runInContext(grab('zoomMax')+grab('zoomClamp')+grab('zoomAt')+grab('focusZoom'),ctx);
let z=ctx.zoomAt({scale:1,tx:0,ty:0},2,195,300,390,600,390,260,6000);
assert.equal(z.scale,2); assert.ok(Math.abs(z.tx-0)<1e-6,'giữ tâm'); 
z=ctx.zoomAt({scale:1,tx:0,ty:0},100,0,300,390,600,390,260,6000); assert.ok(Math.abs(z.scale-6000/390)<1e-6,'kẹp ở 100%');
z=ctx.zoomAt({scale:1,tx:0,ty:0},0.2,0,0,390,600,390,260,6000); assert.equal(z.scale,1);
z=ctx.zoomAt({scale:1,tx:0,ty:0},4,0,300,390,600,390,260,6000); assert.ok(z.tx<=(390*4-390)/2+1e-6,'không lộ mép');
z=ctx.focusZoom([0.25,0.5,9],390,600,390,260,6000); assert.ok(Math.abs(z.scale-6000/390)<1e-6); assert.ok(z.tx>0,'điểm nét bên trái → dịch ảnh sang phải');
(async()=>{
  const ph=[]; for(let i=1;i<=20;i++) ph.push(photo(i));
  for(let i=1;i<=5;i++) Object.assign(ph[i-1],{grp:9,best:i===2?1:0});
  ph[1].focus=[0.3,0.4,9]; ph[1].rating=0; ph[3].rating=2;
  let T=await open({photos:ph}); const pg=T.pg;
  const rates=()=>T.st.calls.filter(c=>c.path==='/api/rate').map(c=>c.body);
  // chạm ô loạt (best id 2) → mở Xem
  await pg.click('.tile[data-id="2"]'); await pg.waitForTimeout(300);
  assert.ok(await pg.isVisible('#view'),'mở Xem');
  assert.ok(T.st.calls.some(c=>c.path==='/api/preview'&&c.q.id==='2'&&!c.q.hq),'bản cache trước');
  assert.ok(T.st.calls.some(c=>c.path==='/api/preview'&&c.q.id==='2'&&c.q.hq==='1'&&+c.q.s>0),'rồi bản đúng cỡ màn hình');
  // dải loạt 5 tấm
  assert.equal((await pg.$$('#strip .sb')).length,5,'dải 5 tấm');
  // chạm đúp có điểm nét → 100%
  const box=await pg.$eval('#vstage',e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};});
  const cx=box.x+box.w/2, cy=box.y+box.h/2;
  await pg.touchscreen.tap(cx,cy); await pg.waitForTimeout(100); await pg.touchscreen.tap(cx,cy); await pg.waitForTimeout(150);
  const iw=await pg.evaluate(()=>vFit().iw);
  assert.ok(Math.abs(await pg.evaluate(()=>M.zoom.scale)-6000/iw)<0.01,'100% tại điểm nét');
  await pg.waitForTimeout(200);
  assert.ok(T.st.calls.some(c=>c.path==='/api/preview'&&c.q.id==='2'&&c.q.s==='0'),'zoom > 1.5 → bản gốc');
  // đang zoom: vuốt ngang không chấm
  const n0=rates().length; await pg.mouse.move(cx,cy); await pg.mouse.down(); await pg.mouse.move(cx+200,cy,{steps:6}); await pg.mouse.up(); await pg.waitForTimeout(150);
  assert.equal(rates().length,n0,'zoom: vuốt chỉ di chuyển');
  // đặt zoom 2 rồi chạm tấm thứ 3 trong dải → giữ scale 2
  await pg.evaluate(()=>{M.zoom={scale:2,tx:0,ty:0};vApply();}); await pg.click('#strip .sb:nth-child(3)'); await pg.waitForTimeout(150);
  assert.equal(await pg.evaluate(()=>M.cur),3); assert.equal(await pg.evaluate(()=>M.zoom.scale),2,'giữ mức zoom khi so loạt');
  // Chọn tấm này: 3 → ★1, các tấm chưa chấm khác của loạt → loại (id 4 có 2 sao giữ nguyên)
  await pg.click('#pickBtn'); await pg.waitForTimeout(200);
  const rr=rates().slice(-2); assert.deepEqual(rr.find(b=>b.rating===1).ids,[3]); assert.deepEqual(rr.find(b=>b.rating===-1).ids.sort(),[1,2,5]);
  // chạm đúp lần nữa về vừa màn hình
  await pg.evaluate(()=>{M.zoom={scale:1,tx:0,ty:0};vApply();});
  // ở vừa màn hình: vuốt phải → Giữ (★1) và sang tấm sau
  await pg.evaluate(()=>openView(7)); await pg.waitForTimeout(150);
  await pg.mouse.move(cx,cy); await pg.mouse.down(); await pg.mouse.move(cx+200,cy,{steps:6}); await pg.mouse.up(); await pg.waitForTimeout(300);
  assert.deepEqual(rates().slice(-1)[0],{ids:[7],rating:1}); assert.equal(await pg.evaluate(()=>M.cur),8,'sang tấm sau');
  // chạm mép phải 1 lần → sang tấm sau sau ≥250ms; chạm đúp ở mép → không chuyển
  await pg.touchscreen.tap(box.x+box.w-20,cy); assert.equal(await pg.evaluate(()=>M.cur),8,'chưa chuyển ngay'); await pg.waitForTimeout(350);
  assert.equal(await pg.evaluate(()=>M.cur),9,'chạm mép phải → tấm sau');
  await pg.touchscreen.tap(box.x+box.w-20,cy); await pg.waitForTimeout(90); await pg.touchscreen.tap(box.x+box.w-20,cy); await pg.waitForTimeout(400);
  assert.equal(await pg.evaluate(()=>M.cur),9,'chạm đúp ở mép không chuyển'); assert.ok(Math.abs(await pg.evaluate(()=>M.zoom.scale)-2.5)<0.01,'double tap without focus → 2.5×');
  // ảnh không thuộc loạt → không có dải
  assert.ok(!(await pg.isVisible('#strip')),'không có dải');
  // ◎ bật/tắt khung nét
  await pg.evaluate(()=>openView(2)); await pg.waitForTimeout(100);
  const fb=()=>pg.isVisible('#fbox'); const before=await fb(); await pg.click('#btnFocus'); assert.notEqual(await fb(),before);
  // đóng Xem → lưới đánh dấu ô vừa xem
  await pg.click('#vBack'); await pg.waitForTimeout(150); assert.ok(!(await pg.isVisible('#view'))); assert.ok(await pg.$('.tile.cur'));
  await pg.evaluate(()=>openView(2)); await pg.waitForTimeout(250);
  await pg.screenshot({path:process.env.SHOT||'/tmp/m-view.png'});
  assert.deepEqual(T.errs,[]); await T.close();
  console.log('ok (mobile view)');
})().catch(e=>{console.error(e.message);process.exit(1)});
