package main

const guiHTML = `<!doctype html><html lang="vi"><head><meta charset="utf-8"><title>Cài đặt MThanglee Cull&amp;Collage</title>
<link rel="icon" href="/favicon.ico"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{font:14px/1.5 "Segoe UI",system-ui,sans-serif;color:#efe7d6;background:radial-gradient(1200px 600px at 20% -10%,#3a2c16 0,#17120b 55%,#0e0b07 100%);display:flex;align-items:center;justify-content:center;overflow:hidden}
.card{width:min(680px,94vw);padding:34px 40px 30px;border-radius:22px;background:linear-gradient(180deg,rgba(255,255,255,.07),rgba(255,255,255,.03));border:1px solid rgba(214,174,92,.28);box-shadow:0 24px 80px rgba(0,0,0,.55);backdrop-filter:blur(14px)}
.logo{display:block;width:300px;margin:0 auto 6px}
h1{font-size:20px;text-align:center;margin:10px 0 4px;font-weight:600;letter-spacing:.3px}
.sub{text-align:center;color:#b9ac90;margin-bottom:22px}
label{display:block;color:#b9ac90;font-size:12px;margin-bottom:6px;text-transform:uppercase;letter-spacing:.8px}
.row{display:flex;gap:8px}input[type=text]{flex:1;padding:10px 12px;border-radius:10px;border:1px solid rgba(214,174,92,.35);background:rgba(0,0,0,.35);color:#fff;font:inherit;outline:none}
input:focus{border-color:#d6ae5c}
button{font:inherit;cursor:pointer;border-radius:10px;padding:10px 18px;border:1px solid rgba(214,174,92,.45);background:rgba(255,255,255,.06);color:#efe7d6}
button:hover{background:rgba(214,174,92,.16)}
button.pri{background:linear-gradient(180deg,#e2bd6a,#b98f3d);color:#1b1408;font-weight:700;border:0;padding:11px 28px}
button.pri:hover{filter:brightness(1.08)}button:disabled{opacity:.5;cursor:default}
.final{margin:8px 0 0;color:#b9ac90;font-size:12px;word-break:break-all}.final b{color:#e8d6aa;font-weight:600}
ul{margin:18px 0 22px;padding:0;list-style:none;color:#cfc4aa}li{padding:3px 0 3px 22px;position:relative}
li:before{content:"◆";position:absolute;left:0;color:#d6ae5c;font-size:10px;top:7px}
.btns{display:flex;justify-content:flex-end;gap:10px;margin-top:22px}
.steps{margin:16px 0}.st{display:flex;align-items:center;gap:10px;padding:5px 0;color:#7d735f}
.st i{width:20px;height:20px;border-radius:50%;border:1.5px solid #5d5441;display:inline-flex;align-items:center;justify-content:center;font-size:12px;font-style:normal}
.st.on{color:#fff}.st.on i{border-color:#d6ae5c;box-shadow:0 0 0 3px rgba(214,174,92,.2)}
.st.ok{color:#cfc4aa}.st.ok i{background:#d6ae5c;border-color:#d6ae5c;color:#1b1408}
.bar{height:10px;border-radius:99px;background:rgba(255,255,255,.1);overflow:hidden}.bar b{display:block;height:100%;width:0;background:linear-gradient(90deg,#b98f3d,#f0d28a);transition:width .5s}
.pct{display:flex;justify-content:space-between;color:#b9ac90;font-size:12px;margin-top:6px}
pre{margin:14px 0 0;height:96px;overflow:auto;background:rgba(0,0,0,.4);border-radius:10px;padding:8px 10px;font:11px/1.45 Consolas,monospace;color:#a89d84;white-space:pre-wrap;word-break:break-all}
.big{font-size:44px;text-align:center;color:#d6ae5c;margin:8px 0}.err{color:#ff9d8a}
.hide{display:none}.note{color:#b9ac90;font-size:12.5px;text-align:center;margin-top:10px}
</style></head><body><div class="card">
<img class="logo" src="/logo.png" alt="MTHANGLEE STUDIO">
<div id="p1">
 <h1>Cài đặt MThanglee Cull&amp;Collage</h1><div class="sub">Lọc ảnh và dàn trang album</div>
 <label>Thư mục cài đặt</label>
 <div class="row"><input type="text" id="dir" spellcheck="false"><button id="pick">Chọn thư mục…</button></div>
 <div class="final">Sẽ cài vào: <b id="final"></b></div>
 <ul><li>Cần kết nối Internet khi cài đặt (khoảng 3–5 phút, chỉ một lần).</li>
 <li>Cài riêng cho tài khoản của bạn, không cần quyền Admin.</li>
 <li>Tạo lối tắt trên Desktop và Start Menu; gỡ cài đặt trong Settings › Apps.</li></ul>
 <div class="btns"><button id="cancel">Thoát</button><button class="pri" id="go">Cài đặt</button></div>
 <div class="err" id="e1"></div>
</div>
<div id="p2" class="hide">
 <h1>Đang cài đặt…</h1><div class="sub" id="cur">Đang chuẩn bị</div>
 <div class="bar"><b id="bar"></b></div><div class="pct"><span id="ptxt"></span><span id="pp">0%</span></div>
 <div class="steps" id="steps"></div>
 <pre id="log"></pre>
</div>
<div id="p3" class="hide">
 <div class="big">✓</div><h1>Cài đặt hoàn tất</h1>
 <div class="sub"><span id="doneMsg">Lối tắt «MThanglee Cull&amp;Collage» đã có trên Desktop và Start Menu.</span></div>
 <div class="note">Có Internet: dùng đầy đủ, gồm lọc ảnh tối / cháy sáng / nhắm mắt.<br>Không có Internet: vẫn chấm sao, gán màu, lọc mờ/trùng, nhận diện người, xuất ảnh.</div>
 <div class="btns"><button id="close">Đóng</button><button class="pri" id="open">Mở ứng dụng</button></div>
</div>
<div id="p4" class="hide">
 <h1 class="err">Cài đặt chưa thành công</h1>
 <div class="sub" id="emsg"></div>
 <div class="note">Kiểm tra kết nối Internet, tạm tắt phần mềm diệt virus rồi chạy lại bộ cài.<br>Nếu vẫn lỗi, chụp màn hình này gửi cho người hỗ trợ.</div>
 <pre id="log2" style="height:110px"></pre>
 <div class="btns"><button class="pri" id="close2">Đóng</button></div>
</div>
</div>
<script>
var T="__TOKEN__",$=function(i){return document.getElementById(i)};
function api(p,b){return fetch(p,{method:b?"POST":"GET",headers:{"X-T":T,"Content-Type":"application/json"},body:b?JSON.stringify(b):undefined}).then(function(r){return r.json()})}
var NAMES=["Chép ứng dụng &amp; tải thành phần","Cài Python &amp; thư viện xử lý ảnh","Hoàn tất model nhận diện","Tạo lối tắt Desktop &amp; gỡ cài đặt"];
var W=[40,40,10,10],tot=100;
$("steps").innerHTML=NAMES.map(function(n,i){return '<div class="st" id="s'+(i+1)+'"><i>'+(i+1)+'</i>'+n+'</div>'}).join("");
function fin(d){d=d.trim().replace(/[\\\/]+$/,"");var m=d.split(/[\\\/]/).pop();return m.toLowerCase()==="mthanglee cullcollage"?d:d+"\\MThanglee CullCollage"}
function upd(){$("final").textContent=fin($("dir").value||"")}
$("dir").oninput=upd;
var init=false,t4=null,lastStep=0;
$("pick").onclick=function(){$("pick").disabled=true;api("/api/pick",{}).then(function(r){$("pick").disabled=false;if(r.path){$("dir").value=r.path;upd()}})};
$("go").onclick=function(){$("e1").textContent="";api("/api/start",{dir:$("dir").value}).then(function(r){if(r.error)$("e1").textContent=r.error})};
$("cancel").onclick=$("close").onclick=$("close2").onclick=function(){api("/api/exit",{});setTimeout(function(){window.close()},200)};
$("open").onclick=function(){api("/api/launch",{})};
function show(n){["p1","p2","p3","p4"].forEach(function(p,i){$(p).className=(i+1===n)?"":"hide"})}
function tick(){api("/api/state").then(function(s){
 if(!init){init=true;$("dir").value=s.dir;upd()}
 if(s.phase==="welcome")show(1);
 else if(s.phase==="running"){show(2);
  if(s.step!==lastStep){lastStep=s.step;t4=Date.now()}
  var done=0;for(var i=0;i<s.step-1;i++)done+=W[i];
  var f=s.sub/100; if(s.step>=2){f=1-Math.exp(-(Date.now()-t4)/(s.step===2?25000:8000))} 
  var p=Math.min(99,Math.round((done+W[s.step-1]*f)*100/tot));
  $("bar").style.width=p+"%";$("pp").textContent=p+"%";$("cur").innerHTML=(s.text||"Đang chuẩn bị")+"…";
  $("ptxt").textContent="Bước "+s.step+"/4";
  for(var j=1;j<=4;j++)$("s"+j).className="st"+(j<s.step?" ok":(j===s.step?" on":""));
  for(var j=1;j<s.step;j++)$("s"+j).firstChild.textContent="✓";
  var L=$("log");L.textContent=s.log.slice(-40).join("\n");L.scrollTop=L.scrollHeight}
 else if(s.phase==="done"){show(3);if(s.warn)$("doneMsg").textContent=s.warn;if(s.closeIn>0)$("close").textContent="Đóng ("+s.closeIn+")"}
 else if(s.phase==="error"){show(4);$("emsg").textContent=s.err;$("log2").textContent=s.log.slice(-30).join("\n")}
}).catch(function(){})}
setInterval(tick,700);tick();
</script></body></html>`
