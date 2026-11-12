/**
 * MThanglee Cull&Collage — máy chủ TỰ CẤP BẢN QUYỀN VĨNH VIỄN khi khách thanh toán.
 *
 * Luồng: Khách quét VietQR trả 500.000đ (nội dung CK có sẵn "MTCC<mã máy>")
 *   → SePay báo giao dịch về Worker này (webhook)
 *   → Worker kiểm tra số tiền + lấy mã máy → KÝ key vĩnh viễn bằng KHÓA BÁN HÀNG
 *   → ghi vào license/grants.json trên GitHub → app của khách tự tải về và kích hoạt.
 *
 * Secrets (đặt trong Cloudflare, KHÔNG viết vào code):
 *   SEPAY_APIKEY   : chuỗi bí mật bạn đặt, khớp với "API Key" cấu hình ở SePay (xác thực webhook)
 *   SALES_SEED_HEX : 64 ký tự hex — khóa bí mật bán hàng (mình cấp riêng; chỉ đặt ở đây)
 *   GH_TOKEN       : GitHub token (fine-grained, quyền Contents: Read and write cho repo phanmemlocanh)
 *   GH_REPO        : "mthanglee97dnvn/phanmemlocanh"
 *   PRICE          : "500000" (số tiền tối thiểu để cấp vĩnh viễn)
 */

const EPOCH = Date.UTC(2024, 0, 1);
const PERMANENT = 0xFFFF;
const B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

function b32decode(s) {
  s = s.replace(/[^A-Z2-7]/gi, "").toUpperCase();
  let bits = 0, val = 0; const out = [];
  for (const c of s) { val = (val << 5) | B32.indexOf(c); bits += 5; if (bits >= 8) { out.push((val >>> (bits - 8)) & 255); bits -= 8; } }
  return new Uint8Array(out);
}
function b32encode(u) {
  let bits = 0, val = 0, o = "";
  for (const b of u) { val = (val << 8) | b; bits += 8; while (bits >= 5) { o += B32[(val >>> (bits - 5)) & 31]; bits -= 5; } }
  if (bits > 0) o += B32[(val << (5 - bits)) & 31];
  return o;
}
function todayNum() { const d = new Date(); const u = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()); return Math.floor((u - EPOCH) / 86400000); }

async function signKey(seedHex, machine8) {
  // body = [1, serial=0, issued(2B BE), exp=FFFF(2B BE), machine(8B)]
  const body = new Uint8Array(14);
  body[0] = 1; body[1] = 0;
  const iss = todayNum(); body[2] = (iss >>> 8) & 255; body[3] = iss & 255;
  body[4] = (PERMANENT >>> 8) & 255; body[5] = PERMANENT & 255;
  body.set(machine8, 6);
  const msg = new Uint8Array(5 + 14); msg.set([77, 84, 67, 67, 49], 0); msg.set(body, 5); // "MTCC1"
  const seed = Uint8Array.from(seedHex.match(/../g).map(h => parseInt(h, 16)));
  const pkcs8 = new Uint8Array(48);
  pkcs8.set([0x30,0x2e,0x02,0x01,0x00,0x30,0x05,0x06,0x03,0x2b,0x65,0x70,0x04,0x22,0x04,0x20], 0);
  pkcs8.set(seed, 16);
  const key = await crypto.subtle.importKey("pkcs8", pkcs8.buffer, { name: "Ed25519" }, false, ["sign"]);
  const sig = new Uint8Array(await crypto.subtle.sign("Ed25519", key, msg));
  const raw = new Uint8Array(78); raw.set(body, 0); raw.set(sig, 14);
  const t = b32encode(raw);
  const g = []; for (let i = 0; i < t.length; i += 5) g.push(t.slice(i, i + 5));
  return "MTCC-" + g.join("-");
}

function codeDashed(code13) { const t = code13.toUpperCase().replace(/[^A-Z2-7]/g, ""); return t.slice(0,4)+"-"+t.slice(4,8)+"-"+t.slice(8,13); }

async function ghGrant(env, machineDashed, key) {
  const api = `https://api.github.com/repos/${env.GH_REPO}/contents/license/grants.json`;
  const h = { "Authorization": `Bearer ${env.GH_TOKEN}`, "Accept": "application/vnd.github+json", "User-Agent": "mtcc-sales" };
  let data = {}, sha = undefined;
  const cur = await fetch(api + "?ref=main", { headers: h });
  if (cur.ok) { const j = await cur.json(); sha = j.sha; try { data = JSON.parse(atob(j.content.replace(/\n/g, ""))); } catch (e) { data = {}; } }
  if (data[machineDashed] === key) return "unchanged";
  data[machineDashed] = key;
  const body = { message: `grant permanent: ${machineDashed}`, content: btoa(JSON.stringify(data, null, 1)), branch: "main" };
  if (sha) body.sha = sha;
  const put = await fetch(api, { method: "PUT", headers: h, body: JSON.stringify(body) });
  if (!put.ok) throw new Error("GitHub PUT failed: " + put.status + " " + (await put.text()).slice(0, 200));
  return "granted";
}

export default {
  async fetch(request, env) {
    if (request.method === "GET") return new Response("MThanglee sales worker OK", { status: 200 });
    if (request.method !== "POST") return new Response("method", { status: 405 });

    // Xác thực webhook SePay: header "Authorization: Apikey <SEPAY_APIKEY>"
    const auth = request.headers.get("Authorization") || "";
    if (!env.SEPAY_APIKEY || auth !== `Apikey ${env.SEPAY_APIKEY}`) return new Response("unauthorized", { status: 401 });

    let p; try { p = await request.json(); } catch (e) { return new Response("bad json", { status: 400 }); }
    // SePay gửi: transferType "in", transferAmount (số), content/description (nội dung CK)
    const type = (p.transferType || p.type || "in").toLowerCase();
    const amount = Number(p.transferAmount ?? p.amount ?? 0);
    const content = String(p.content ?? p.description ?? p.addInfo ?? "");
    const price = Number(env.PRICE || 500000);
    if (type !== "in") return new Response(JSON.stringify({ skip: "not incoming" }), { status: 200 });
    const m = content.toUpperCase().match(/MTCC([A-Z2-7]{13})/);
    if (!m) return new Response(JSON.stringify({ skip: "no machine code" }), { status: 200 });
    if (amount < price) return new Response(JSON.stringify({ skip: "amount too low", amount }), { status: 200 });

    const machineDashed = codeDashed(m[1]);
    const machine8 = b32decode(m[1]).slice(0, 8);
    if (machine8.length !== 8) return new Response(JSON.stringify({ skip: "bad machine" }), { status: 200 });
    try {
      const key = await signKey(env.SALES_SEED_HEX, machine8);
      const r = await ghGrant(env, machineDashed, key);
      return new Response(JSON.stringify({ ok: true, machine: machineDashed, result: r }), { status: 200, headers: { "content-type": "application/json" } });
    } catch (e) {
      return new Response(JSON.stringify({ ok: false, error: String(e) }), { status: 500 });
    }
  }
};
