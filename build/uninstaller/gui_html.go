package main

const guiHTML = `<!doctype html><html lang="vi"><head><meta charset="utf-8"><title>Gỡ cài đặt MTHANGLEE PhotoSift</title>
<link rel="icon" href="/favicon.ico">
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
 <h1>Gỡ cài đặt PhotoSift</h1><div class="sub">Sẽ xoá phần mềm khỏi máy này</div>
 <label>Thư mục sẽ bị xoá</label><div class="final" style="margin:0 0 14px"><b>__DIR__</b></div>
 <ul><li>Tắt PhotoSift nếu đang chạy, xoá lối tắt Desktop / Start Menu và mục trong Settings › Apps.</li>
 <li>Ảnh gốc của bạn <b>không</b> bị đụng tới.</li></ul>
 <label style="display:flex;gap:10px;align-items:flex-start;text-transform:none;font-size:13px;letter-spacing:0;color:#efe7d6"><input type="checkbox" id="dd" checked style="margin-top:4px">
 <span>Xoá luôn dữ liệu người dùng: điểm sao, nhãn màu, tên người, ảnh cache<br><span style="color:#b9ac90;font-size:12px">__HOME__ — bỏ chọn nếu muốn giữ lại cho lần cài sau</span></span></label>
 <div class="btns"><button id="cancel">Huỷ</button><button class="pri" id="go">Gỡ cài đặt</button></div>
</div>
<div id="p2" class="hide"><h1>Đang gỡ cài đặt…</h1><div class="sub" id="cnt">Vui lòng đợi…</div><div class="bar"><b style="width:60%;animation:p 1.4s infinite alternate"></b></div><pre id="log"></pre></div>
<div id="p3" class="hide"><div class="big">✓</div><h1>Đã gỡ cài đặt sạch</h1><div class="sub">Cảm ơn bạn đã dùng MTHANGLEE PhotoSift.</div><div class="btns"><button class="pri" id="close">Đóng</button></div></div>
<div id="p4" class="hide"><h1 class="err">Chưa gỡ xong</h1><div class="sub" id="emsg"></div><pre id="log2" style="height:100px"></pre><div class="btns"><button class="pri" id="close2">Đóng</button></div></div>
</div>
<style>@keyframes p{from{width:25%}to{width:95%}}</style>
<script>
var T="__TOKEN__",$=function(i){return document.getElementById(i)};
function api(p,b){return fetch(p,{method:b?"POST":"GET",headers:{"X-T":T,"Content-Type":"application/json"},body:b?JSON.stringify(b):undefined}).then(function(r){return r.json()})}
function show(n){["p1","p2","p3","p4"].forEach(function(p,i){$(p).className=(i+1===n)?"":"hide"})}
$("go").onclick=function(){api("/api/start",{DelData:$("dd").checked})};
$("cancel").onclick=$("close").onclick=$("close2").onclick=function(){api("/api/exit",{});setTimeout(function(){window.close()},200)};
function tick(){api("/api/state").then(function(s){
 if(s.phase==="ask")show(1);else if(s.phase==="running"){show(2);$("cnt").textContent=s.n>0?("Đã xoá "+s.n+" mục…"):"Đang tắt PhotoSift và chuẩn bị…";$("log").textContent=s.log.join("\n")}
 else if(s.phase==="done")show(3);else{show(4);$("emsg").textContent=s.err;$("log2").textContent=s.log.join("\n")}
}).catch(function(){})}
setInterval(tick,600);tick();
</script></body></html>`
