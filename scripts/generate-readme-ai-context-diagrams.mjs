import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, '..');
const outDir = join(root, 'docs', 'diagrams');

const WIDTH = 1800;
const HEIGHT = 1200;

const palette = {
  ink: '#18202f',
  muted: '#5b6577',
  line: '#b7c1d6',
  softLine: '#d7deeb',
  panel: '#ffffff',
  bgTop: '#f6f8fc',
  bgBottom: '#edf3f7',
  project: '#ecf8f3',
  projectStroke: '#2b8a6e',
  route: '#eef4ff',
  routeStroke: '#4269d6',
  output: '#fff7e7',
  outputStroke: '#b7791f',
  agent: '#fbfcff',
  agentStroke: '#6b7894',
  green: '#2f9e73',
  blue: '#4269d6',
  amber: '#d08a16',
  rose: '#cc5c5c',
};

const locales = {
  zh: {
    file: 'raven-ai-context-zh.svg',
    title: 'RavenAIService 多 Agent 与项目上下文关系示意图',
    subtitle: '以“项目”为核心串联日志、代码、设备、版本资产与 Agent 技能，支撑测试、研发、交付、运维闭环协作',
    userTitle: '用户入口',
    userLines: ['测试 / 研发 / 交付 / 运维', 'AI Chat：提问、上传日志、选择项目、触发操作'],
    routeTitle: 'GeneralAgent',
    routeLines: ['统一对话入口', '识别意图并路由到专业 Agent', '汇总上下文与最终答复'],
    projectTitle: '项目上下文包',
    projectLines: ['project_id / project_code 作为隔离与关联键', '每个项目拥有独立日志、仓库、技能与资产上下文'],
    contextsTitle: '系统提供给 AI 的上下文',
    contexts: [
      ['日志与元数据', ['日志文件、metadata.json、问题描述', '环境信息与版本信息']],
      ['代码仓库', ['项目关联仓库、默认分支', '源码路径与提交历史']],
      ['Agent 技能与 Prompt', ['项目级技能、Agent 级技能', 'Prompt 与模型配置']],
      ['设备连接', ['WebSocket 在线状态、能力描述', '心跳与执行结果']],
      ['包与发布物', ['软件包元数据、组件', '版本范围与发布记录']],
      ['会话与追踪', ['历史问答、工具调用轨迹', '用量统计与审计信息']],
    ],
    agentsTitle: '专业 Agent 职责',
    agents: [
      ['LogAnalysisAgent', ['结合日志解析、元数据与项目上下文', '输出根因假设、严重度和建议动作']],
      ['ProjectExpertAgent', ['基于用户选择的项目仓库做源码级问答', '引用文件路径与行号']],
      ['BugFixAgent', ['从日志分析结论出发定位代码问题', '生成修复建议或 Bug 任务']],
      ['DeviceAgent', ['向目标设备转发 AI 指令', '等待执行结果并回传验证信息']],
      ['PackageSearchAgent', ['检索软件包资产', '辅助包选型、版本回溯和发布物治理']],
    ],
    outputTitle: '闭环产出',
    outputs: ['分析结论', '设备执行结果', '修复建议 / Bug 任务', '包推荐 / 版本回溯', '可复用测试资产'],
    loopTitle: '闭环协作',
    loopLines: ['测试发现问题 → AI 分析定位 → 设备联动验证 → 研发修复 → 交付与运维回溯'],
  },
  en: {
    file: 'raven-ai-context-en.svg',
    title: 'RavenAIService Multi-Agent and Project Context Diagram',
    subtitle: 'Projects connect logs, code, devices, release assets, and agent skills into a closed loop for testing, R&D, delivery, and operations',
    userTitle: 'User Entry',
    userLines: ['Testing / R&D / Delivery / Operations', 'AI Chat: ask questions, upload logs, select projects', 'and trigger actions'],
    routeTitle: 'GeneralAgent',
    routeLines: ['Unified chat entry point', 'Detects intent and routes to specialist agents', 'Combines context and final response'],
    projectTitle: 'Project Context Bundle',
    projectLines: ['project_id / project_code isolate and connect assets', 'Each project owns its logs, repos, skills, and asset context'],
    contextsTitle: 'Context Provided by the System to AI',
    contexts: [
      ['Logs and Metadata', ['log files, metadata.json, issue description', 'environment and version data']],
      ['Code Repositories', ['linked project repos, default branch', 'source paths and commit history']],
      ['Agent Skills and Prompts', ['project skills, agent skills', 'prompt and model configuration']],
      ['Device Connections', ['WebSocket online state, capabilities', 'heartbeat and execution results']],
      ['Packages and Releases', ['package metadata and components', 'version ranges and release records']],
      ['Sessions and Traces', ['chat history and tool-call traces', 'usage metrics and audit data']],
    ],
    agentsTitle: 'Specialist Agent Responsibilities',
    agents: [
      ['LogAnalysisAgent', ['Uses parsed logs, metadata, and project context', 'to produce root-cause hypotheses and actions']],
      ['ProjectExpertAgent', ['Answers source-code questions from the selected repo', 'and cites file paths and line numbers']],
      ['BugFixAgent', ['Starts from log analysis conclusions', 'locates code issues and generates fix tasks']],
      ['DeviceAgent', ['Forwards AI instructions to target devices', 'waits for execution and returns validation results']],
      ['PackageSearchAgent', ['Searches package assets for selection', 'version tracing, and release governance']],
    ],
    outputTitle: 'Closed-Loop Outputs',
    outputs: ['Analysis conclusions', 'Device execution results', 'Fix suggestions / bug tasks', 'Package recommendations / version trace', 'Reusable testing assets'],
    loopTitle: 'Collaboration Loop',
    loopLines: ['Issue found in testing → AI analysis → device validation → R&D fix → delivery and operations trace-back'],
  },
};

