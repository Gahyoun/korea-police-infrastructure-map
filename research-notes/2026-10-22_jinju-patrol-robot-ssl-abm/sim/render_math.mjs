#!/usr/bin/env node
// LaTeX 수식 → KaTeX HTML(빌드 시 렌더링). 입력·출력은 JSON 파일.
// 사용법: node render_math.mjs in.json out.json   (in: [{tex, display}], out: [html])
import fs from 'node:fs';
import katex from 'katex';

const [input, output] = process.argv.slice(2);
const items = JSON.parse(fs.readFileSync(input, 'utf8'));
const html = items.map(({tex, display}) => katex.renderToString(tex, {
  displayMode: display, output: 'htmlAndMathml', throwOnError: true, strict: 'ignore',
}));
fs.writeFileSync(output, JSON.stringify(html));
console.log(`수식 ${html.length}개 렌더링`);
