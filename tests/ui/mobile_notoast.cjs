// Xem từng tấm: Giữ/Loại/sao/Chọn tấm này không hiện thông báo đè lên ảnh; nút ↶ vẫn hoàn tác (node tests/ui/mobile_notoast.cjs)
const assert=require('assert'),{open,photo}=require('./mlib.cjs');
(async()=>{
  const ph=[]; for(let i=1;i<=10;i++) ph.push(photo(i));
  for(let i=1;i<=3;i++) Object.assign(ph[i-1],{grp:5,best:i===1?1:0});
  const T=await open({photos:ph}); const pg=T.pg, calls=p=>T.st.calls.filter(c=>c.path===p);
  const shown=()=>pg.evaluate(()=>$('toast').classList.contains('on'));
  await pg.click('.tile[data-id="5"]'); await pg.waitForTimeout(200);
  await pg.click('#vKeep'); await pg.waitForTimeout(200);
  assert.deepEqual(calls('/api/rate').slice(-1)[0].body,{ids:[5],rating:1});
  assert.ok(!(await shown()),'Giữ: không có thông báo');
  await pg.click('#vRej'); await pg.waitForTimeout(200);
  assert.ok(!(await shown()),'Loại: không có thông báo');
  await pg.click('#vstars [data-v="4"]'); await pg.waitForTimeout(200);
  assert.ok(!(await shown()),'Chấm sao: không có thông báo');
  // ↶ vẫn hoàn tác lần chấm sao vừa rồi
  const before=calls('/api/rate').length; await pg.click('#vUndo'); await pg.waitForTimeout(200);
  assert.equal(calls('/api/rate').length,before+1,'↶ gửi hoàn tác');
  // Chọn tấm này trong loạt: không có thông báo
  await pg.waitForTimeout(1500); await pg.click('#vBack'); await pg.waitForTimeout(150);
  await pg.click('.tile[data-id="1"]'); await pg.waitForTimeout(200);
  await pg.click('#pickBtn'); await pg.waitForTimeout(200);
  assert.ok(!(await shown()),'Chọn tấm này: không có thông báo');
  assert.deepEqual(T.errs,[]); await T.close(); console.log('ok');
})().catch(e=>{console.error(e);process.exit(1);});
