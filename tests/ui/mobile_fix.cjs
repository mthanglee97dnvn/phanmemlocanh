// Sửa sau đợt soát cuối — trang điện thoại (node tests/ui/mobile_fix.cjs)
const assert=require('assert'),{open,photo}=require('./mlib.cjs');
const PE=(pg,list)=>pg.evaluate(list=>{const st=document.getElementById('vstage'),r=st.getBoundingClientRect();
  for(const [type,id,x,y] of list) st.dispatchEvent(new PointerEvent(type,{pointerId:id,pointerType:'touch',clientX:r.left+x,clientY:r.top+y,bubbles:true,isPrimary:id===1}));},list);
(async()=>{
  const ph=[]; for(let i=1;i<=40;i++) ph.push(photo(i));
  let T=await open({photos:ph}); const pg=T.pg; const rates=()=>T.st.calls.filter(c=>c.path==='/api/rate');
  // 1. chụm 2 ngón rồi nhấc 1 ngón, ngón còn lại di chuyển → không chấm, không chuyển tấm
  await pg.evaluate(()=>openView(5)); await pg.waitForTimeout(150);
  await PE(pg,[['pointerdown',1,100,300],['pointerdown',2,250,300],['pointermove',2,330,300],['pointerup',1,100,300],['pointermove',2,360,300],['pointermove',2,380,300],['pointerup',2,380,300]]);
  await pg.waitForTimeout(400); assert.equal(rates().length,0,'chụm không được chấm'); assert.equal(await pg.evaluate(()=>M.cur),5);
  // 8. vuốt bị huỷ (pointercancel) → không chấm
  await pg.evaluate(()=>{M.zoom={scale:1,tx:0,ty:0};vApply();});
  await PE(pg,[['pointerdown',3,100,300],['pointermove',3,200,300],['pointermove',3,330,300],['pointercancel',3,330,300]]); await pg.waitForTimeout(300);
  assert.equal(rates().length,0,'pointercancel không chấm');
  // 9. chạm mép rồi chạm lại ở 270ms → là chạm đúp, không chuyển tấm
  await PE(pg,[['pointerdown',4,370,300],['pointerup',4,370,300]]); await pg.waitForTimeout(270);
  await PE(pg,[['pointerdown',5,370,300],['pointerup',5,370,300]]); await pg.waitForTimeout(400);
  assert.equal(await pg.evaluate(()=>M.cur),5,'chạm đúp ở mép trong 300ms không chuyển tấm');
  await pg.evaluate(()=>{M.zoom={scale:1,tx:0,ty:0};vApply();closeView();});
  // 5. lọc Chưa chấm, xem tấm 5, chấm 3 sao (rời bộ lọc) rồi › → tấm 6, không về tấm 1
  await pg.click('.chip[data-f="todo"]'); await pg.evaluate(()=>openView(5)); await pg.waitForTimeout(100);
  await pg.click('#vstars [data-v="3"]'); await pg.waitForTimeout(150); await pg.click('#vNext'); await pg.waitForTimeout(100);
  assert.equal(await pg.evaluate(()=>M.cur),6,'› sang tấm kế tiếp sau tấm vừa rời bộ lọc');
  assert.ok(!/^0 \//.test(await pg.textContent('#vcount')),'bộ đếm không hiện 0 / N');
  await pg.evaluate(()=>closeView()); await pg.click('.chip[data-f="all"]');
  // 4. đồng bộ ép khi đang đồng bộ → vẫn tải lại
  const n0=T.st.calls.filter(c=>c.path==='/api/photos').length;
  await pg.evaluate(()=>{ mSync(); return mSync(true); }); await pg.waitForTimeout(200);
  assert.ok(T.st.calls.filter(c=>c.path==='/api/photos').length-n0>=1,'đồng bộ ép không bị bỏ');
  // 3. đồng bộ chỉ vá ô đổi: thẻ img của ô không đổi vẫn là nút cũ
  await pg.evaluate(()=>{document.querySelector('.tile[data-id="2"] img').__keep=1;});
  T.st.photos[2].rating=2; T.st.ver++; await pg.evaluate(()=>mSync()); await pg.waitForTimeout(200);
  assert.ok(await pg.evaluate(()=>document.querySelector('.tile[data-id="2"] img').__keep===1),'ô không đổi giữ nguyên ảnh');
  assert.ok(await pg.$('.tile[data-id="3"] .st'),'ô đổi được vá');
  // 6/15. chống chọn chữ / callout / phóng cả trang
  assert.equal(await pg.$eval('.tile',e=>getComputedStyle(e).webkitUserSelect),'none');
  assert.equal(await pg.$eval('#grid',e=>getComputedStyle(e).touchAction),'pan-y');
  // 7a. ★3 trong thanh chọn nhiều
  assert.ok(await pg.$('#selBtns [data-r="3"]'),'có ★3');
  // 7b. giờ chụp của đoạn đang cuộn hiện ở thanh trên
  await pg.evaluate(()=>{const g=document.getElementById('grid'); g.scrollTop=g.scrollHeight-g.clientHeight; g.dispatchEvent(new Event('scroll'));}); await pg.waitForTimeout(120);
  const want=await pg.evaluate(()=>{const t=new Date(M.by[40].taken*1000); return ('0'+t.getHours()).slice(-2)+':'+('0'+t.getMinutes()).slice(-2);});
  assert.ok((await pg.textContent('#fsub')).includes(want),'giờ đoạn đang cuộn');
  // 7c. vuốt xuống đóng bảng ⋯
  await pg.click('#btnTools'); await pg.waitForTimeout(100);
  await pg.evaluate(()=>{const s=document.getElementById('sheet'),r=s.getBoundingClientRect(),mk=(t,y)=>s.dispatchEvent(new PointerEvent(t,{pointerId:9,pointerType:'touch',clientX:r.left+100,clientY:y,bubbles:true}));
    mk('pointerdown',r.top+10); mk('pointermove',r.top+80); mk('pointermove',r.top+160); mk('pointerup',r.top+160);}); await pg.waitForTimeout(150);
  assert.ok(!(await pg.isVisible('#sheetWrap')),'vuốt xuống đóng bảng');
  assert.deepEqual(T.errs,[]); await T.close();
  // 2. iPhone Pro Max ngang 932×430 → không chia đôi; 13. rời chia đôi bỏ body.viewing
  T=await open({photos:ph,viewport:{width:932,height:430}});
  assert.ok(!(await T.pg.evaluate(()=>M.split)),'iPhone ngang không vào chế độ iPad');
  await T.pg.setViewportSize({width:1180,height:820}); await T.pg.waitForTimeout(150); assert.ok(await T.pg.evaluate(()=>M.split));
  await T.pg.setViewportSize({width:390,height:844}); await T.pg.waitForTimeout(150);
  assert.ok(!(await T.pg.evaluate(()=>document.body.classList.contains('viewing'))),'bỏ body.viewing khi rời chia đôi');
  assert.deepEqual(T.errs,[]); await T.close();
  console.log('ok (mobile fix)');
})().catch(e=>{console.error(e.message);process.exit(1)});
