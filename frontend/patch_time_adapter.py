import re

def add_to_ts(filepath, new_content):
    with open(filepath, 'r') as f:
        content = f.read()
    
    last_brace_idx = content.rfind('}')
    if last_brace_idx != -1:
        updated = content[:last_brace_idx] + new_content + '\n' + content[last_brace_idx:]
        with open(filepath, 'w') as f:
            f.write(updated)

zh_content = """
  markdown: {
    mermaidLoading: '图表渲染中…',
    noContent: '暂无内容',
    mermaidLoadFail: 'Mermaid 库加载失败，降级为源码展示:',
    copySource: '复制源码',
    mermaidRenderFail: '⚠ 图表渲染失败：{msg}'
  },
"""

en_content = """
  markdown: {
    mermaidLoading: 'Rendering chart…',
    noContent: 'No content',
    mermaidLoadFail: 'Failed to load Mermaid, falling back to source code:',
    copySource: 'Copy source',
    mermaidRenderFail: '⚠ Chart rendering failed: {msg}'
  },
"""

add_to_ts('src/i18n/zh.ts', zh_content)
add_to_ts('src/i18n/en.ts', en_content)

# Patch utils/index.ts
with open('src/utils/index.ts', 'r') as f:
    index_ts = f.read()

if "import { i18n } from '@/i18n'" not in index_ts:
    index_ts = "import { i18n } from '@/i18n'\n" + index_ts

index_ts = index_ts.replace('`${days}天前`', 'i18n.global.t(\'time.daysAgo\', { days })')
index_ts = index_ts.replace('`${hours}小时前`', 'i18n.global.t(\'time.hoursAgo\', { hours })')
index_ts = index_ts.replace('`${minutes}分钟前`', 'i18n.global.t(\'time.minutesAgo\', { minutes })')
index_ts = index_ts.replace("'刚刚'", "i18n.global.t('time.justNow')")

index_ts = index_ts.replace("'待处理'", "i18n.global.t('logList.status.pending')")
index_ts = index_ts.replace("'处理中'", "i18n.global.t('logList.status.processing')")
index_ts = index_ts.replace("'已完成'", "i18n.global.t('logList.status.completed')")
index_ts = index_ts.replace("'失败'", "i18n.global.t('logList.status.failed')")

with open('src/utils/index.ts', 'w') as f:
    f.write(index_ts)


# Patch utils/formatAdapter.ts
with open('src/utils/formatAdapter.ts', 'r') as f:
    format_ts = f.read()

if "import { i18n } from '@/i18n'" not in format_ts:
    format_ts = "import { i18n } from '@/i18n'\n" + format_ts

format_ts = format_ts.replace("button.textContent = '已复制'", "button.textContent = i18n.global.t('adapter.copied')")
format_ts = format_ts.replace("button.textContent = '复制'", "button.textContent = i18n.global.t('adapter.copy')")
format_ts = format_ts.replace(">复制<", ">${i18n.global.t('adapter.copy')}<")
format_ts = format_ts.replace("'缺少分析ID'", "i18n.global.t('adapter.missingId')")
format_ts = format_ts.replace("'缺少查询内容'", "i18n.global.t('adapter.missingQuery')")
format_ts = format_ts.replace("'缺少时间戳'", "i18n.global.t('adapter.missingTimestamp')")
format_ts = format_ts.replace("'缺少分析结果内容'", "i18n.global.t('adapter.missingContent')")

format_ts = format_ts.replace("'日志分析'", "i18n.global.t('adapter.analysisQueryFallback')")
format_ts = format_ts.replace("'执行计划已完成'", "i18n.global.t('adapter.planCompleted')")
format_ts = format_ts.replace("`步骤 ${index + 1}`", "i18n.global.t('adapter.stepFallback', { index: index + 1 })")
format_ts = format_ts.replace("'执行分析步骤'", "i18n.global.t('adapter.reasoningFallback')")
format_ts = format_ts.replace("'使用工具进行分析'", "i18n.global.t('adapter.approachFallback')")
format_ts = format_ts.replace("'获取分析结果'", "i18n.global.t('adapter.expectedFallback')")
format_ts = format_ts.replace("'分析已完成'", "i18n.global.t('adapter.analysisCompleted')")

format_ts = format_ts.replace("'数据分析'", "i18n.global.t('adapter.dataAnalysisFallback')")
format_ts = format_ts.replace("'数据处理完成'", "i18n.global.t('adapter.dataProcessed')")
format_ts = format_ts.replace("'已处理原始数据'", "i18n.global.t('adapter.processedRawData')")
format_ts = format_ts.replace("['请检查数据格式', '考虑使用标准化输出']", "[i18n.global.t('adapter.checkDataFormat'), i18n.global.t('adapter.useStandardOutput')]")

format_ts = format_ts.replace("'分析失败'", "i18n.global.t('adapter.analysisFailedQuery')")
format_ts = format_ts.replace("'分析过程中出现错误'", "i18n.global.t('adapter.analysisFailedContent')")
format_ts = format_ts.replace("`**错误信息:** ${error.message}\\n\\n**原始数据:**\\n\\`\\`\\`json\\n${JSON.stringify(rawData, null, 2)}\\n\\`\\`\\``", "i18n.global.t('adapter.errorInfoMsg', { msg: error.message, data: JSON.stringify(rawData, null, 2) })")
format_ts = format_ts.replace("['检查输入数据格式', '联系技术支持']", "[i18n.global.t('adapter.checkDataFormat'), i18n.global.t('adapter.contactSupport')]")

format_ts = format_ts.replace("'无摘要信息'", "i18n.global.t('adapter.noSummaryInfo')")

format_ts = format_ts.replace('`${days}天前`', 'i18n.global.t(\'time.daysAgo\', { days })')
format_ts = format_ts.replace('`${hours}小时前`', 'i18n.global.t(\'time.hoursAgo\', { hours })')
format_ts = format_ts.replace('`${minutes}分钟前`', 'i18n.global.t(\'time.minutesAgo\', { minutes })')
format_ts = format_ts.replace('`${seconds}秒前`', 'i18n.global.t(\'time.secondsAgo\', { seconds })')

format_ts = format_ts.replace("console.error('格式适配失败:', error)", "console.error('Format adapter failed:', error)")
format_ts = format_ts.replace("console.error('Markdown处理失败:', error)", "console.error('Markdown processing failed:', error)")

with open('src/utils/formatAdapter.ts', 'w') as f:
    f.write(format_ts)

# Patch utils/markdownRenderer.ts
with open('src/utils/markdownRenderer.ts', 'r') as f:
    md_ts = f.read()

if "import { i18n } from '@/i18n'" not in md_ts:
    md_ts = "import { i18n } from '@/i18n'\n" + md_ts

md_ts = md_ts.replace(">图表渲染中…<", ">${i18n.global.t('markdown.mermaidLoading')}<")
md_ts = md_ts.replace(">暂无内容<", ">${i18n.global.t('markdown.noContent')}<")
md_ts = md_ts.replace("'Mermaid 库加载失败，降级为源码展示:'", "i18n.global.t('markdown.mermaidLoadFail')")
md_ts = md_ts.replace('aria-label="复制源码">复制源码', 'aria-label="${i18n.global.t(\'markdown.copySource\')}">${i18n.global.t(\'markdown.copySource\')}')
md_ts = md_ts.replace(">⚠ 图表渲染失败：${escapeHtml(message)}<", ">${i18n.global.t('markdown.mermaidRenderFail', { msg: escapeHtml(message) })}<")

with open('src/utils/markdownRenderer.ts', 'w') as f:
    f.write(md_ts)

