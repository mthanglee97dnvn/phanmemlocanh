// Trang điện thoại — chọn nhiều, hoàn tác, bảng ⋯ (node tests/ui/mobile_tools.cjs)
const assert=require('assert'),{open,photo}=require('./mlib.cjs');
(async()=>{
  const ph=[]; for(let i=1;i<=40;i++) ph.push(photo(i));
  for(let i=1;i<=4;i++) Object.assign(ph[i-1],{grp:5,best:i===1?1:0});
  ph[9].flags=['blur']; ph[10].flags=['eyes']; ph[11].flags=['dup']; ph[12].flags=['blur']; ph[12].rating=2;
  let T=await open({photos:ph,taste:{source:'personal',rolls:[{root:'/a',on:true}],n_rolls:12,agree:0.78,stale:false}}); const pg=T.pg;
  const calls=p=>T.st.calls.filter(c=>c.path===p);
  const longPress=async sel=>{const b=await pg.$eval(sel,e=>{const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};});
    await pg.mouse.move(b.x,b.y); await pg.mouse.down(); await pg.waitForTimeout(560); await pg.mouse.up(); await pg.waitForTimeout(80);};
  // chạm giữ → chế độ chọn; chọn thêm 2 ô
  await longPress('.tile[data-id="6"]'); assert.ok(await pg.evaluate(()=>M.selmode),'vào chế độ chọn');
  await pg.click('.tile[data-id="7"]'); await pg.click('.tile[data-id="8"]');
  assert.match(await pg.textContent('#selTitle'),/Đã chọn 3 tấm/);
  await pg.click('#selBar [data-r="1"]'); await pg.waitForTimeout(150);
  assert.deepEqual(calls('/api/rate').slice(-1)[0].body,{ids:[6,7,8],rating:1});
  assert.ok(!(await pg.evaluate(()=>M.selmode)),'thoát chế độ chọn sau khi chấm');
  // toast Hoàn tác → trả rating cũ (0)
  assert.ok(await pg.isVisible('#toastUndo')); await pg.click('#toastUndo'); await pg.waitForTimeout(150);
  assert.deepEqual(calls('/api/rate').slice(-1)[0].body,{ids:[6,7,8],rating:0});
  // chọn ô gộp ×4 → cả 4 id
  await longPress('.tile[data-id="1"]'); assert.match(await pg.textContent('#selTitle'),/Đã chọn 4 tấm/);
  await pg.click('#selBar [data-r="-1"]'); await pg.waitForTimeout(150);
  assert.deepEqual(calls('/api/rate').slice(-1)[0].body.ids.sort((a,b)=>a-b),[1,2,3,4]);
  // hoàn tác khi máy tính đã sửa 1 ảnh → bỏ qua ảnh đó
  T.st.photos[1].rating=3; T.st.ver++; await pg.evaluate(()=>mSync()); await pg.waitForTimeout(150);
  await pg.evaluate(()=>undoPop()); await pg.waitForTimeout(150);
  assert.deepEqual(calls('/api/rate').slice(-1)[0].body.ids.sort((a,b)=>a-b),[1,3,4]); assert.match(await pg.textContent('#toastT'),/bỏ qua 1 ảnh/);
  // ⋯ → Tự động lọc mức Vừa
  await pg.click('#btnTools'); await pg.waitForTimeout(100); assert.ok(await pg.isVisible('#sheet'));
  const expect=await pg.evaluate(()=>cullCandidates(M.all,['blur','dark','bright','eyes','dup']).length);
  assert.match(await pg.textContent('#cullGo'),new RegExp('Đánh dấu loại '+expect+' /'));
  await pg.click('#cullGo'); await pg.waitForTimeout(150);
  assert.deepEqual(calls('/api/cull/apply').slice(-1)[0].body.ids.length,expect);
  await pg.click('#toastUndo'); await pg.waitForTimeout(150); assert.deepEqual(calls('/api/cull/undo').slice(-1)[0].body,{batch:7});
  // ✦ Chọn ảnh đẹp: 15% → round(0.15*40)=6
  await pg.click('#btnTools'); await pg.waitForTimeout(100);
  assert.match(await pg.textContent('#tInfo'),/gu của bạn \(học từ 12 đám, trùng khớp 78%\)/);
  await pg.fill('#tN','15%'); await pg.click('#tGo'); await pg.waitForTimeout(250);
  assert.deepEqual(calls('/api/suggest').slice(-1)[0].body,{n:6}); assert.equal(await pg.evaluate(()=>M.filter),'sugg');
  assert.ok(!(await pg.isVisible('#sheet')),'đóng bảng sau khi đề xuất');
  // chấm sao cho đề xuất + hoàn tác
  await pg.click('#btnTools'); await pg.waitForTimeout(100); await pg.click('#tRate'); await pg.waitForTimeout(150);
  assert.ok(calls('/api/suggest/rate').length===1); await pg.click('#toastUndo'); await pg.waitForTimeout(150);
  assert.deepEqual(calls('/api/suggest/rate/undo').slice(-1)[0].body,{batch:3});
  // sắp xếp
  await pg.click('#btnTools'); await pg.waitForTimeout(100); await pg.selectOption('#sSort','score'); assert.equal(await pg.evaluate(()=>M.sort),'score');
  await pg.click('#sheetBack'); await pg.waitForTimeout(100);
  await pg.screenshot({path:process.env.SHOT||'/tmp/m-tools.png'});
  // rate failure rollback
  T.st.rateFail=true; await pg.evaluate(()=>openView(20)); await pg.waitForTimeout(150);
  await pg.click('#vstars [data-v="3"]'); await pg.waitForTimeout(200);
  assert.equal(await pg.evaluate(()=>M.by[20].rating),0,'trả lại sao cũ'); assert.match(await pg.textContent('#toastT'),/Không lưu được/);
  assert.deepEqual(T.errs,[]); await T.close();
  console.log('ok (mobile tools)');
})().catch(e=>{console.error(e.message);process.exit(1)});