function escapeXml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

function textLines(lines, x, y, options = {}) {
  const {
    size = 28,
    weight = 400,
    fill = palette.ink,
    gap = Math.round(size * 1.42),
    anchor = 'start',
    family = 'Inter, PingFang SC, Microsoft YaHei, Arial, sans-serif',
  } = options;
  return `<g>
${lines.map((line, index) => `<text x="${x}" y="${y + index * gap}" font-family="${family}" font-size="${size}" font-weight="${weight}" fill="${fill}" text-anchor="${anchor}">${escapeXml(line)}</text>`).join('\n')}
</g>`;
}

function pill(x, y, w, h, text, color, size = 22) {
  return `<g>
  <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="20" fill="${color}" fill-opacity="0.11" stroke="${color}" stroke-width="2"/>
  ${textLines([text], x + w / 2, y + 29, { size, weight: 700, fill: color, anchor: 'middle' })}
</g>`;
}

function iconCircle(cx, cy, color, label) {
  return `<g>
  <circle cx="${cx}" cy="${cy}" r="22" fill="${color}" fill-opacity="0.14" stroke="${color}" stroke-width="2"/>
  ${textLines([label], cx, cy + 8, { size: 21, weight: 800, fill: color, anchor: 'middle' })}
</g>`;
}

function panel(x, y, w, h, title, bodyLines, options = {}) {
  const stroke = options.stroke ?? palette.line;
  const fill = options.fill ?? palette.panel;
  const accent = options.accent ?? stroke;
  const titleSize = options.titleSize ?? 30;
  const bodySize = options.bodySize ?? 22;
  const icon = options.icon ?? '';
  return `<g filter="url(#shadow)">
  <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="22" fill="${fill}" stroke="${stroke}" stroke-width="2.4"/>
  <rect x="${x}" y="${y}" width="${w}" height="8" rx="4" fill="${accent}"/>
  ${icon ? iconCircle(x + 40, y + 48, accent, icon) : ''}
  ${textLines([title], x + (icon ? 78 : 28), y + 58, { size: titleSize, weight: 800, fill: palette.ink })}
  ${textLines(bodyLines, x + 28, y + 103, { size: bodySize, fill: palette.muted, gap: Math.round(bodySize * 1.48) })}
</g>`;
}

