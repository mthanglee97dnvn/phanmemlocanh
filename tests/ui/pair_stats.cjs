// Kiểm tra pairStats / sortCmp trong index.html (chạy: node tests/ui/pair_stats.cjs)
const fs=require('fs'),path=require('path'),assert=require('assert');
const src=fs.readFileSync(path.join(__dirname,'../../app/photosift/web/index.html'),'utf8');
const grab=re=>{const m=src.match(re);if(!m)throw new Error('không tìm thấy '+re);return m[0]};
eval(grab(/^const RAWRE=.*$/m).replace(/^const /,'globalThis.')+';');
eval(grab(/^function pairStats\(list\)\{[\s\S]*?^\}/m).replace(/^function pairStats/,'globalThis.pairStats=function'));
const P=(id,dir,name,cam)=>({id,dir,name,cam});
let r=pairStats([P(1,'a','X1.ARW','A'),P(2,'a','x1.jpg','A'),P(3,'a','X2.ARW','A'),P(4,'b','X2.JPG','B'),P(5,'a','I.0001.CR3'),P(6,'a','I.0001.JPG')]);
assert.equal(r.raw,3); assert.equal(r.jpg,3);
assert.deepEqual([...r.odd].sort(),[3,4]);
assert.equal(r.byCam.get('A'),1); assert.equal(r.byCam.get('B'),1);
r=pairStats([P(1,'a','A.JPG'),P(2,'a','B.JPG')]); assert.equal(r.raw,0); assert.equal(r.odd.size,0);
r=pairStats([P(1,'a','A.ARW'),P(2,'a','A.HEIC'),P(3,'a','B.ARW')]); assert.deepEqual([...r.odd],[3]); assert.equal(r.byCam.get('Chưa dò máy'),1);
{
  eval(grab(/^function sortCmp\(key,rev\)\{[\s\S]*?^\}/m).replace(/^function sortCmp/,'globalThis.sortCmp=function'));
  const L=[P(1,'a','B.JPG'),P(2,'a','A.ARW'),P(3,'a','C.ARW')]; L[0].taken=1;L[1].taken=3;L[2].taken=2;
  assert.deepEqual([...L].sort(sortCmp('type',false)).map(p=>p.id),[3,2,1]);
  assert.deepEqual([...L].sort(sortCmp('type',true)).map(p=>p.id),[1,2,3]);
  assert.deepEqual([...L].sort(sortCmp('time',true)).map(p=>p.id),[2,3,1]);
  const O=[P(1,'a','Z.ARW','B'),P(2,'a','Y.ARW','A'),P(3,'a','X.JPG','A')]; O[0].taken=1;O[1].taken=5;O[2].taken=2;
  assert.deepEqual([...O].sort(sortCmp('oddcam',false)).map(p=>p.id),[3,2,1]);
  console.log('ok (pairStats + sortCmp)');
}
