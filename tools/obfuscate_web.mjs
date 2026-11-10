// Làm rối giao diện trước khi nhúng vào lõi: JS trong <script> được làm rối (giữ nguyên tên hàm toàn cục mà
// HTML gọi tới như onclick="pickFolder()"), bỏ chú thích HTML/CSS, nén khoảng trắng CSS.
// Cách chạy: node tools/obfuscate_web.mjs <thư mục web nguồn> <thư mục ra>
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(process.cwd() + '/');
const JO = require('javascript-obfuscator');
const [src, out] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const opts = {
  compact: true, simplify: true, target: 'browser',
  renameGlobals: false,            // giữ tên toàn cục: HTML / iframe khác gọi theo tên
  identifierNamesGenerator: 'hexadecimal',
  stringArray: true, stringArrayEncoding: ['base64'], stringArrayThreshold: 0.75,
  stringArrayRotate: true, stringArrayShuffle: true, stringArrayWrappersCount: 1,
  splitStrings: false, controlFlowFlattening: false, deadCodeInjection: false,   // giữ app chạy nhanh
  selfDefending: false, debugProtection: false, disableConsoleOutput: false,
  transformObjectKeys: false, unicodeEscapeSequence: false, numbersToExpressions: false,
  reservedStrings: [], seed: 20261110,
};
const css = s => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\s*\n\s*/g, '\n').replace(/[ \t]{2,}/g, ' ');
for (const f of fs.readdirSync(src)) {
  const p = path.join(src, f);
  if (!f.endsWith('.html') || f.includes(' ')) { if (fs.statSync(p).isFile() && !f.includes(' ')) fs.copyFileSync(p, path.join(out, f)); continue; }
  let h = fs.readFileSync(p, 'utf8');
  let n = 0;
  h = h.replace(/<script>([\s\S]*?)<\/script>/g, (m, js) => {
    n++;
    const r = JO.obfuscate(js, opts).getObfuscatedCode();
    return '<script>' + r.replace(/<\/script/gi, '<\\/script') + '</script>';
  });
  h = h.replace(/<style>([\s\S]*?)<\/style>/g, (m, c) => '<style>' + css(c) + '</style>');
  h = h.replace(/<!--(?!\[if)[\s\S]*?-->/g, '');
  fs.writeFileSync(path.join(out, f), h);
  console.log(f, n, 'script', fs.statSync(p).size, '->', h.length);
}