function contextGrid(data) {
  const x0 = 130;
  const y0 = 530;
  const w = 465;
  const h = 122;
  const gapX = 38;
  const gapY = 30;
  const icons = ['L', 'C', 'S', 'D', 'P', 'T'];
  const colors = [palette.green, palette.blue, palette.amber, palette.rose, '#7a61c9', '#32899c'];
  return data.contexts.map(([title, desc], idx) => {
    const row = Math.floor(idx / 2);
    const col = idx % 2;
    const x = x0 + col * (w + gapX);
    const y = y0 + row * (h + gapY);
    return `<g>
  <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="18" fill="#ffffff" stroke="${palette.softLine}" stroke-width="2"/>
  ${iconCircle(x + 38, y + 40, colors[idx], icons[idx])}
  ${textLines([title], x + 82, y + 39, { size: 25, weight: 800 })}
  ${textLines(asLines(desc), x + 82, y + 73, { size: 19, fill: palette.muted, gap: 26 })}
</g>`;
  }).join('\n');
}

function agentStack(data) {
  const x = 1210;
  const y0 = 300;
  const w = 500;
  const h = 112;
  const gap = 22;
  const colors = [palette.green, palette.blue, palette.rose, '#32899c', palette.amber];
  return data.agents.map(([name, desc], idx) => {
    const y = y0 + idx * (h + gap);
    return `<g>
  <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="18" fill="${palette.agent}" stroke="${colors[idx]}" stroke-width="2"/>
  <circle cx="${x + 31}" cy="${y + 34}" r="15" fill="${colors[idx]}" fill-opacity="0.18" stroke="${colors[idx]}" stroke-width="2"/>
  ${textLines([String(idx + 1)], x + 31, y + 42, { size: 19, weight: 800, fill: colors[idx], anchor: 'middle' })}
  ${textLines([name], x + 58, y + 38, { size: 24, weight: 800 })}
  ${textLines(asLines(desc), x + 28, y + 70, { size: 18, fill: palette.muted, gap: 24 })}
</g>`;
  }).join('\n');
}

function asLines(value) {
  return Array.isArray(value) ? value : splitShort(value, 34);
}

function splitShort(text, maxChars) {
  const value = String(text);
  if (/[\u3400-\u9fff]/.test(value)) {
    const chunks = [];
    let current = '';
    for (const char of value) {
      current += char;
      if (current.length >= maxChars && /[，、。；,;/ ]/.test(char)) {
        chunks.push(current.trim());
        current = '';
      }
    }
    if (current.trim()) chunks.push(current.trim());
    return chunks.length > 1 ? chunks.slice(0, 2) : [value];
  }
  const words = value.split(/\s+/);
  const lines = [];
  let current = '';
  for (const word of words) {
    const next = current ? `${current} ${word}` : word;
    if (next.length > maxChars && current) {
      lines.push(current);
      current = word;
    } else {
      current = next;
    }
  }
  if (current) lines.push(current);
  return lines.slice(0, 3);
}

function arrow(x1, y1, x2, y2, color = palette.line, dashed = false) {
  return `<path d="M ${x1} ${y1} C ${(x1 + x2) / 2} ${y1}, ${(x1 + x2) / 2} ${y2}, ${x2} ${y2}" fill="none" stroke="${color}" stroke-width="3" stroke-linecap="round"${dashed ? ' stroke-dasharray="9 8"' : ''} marker-end="url(#arrow)"/>`;
}

