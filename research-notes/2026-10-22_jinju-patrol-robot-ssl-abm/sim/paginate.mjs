#!/usr/bin/env node
// flow HTML(build_report.py 결과)을 A4 쪽으로 나눠 정적 HTML로 저장한다.
// 사용법: node paginate.mjs flow.html report.html
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {createRequire} from 'node:module';

const require = createRequire(import.meta.url);
const {chromium} = require('playwright');
const [input, output] = process.argv.slice(2).map(p => path.resolve(p));

const browser = await chromium.launch();
try {
  const page = await browser.newPage({viewport: {width: 1000, height: 1200}});
  await page.goto(pathToFileURL(input).href, {waitUntil: 'load'});
  await page.evaluate(() => document.fonts.ready);
  const pages = await page.evaluate(() => {
    const flow = document.getElementById('flow');
    const tpl = document.getElementById('page-tpl');
    const blocks = [...flow.children];
    const sheets = [];
    let body;
    const fresh = () => {
      const node = tpl.content.firstElementChild.cloneNode(true);
      flow.before(node);
      body = node.querySelector('.report-body');
      sheets.push(node);
    };
    const over = () => body.scrollHeight > body.clientHeight + 1;
    // 표·목록은 행 단위로 쪼갠다.
    const splittable = el => el.tagName === 'TABLE' || el.tagName === 'UL' || el.tagName === 'OL';
    const rowsOf = el => el.tagName === 'TABLE' ? [...el.tBodies[0].rows] : [...el.children];
    const shell = el => {
      const c = el.cloneNode(true);
      if (c.tagName === 'TABLE') c.tBodies[0].replaceChildren(); else c.replaceChildren();
      return c;
    };
    const holder = c => c.tagName === 'TABLE' ? c.tBodies[0] : c;
    fresh();
    for (let i = 0; i < blocks.length; i++) {
      const el = blocks[i];
      body.appendChild(el);
      if (!over()) continue;
      body.removeChild(el);
      if (splittable(el)) {
        let part = shell(el);
        body.appendChild(part);
        for (const row of rowsOf(el)) {
          holder(part).appendChild(row);
          if (over()) {
            holder(part).removeChild(row);
            const moved = [];
            if (!holder(part).children.length) {
              body.removeChild(part);
              // 첫 행부터 넘치면 앞의 제목도 함께 다음 쪽으로
              while (body.lastElementChild && /^H[23]$/.test(body.lastElementChild.tagName)) moved.unshift(body.removeChild(body.lastElementChild));
            }
            fresh();
            for (const h of moved) body.appendChild(h);
            part = shell(el);
            body.appendChild(part);
            holder(part).appendChild(row);
          }
        }
      } else {
        // 제목이 쪽 끝에 홀로 남지 않게 다음 쪽으로 함께 넘긴다.
        const moved = [];
        while (body.lastElementChild && /^H[23]$/.test(body.lastElementChild.tagName)) moved.unshift(body.removeChild(body.lastElementChild));
        fresh();
        for (const h of moved) body.appendChild(h);
        body.appendChild(el);
      }
    }
    flow.remove(); tpl.remove();
    const total = sheets.length + 1;
    sheets.forEach((s, k) => { s.querySelector('.pno').textContent = `${k + 2} / ${total}`; });
    return total;
  });
  const html = '<!doctype html>\n' + await page.evaluate(() => document.documentElement.outerHTML);
  await fs.writeFile(output, html, 'utf8');
  console.log(JSON.stringify({output, pages}));
} finally { await browser.close(); }