function render(data) {
  const outputPills = data.outputs.map((label, idx) => pill(128 + idx * 312, 1082, 280, 48, label, [palette.green, palette.blue, palette.rose, palette.amber, '#7a61c9'][idx], 17)).join('\n');

  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${WIDTH}" height="${HEIGHT}" viewBox="0 0 ${WIDTH} ${HEIGHT}" role="img" aria-labelledby="title desc">
<title id="title">${escapeXml(data.title)}</title>
<desc id="desc">${escapeXml(data.subtitle)}</desc>
<defs>
  <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
    <stop offset="0%" stop-color="${palette.bgTop}"/>
    <stop offset="100%" stop-color="${palette.bgBottom}"/>
  </linearGradient>
  <filter id="shadow" x="-10%" y="-10%" width="120%" height="130%">
    <feDropShadow dx="0" dy="12" stdDeviation="14" flood-color="#23304a" flood-opacity="0.10"/>
  </filter>
  <marker id="arrow" markerWidth="12" markerHeight="12" refX="9" refY="3" orient="auto" markerUnits="strokeWidth">
    <path d="M0,0 L0,6 L9,3 z" fill="${palette.line}"/>
  </marker>
</defs>
<rect width="${WIDTH}" height="${HEIGHT}" fill="url(#bg)"/>
<circle cx="1620" cy="132" r="96" fill="#d9eee8" opacity="0.58"/>
<circle cx="112" cy="1060" r="70" fill="#dce7ff" opacity="0.65"/>

${textLines([data.title], 80, 76, { size: 42, weight: 850 })}
${textLines([data.subtitle], 82, 120, { size: 22, fill: palette.muted })}

${panel(82, 174, 510, 170, data.userTitle, data.userLines, { stroke: '#62a986', accent: palette.green, icon: 'U' })}
${panel(720, 174, 520, 170, data.routeTitle, data.routeLines, { stroke: palette.routeStroke, fill: palette.route, accent: palette.routeStroke, icon: 'G', bodySize: 20 })}

${arrow(592, 247, 720, 247, palette.line)}
${arrow(1240, 247, 1210, 345, palette.line)}
${arrow(980, 320, 980, 405, palette.line)}

<g>
  <rect x="82" y="390" width="1060" height="610" rx="30" fill="#fafdff" stroke="${palette.projectStroke}" stroke-width="2.5"/>
  <rect x="82" y="390" width="1060" height="92" rx="30" fill="${palette.project}" stroke="none"/>
  ${iconCircle(128, 414, palette.projectStroke, 'P')}
  ${textLines([data.projectTitle], 170, 426, { size: 31, weight: 850, fill: palette.projectStroke })}
  ${textLines(data.projectLines, 170, 456, { size: 18, fill: palette.muted, gap: 25 })}
  ${textLines([data.contextsTitle], 130, 515, { size: 26, weight: 800, fill: palette.ink })}
  ${contextGrid(data)}
</g>

<g>
  <rect x="1170" y="224" width="590" height="775" rx="30" fill="#fafdff" stroke="${palette.routeStroke}" stroke-width="2.5"/>
  ${textLines([data.agentsTitle], 1210, 264, { size: 30, weight: 850, fill: palette.routeStroke })}
  ${agentStack(data)}
</g>

${arrow(1142, 572, 1170, 572, palette.projectStroke)}
${arrow(1142, 726, 1170, 726, palette.projectStroke)}
${arrow(1170, 880, 1142, 880, palette.outputStroke, true)}

<g filter="url(#shadow)">
  <rect x="82" y="1030" width="1678" height="140" rx="28" fill="${palette.output}" stroke="${palette.outputStroke}" stroke-width="2.5"/>
  ${textLines([data.outputTitle], 128, 1068, { size: 29, weight: 850, fill: palette.outputStroke })}
  ${outputPills}
  ${textLines([`${data.loopTitle}: ${data.loopLines[0]}`], 452, 1067, { size: 20, fill: palette.muted })}
</g>

${arrow(1390, 1030, 850, 922, palette.outputStroke, true)}
</svg>`;
}

mkdirSync(outDir, { recursive: true });

for (const data of Object.values(locales)) {
  writeFileSync(join(outDir, data.file), render(data), 'utf8');
}

console.log(`Generated ${Object.values(locales).length} diagrams in ${outDir}`);
